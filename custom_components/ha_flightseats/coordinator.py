"""Per-watch data update coordinator."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    FlightSeatsAuthError,
    FlightSeatsBadRequestError,
    FlightSeatsClient,
    FlightSeatsError,
    FlightSeatsForbiddenError,
    FlightSeatsRateLimitError,
)
from .budget import QuotaBudget, QuotaLowError
from .const import (
    DOMAIN,
    ISSUE_NOT_GOLD,
    RESULT_LIMIT,
    TRANSIENT_FAILURES_BEFORE_UNAVAILABLE,
)
from .diff import diff_matches, empty_state
from .matching import WatchConfig, extract_matches, summarise
from .storage import FlightSeatsStore

if TYPE_CHECKING:
    from .data import FlightSeatsConfigEntry

_LOGGER = logging.getLogger(__name__)

_CATCH_UP_DELAY = timedelta(minutes=2)
# After a connection failure, retry sooner than the normal (hours-long) interval.
_RETRY_INTERVAL = timedelta(minutes=30)


@dataclass
class WatchData:
    """The processed result of one poll."""

    matches: list[dict[str, Any]]
    summary: dict[str, Any]
    fetched_at: datetime | None
    raw_count: int
    complete: bool
    poll_id: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    expired: bool = False


class FlightSeatsWatchCoordinator(DataUpdateCoordinator[WatchData]):
    """Polls the search endpoint for one saved search."""

    config_entry: FlightSeatsConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: FlightSeatsConfigEntry,
        subentry: ConfigSubentry,
        client: FlightSeatsClient,
        budget: QuotaBudget,
        store: FlightSeatsStore,
    ) -> None:
        """Initialise the coordinator for one watch."""
        self.subentry_id = subentry.subentry_id
        self.watch_name = subentry.title
        self.config = WatchConfig.from_data(subentry.data)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {subentry.title}",
            update_interval=timedelta(hours=self.config.interval_hours),
            config_entry=entry,
        )
        self._client = client
        self._budget = budget
        self._store = store
        self._diff_state: dict[str, Any] = (
            store.watch(self.subentry_id).get("diff") or empty_state()
        )
        self._normal_interval = self.update_interval
        self._poll_id = 0
        self._failures = 0
        self._manual = False
        self._catch_up_unsub: CALLBACK_TYPE | None = None

    # -- public helpers -------------------------------------------------

    async def async_manual_refresh(self) -> None:
        """Poll now, using the manual part of the quota. Raises QuotaLowError."""
        self._budget.check_manual()
        self._manual = True
        try:
            await self.async_refresh()
        finally:
            self._manual = False

    async def async_shutdown(self) -> None:
        """Cancel the quota catch-up timer, then shut down."""
        self._cancel_catch_up()
        await super().async_shutdown()

    # -- update ----------------------------------------------------------

    async def _async_update_data(self) -> WatchData:
        """Return fresh data, saved data, or the last data when the quota is low."""
        fallback = self.data
        if fallback is None:
            restored = self._restore()
            if restored is not None and self._is_fresh(restored):
                return restored
            fallback = restored

        today = dt_util.utcnow().date()
        if self.config.is_expired(today):
            return WatchData([], summarise([]), None, 0, True, expired=True)

        try:
            await self._budget.acquire(manual=self._manual)
        except QuotaLowError as err:
            _LOGGER.info(
                "Skipping poll of %s: %s", self.watch_name, err
            )
            self._schedule_catch_up()
            return fallback or WatchData([], summarise([]), None, 0, True)

        try:
            response = await self._client.async_search(self.config.search_params(today))
        except FlightSeatsAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except FlightSeatsForbiddenError as err:
            self._create_not_gold_issue()
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="not_gold"
            ) from err
        except FlightSeatsBadRequestError as err:
            raise UpdateFailed(f"FlightSeats.io rejected the search: {err}") from err
        except FlightSeatsRateLimitError as err:
            self._budget.rate_limited(err.rate_limit)
            return self._transient(fallback, err)
        except FlightSeatsError as err:
            return self._transient(fallback, err)

        self._failures = 0
        self.update_interval = self._normal_interval
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_NOT_GOLD)
        self._budget.update(response.rate_limit)

        matches = extract_matches(response.flights, self.config)
        complete = response.raw_count < RESULT_LIMIT
        self._diff_state, events = diff_matches(
            self._diff_state,
            matches,
            complete=complete,
            cooldown=timedelta(hours=self.config.cooldown_hours),
        )
        self._poll_id += 1
        data = WatchData(
            matches=matches,
            summary=summarise(matches),
            fetched_at=dt_util.utcnow(),
            raw_count=response.raw_count,
            complete=complete,
            poll_id=self._poll_id,
            events=events,
        )
        self._save(data)
        return data

    # -- internals ---------------------------------------------------------

    def _transient(self, fallback: WatchData | None, err: Exception) -> WatchData:
        """Keep the last data through brief outages; fail after repeated ones."""
        self._failures += 1
        self.update_interval = min(_RETRY_INTERVAL, self._normal_interval)
        if fallback is not None and self._failures < TRANSIENT_FAILURES_BEFORE_UNAVAILABLE:
            _LOGGER.warning(
                "Poll of %s failed (%s); keeping the last data", self.watch_name, err
            )
            return fallback
        raise UpdateFailed(f"Cannot update {self.watch_name}: {err}") from err

    def _is_fresh(self, data: WatchData) -> bool:
        if data.fetched_at is None or self.update_interval is None:
            return False
        return data.fetched_at + self.update_interval > dt_util.utcnow()

    def _restore(self) -> WatchData | None:
        """Rebuild the last result from storage without calling the API."""
        saved = self._store.watch(self.subentry_id)
        fetched = dt_util.parse_datetime(saved.get("fetched_at") or "")
        matches = saved.get("matches")
        if fetched is None or not isinstance(matches, list):
            return None
        return WatchData(
            matches=matches,
            summary=summarise(matches),
            fetched_at=fetched,
            raw_count=saved.get("raw_count", len(matches)),
            complete=saved.get("complete", True),
        )

    def _save(self, data: WatchData) -> None:
        self._store.set_watch(
            self.subentry_id,
            {
                "fetched_at": data.fetched_at.isoformat() if data.fetched_at else None,
                "matches": data.matches,
                "raw_count": data.raw_count,
                "complete": data.complete,
                "diff": self._diff_state,
            },
        )

    def _create_not_gold_issue(self) -> None:
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            ISSUE_NOT_GOLD,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_NOT_GOLD,
            learn_more_url="https://flightseats.io/pricing",
        )

    @callback
    def _schedule_catch_up(self) -> None:
        """Refresh once the daily allowance resets instead of waiting a full interval."""
        if self._catch_up_unsub is not None:
            return
        when = self._budget.reset_at
        if when is None:
            return
        self._catch_up_unsub = async_track_point_in_utc_time(
            self.hass, self._async_catch_up, when + _CATCH_UP_DELAY
        )

    @callback
    def _cancel_catch_up(self) -> None:
        if self._catch_up_unsub is not None:
            self._catch_up_unsub()
            self._catch_up_unsub = None

    async def _async_catch_up(self, _now: datetime) -> None:
        self._catch_up_unsub = None
        await self.async_request_refresh()
