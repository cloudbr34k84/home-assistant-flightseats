"""Sensors: account quota diagnostics and per-watch values."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .budget import QuotaBudget
from .const import MAX_RESULTS_ATTRIBUTE, SCHEDULED_RESERVE, SUBENTRY_TYPE_WATCH
from .coordinator import FlightSeatsWatchCoordinator, WatchData
from .data import FlightSeatsConfigEntry
from .entity import FlightSeatsWatchEntity, account_device_info

PARALLEL_UPDATES = 0

POINTS_UNIT = "points"
_DETAIL_KEYS = (
    "program",
    "origin",
    "destination",
    "date",
    "cabin",
    "flight_numbers",
    "departure",
    "arrival",
    "duration_minutes",
    "stops",
    "is_reward",
    "last_seen",
)


def _pick(match: dict[str, Any] | None, *keys: str) -> dict[str, Any]:
    """Return the chosen keys of a match, or nothing when there is no match."""
    if match is None:
        return {}
    return {key: match.get(key) for key in keys}


# -- per-watch sensors ---------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class WatchSensorDescription(SensorEntityDescription):
    """Describes a sensor computed from a watch's latest data."""

    value_fn: Callable[[WatchData], int | float | date | datetime | None]
    attrs_fn: Callable[[WatchData], dict[str, Any]]


def _best_points_attrs(data: WatchData) -> dict[str, Any]:
    best = data.summary["best"]
    attrs = _pick(best, *_DETAIL_KEYS, "tax", "currency")
    if best is not None:
        attrs["seats_available"] = best["seats"]
    return attrs


def _results_attrs(data: WatchData) -> dict[str, Any]:
    results = [
        {key: value for key, value in match.items() if key != "key"}
        for match in data.matches[:MAX_RESULTS_ATTRIBUTE]
    ]
    return {
        "results": results,
        "results_truncated": len(data.matches) > MAX_RESULTS_ATTRIBUTE,
        "by_program": data.summary["by_program"],
        "by_cabin": data.summary["by_cabin"],
        "api_limit_reached": not data.complete,
    }


def _freshness_attrs(data: WatchData) -> dict[str, Any]:
    oldest = data.summary["oldest_last_seen"]
    return {
        "oldest_last_seen": oldest.isoformat() if oldest else None,
        "flights_without_last_seen": data.summary["without_last_seen"],
    }


def _earliest_date(data: WatchData) -> date | None:
    earliest = data.summary["earliest"]
    return dt_util.parse_date(earliest["date"]) if earliest else None


WATCH_SENSORS: tuple[WatchSensorDescription, ...] = (
    WatchSensorDescription(
        key="best_points",
        translation_key="best_points",
        native_unit_of_measurement=POINTS_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.summary["best"]["points"] if data.summary["best"] else None,
        attrs_fn=_best_points_attrs,
    ),
    WatchSensorDescription(
        key="best_taxes",
        translation_key="best_taxes",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_fn=lambda data: data.summary["best"]["tax"] if data.summary["best"] else None,
        attrs_fn=lambda data: _pick(
            data.summary["best"], "currency", "program", "date", "cabin", "flight_numbers"
        ),
    ),
    WatchSensorDescription(
        key="matching_flights",
        translation_key="matching_flights",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: len(data.matches),
        attrs_fn=_results_attrs,
    ),
    WatchSensorDescription(
        key="data_freshness",
        translation_key="data_freshness",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.summary["newest_last_seen"],
        attrs_fn=_freshness_attrs,
    ),
    WatchSensorDescription(
        key="earliest_date",
        translation_key="earliest_date",
        device_class=SensorDeviceClass.DATE,
        entity_registry_enabled_default=False,
        value_fn=_earliest_date,
        attrs_fn=lambda data: _pick(
            data.summary["earliest"],
            "program",
            "origin",
            "destination",
            "cabin",
            "points",
            "flight_numbers",
        ),
    ),
)


class FlightSeatsWatchSensor(FlightSeatsWatchEntity, SensorEntity):
    """A sensor computed from a watch's latest poll."""

    entity_description: WatchSensorDescription
    # The result list can be large; keep it out of the recorder database.
    _unrecorded_attributes = frozenset({"results"})

    def __init__(
        self,
        coordinator: FlightSeatsWatchCoordinator,
        description: WatchSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | float | date | datetime | None:
        """Return the sensor value."""
        if (data := self.coordinator.data) is None:
            return None
        return self.entity_description.value_fn(data)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Monetary sensors use the currency the API returned for the best fare."""
        if self.entity_description.device_class is SensorDeviceClass.MONETARY:
            data = self.coordinator.data
            best = data.summary["best"] if data is not None else None
            return (best["currency"] or None) if best else None
        return self.entity_description.native_unit_of_measurement

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details of the match behind the value."""
        if (data := self.coordinator.data) is None:
            return {}
        return self.entity_description.attrs_fn(data)


# -- account (quota) sensors ---------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class AccountSensorDescription(SensorEntityDescription):
    """Describes a sensor computed from the shared quota budget."""

    value_fn: Callable[[QuotaBudget], int | datetime | None]
    attrs_fn: Callable[[QuotaBudget], dict[str, Any]]


def _remaining_attrs(budget: QuotaBudget) -> dict[str, Any]:
    reset_at = budget.reset_at
    known = budget.as_of is not None
    return {
        "daily_limit": budget.limit,
        # The count is shared with the website and any other project using the key, so it is
        # only as fresh as the last API response.
        "as_of": budget.as_of.isoformat() if budget.as_of else None,
        "used_today": budget.used_today if known else None,
        "resets_at": reset_at.isoformat() if reset_at else None,
        "last_request_at": (
            budget.last_request_at.isoformat() if budget.last_request_at else None
        ),
        "watches_polling": budget.watches_polling,
        "estimated_daily_usage": round(budget.estimated_daily_usage, 1),
        "reserve": SCHEDULED_RESERVE,
    }


ACCOUNT_SENSORS: tuple[AccountSensorDescription, ...] = (
    AccountSensorDescription(
        key="requests_remaining",
        translation_key="requests_remaining",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda budget: budget.remaining_if_known,
        attrs_fn=_remaining_attrs,
    ),
    AccountSensorDescription(
        key="quota_resets_at",
        translation_key="quota_resets_at",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda budget: budget.reset_at,
        attrs_fn=lambda budget: {"reset_epoch": budget.reset},
    ),
    AccountSensorDescription(
        key="daily_limit",
        translation_key="daily_limit",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda budget: budget.limit,
        attrs_fn=lambda budget: {},
    ),
)


class FlightSeatsAccountSensor(SensorEntity):
    """A quota diagnostic that updates whenever the budget changes."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: AccountSensorDescription

    def __init__(
        self,
        entry: FlightSeatsConfigEntry,
        description: AccountSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        self.entity_description = description
        self._budget = entry.runtime_data.budget
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = account_device_info(entry.entry_id)

    async def async_added_to_hass(self) -> None:
        """Refresh whenever the budget changes."""
        self.async_on_remove(self._budget.async_add_listener(self._handle_update))

    def _handle_update(self) -> None:
        if self.hass is not None:
            self.async_write_ha_state()

    @property
    def native_value(self) -> int | datetime | None:
        """Return the value."""
        return self.entity_description.value_fn(self._budget)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra values for the quota."""
        return self.entity_description.attrs_fn(self._budget)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FlightSeatsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the quota sensors and one set of sensors per watch."""
    async_add_entities(
        FlightSeatsAccountSensor(entry, description) for description in ACCOUNT_SENSORS
    )
    for subentry in entry.subentries.values():
        coordinator = entry.runtime_data.coordinators.get(subentry.subentry_id)
        if subentry.subentry_type != SUBENTRY_TYPE_WATCH or coordinator is None:
            continue
        async_add_entities(
            (FlightSeatsWatchSensor(coordinator, description) for description in WATCH_SENSORS),
            config_subentry_id=subentry.subentry_id,
        )
