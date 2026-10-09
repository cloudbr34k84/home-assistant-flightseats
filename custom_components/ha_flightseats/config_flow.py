"""Config flow: the API key (one per account) and watches (subentries)."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    DateSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import dt as dt_util

from .api import (
    FlightSeatsAuthError,
    FlightSeatsBadRequestError,
    FlightSeatsClient,
    FlightSeatsConnectionError,
    FlightSeatsError,
    FlightSeatsForbiddenError,
    FlightSeatsRateLimitError,
    SearchParams,
)
from .const import (
    CABINS,
    CONF_API_KEY,
    CONF_CABINS,
    CONF_COOLDOWN_HOURS,
    CONF_DATE_FROM,
    CONF_DATE_TO,
    CONF_DAYS_AHEAD,
    CONF_DESTINATIONS,
    CONF_INTERVAL_HOURS,
    CONF_MAX_POINTS,
    CONF_MIN_SEATS,
    CONF_NAME,
    CONF_ORIGINS,
    CONF_PROGRAMS,
    CONF_REWARD_ONLY,
    DEFAULT_COOLDOWN_HOURS,
    DEFAULT_DAILY_LIMIT,
    DEFAULT_INTERVAL_HOURS,
    DEFAULT_MIN_SEATS,
    DEFAULT_PROGRAMS,
    DEFAULT_REWARD_ONLY,
    DOMAIN,
    MAX_DAYS_AHEAD,
    MAX_INTERVAL_HOURS,
    MAX_PERMUTATIONS,
    MIN_INTERVAL_HOURS,
    PROGRAM_MAX_SEATS,
    PROGRAMS,
    SCHEDULED_RESERVE,
    SUBENTRY_TYPE_WATCH,
)
from .matching import count_permutations, parse_codes, valid_codes

_LOGGER = logging.getLogger(__name__)

_PROGRAM_LABELS = {"QF": "Qantas", "VA": "Virgin Australia Velocity"}
_CABIN_LABELS = {
    "ECO": "Economy",
    "PRM": "Premium Economy",
    "BUS": "Business",
    "FIR": "First",
}


async def _async_validate_key(hass: HomeAssistant, api_key: str) -> str | None:
    """Return an error key, or None when the key works. Costs one request."""
    client = FlightSeatsClient(async_get_clientsession(hass), api_key)
    today = dt_util.utcnow().date()
    params = SearchParams(
        programs=["QF"],
        origins=["SYD"],
        destinations=["MEL"],
        date_from=today,
        date_to=today,
        limit=1,
    )
    try:
        await client.async_search(params)
    except FlightSeatsAuthError:
        return "invalid_auth"
    except FlightSeatsForbiddenError:
        return "not_gold"
    except FlightSeatsRateLimitError:
        return "rate_limited"
    except FlightSeatsConnectionError:
        return "cannot_connect"
    except (FlightSeatsBadRequestError, FlightSeatsError):
        _LOGGER.exception("Unexpected response while validating the API key")
        return "unknown"
    return None


_KEY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    }
)


class FlightSeatsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the FlightSeats.io account."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Watches are added from the integration page as subentries."""
        return {SUBENTRY_TYPE_WATCH: WatchSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the API key and check it."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}
        if user_input is not None:
            if error := await _async_validate_key(self.hass, user_input[CONF_API_KEY]):
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title="FlightSeats.io",
                    data={CONF_API_KEY: user_input[CONF_API_KEY]},
                )
        return self.async_show_form(
            step_id="user", data_schema=_KEY_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication after the key was rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect a new key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := await _async_validate_key(self.hass, user_input[CONF_API_KEY]):
                errors["base"] = error
            else:
                return self.async_update_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_API_KEY: user_input[CONF_API_KEY]},
                )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=_KEY_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace the key without removing the integration."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := await _async_validate_key(self.hass, user_input[CONF_API_KEY]):
                errors["base"] = error
            else:
                return self.async_update_and_abort(
                    self._get_reconfigure_entry(),
                    data_updates={CONF_API_KEY: user_input[CONF_API_KEY]},
                )
        return self.async_show_form(
            step_id="reconfigure", data_schema=_KEY_SCHEMA, errors=errors
        )


def _number(minimum: int, maximum: int, step: int = 1) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum, max=maximum, step=step, mode=NumberSelectorMode.BOX
        )
    )


def _select(values: list[str], labels: dict[str, str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=v, label=labels[v]) for v in values],
            multiple=True,
            mode=SelectSelectorMode.LIST,
        )
    )


def _auto_name(origins: list[str], destinations: list[str], cabins: list[str]) -> str:
    def _short(codes: list[str]) -> str:
        if len(codes) <= 3:
            return "/".join(codes)
        return "/".join(codes[:3]) + f"+{len(codes) - 3}"

    name = f"{_short(origins)} → {_short(destinations)}"
    return f"{name} {'/'.join(cabins)}" if cabins else name


class WatchSubentryFlow(ConfigSubentryFlow):
    """Add or edit a watch (a saved search)."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a watch."""
        return await self._async_step_watch("user", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit a watch."""
        return await self._async_step_watch("reconfigure", user_input)

    async def _async_step_watch(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry() if step_id == "reconfigure" else None
        defaults: dict[str, Any] = {}
        if subentry is not None:
            defaults = {**subentry.data, CONF_NAME: subentry.title}

        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = self._validate(
                entry, user_input, ignore=subentry.subentry_id if subentry else None
            )
            if not errors:
                title = user_input.get(CONF_NAME) or _auto_name(
                    data[CONF_ORIGINS], data[CONF_DESTINATIONS], data[CONF_CABINS]
                )
                if subentry is not None:
                    return self.async_update_and_abort(
                        entry, subentry, title=title, data=data
                    )
                return self.async_create_entry(title=title, data=data)
            defaults = user_input

        used, allowed = self._budget_numbers(
            entry, ignore=subentry.subentry_id if subentry else None
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self._schema(defaults),
            errors=errors,
            description_placeholders={
                "used": f"{used:.0f}",
                "allowed": str(allowed),
            },
        )

    @staticmethod
    def _budget_numbers(entry: ConfigEntry, ignore: str | None) -> tuple[float, int]:
        """Return (requests per day used by other watches, requests per day allowed)."""
        used = 0.0
        for subentry_id, subentry in entry.subentries.items():
            if subentry_id == ignore or subentry.subentry_type != SUBENTRY_TYPE_WATCH:
                continue
            interval = subentry.data.get(CONF_INTERVAL_HOURS) or DEFAULT_INTERVAL_HOURS
            used += 24 / interval
        limit = DEFAULT_DAILY_LIMIT
        runtime = getattr(entry, "runtime_data", None)
        if runtime is not None:
            limit = runtime.budget.limit
        return used, limit - SCHEDULED_RESERVE

    def _validate(
        self, entry: ConfigEntry, user_input: dict[str, Any], ignore: str | None
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Normalise the form and return (stored data, errors)."""
        errors: dict[str, str] = {}
        programs = list(user_input.get(CONF_PROGRAMS) or [])
        origins = parse_codes(user_input.get(CONF_ORIGINS))
        destinations = parse_codes(user_input.get(CONF_DESTINATIONS))
        cabins = list(user_input.get(CONF_CABINS) or [])
        min_seats = int(user_input.get(CONF_MIN_SEATS) or DEFAULT_MIN_SEATS)
        max_points = int(user_input.get(CONF_MAX_POINTS) or 0) or None
        days_ahead = int(user_input.get(CONF_DAYS_AHEAD) or 0) or None
        date_from = dt_util.parse_date(user_input.get(CONF_DATE_FROM) or "")
        date_to = dt_util.parse_date(user_input.get(CONF_DATE_TO) or "")
        interval = int(user_input.get(CONF_INTERVAL_HOURS) or DEFAULT_INTERVAL_HOURS)
        cooldown = int(user_input.get(CONF_COOLDOWN_HOURS) or 0)
        today = dt_util.utcnow().date()

        if not programs:
            errors[CONF_PROGRAMS] = "no_programs"
        elif min_seats > max(PROGRAM_MAX_SEATS[p] for p in programs):
            errors[CONF_MIN_SEATS] = "too_many_seats"
        if not valid_codes(origins):
            errors[CONF_ORIGINS] = "invalid_codes"
        if not valid_codes(destinations):
            errors[CONF_DESTINATIONS] = "invalid_codes"
        if days_ahead and (date_from or date_to):
            errors[CONF_DAYS_AHEAD] = "date_conflict"
        elif date_from and date_to and date_to < date_from:
            errors[CONF_DATE_TO] = "date_order"
        elif not days_ahead and date_to and date_to < today:
            errors[CONF_DATE_TO] = "window_in_past"

        if not errors:
            permutations = count_permutations(
                len(origins),
                len(destinations),
                days_ahead=days_ahead,
                date_from=date_from,
                date_to=date_to,
                today=today,
            )
            if permutations > MAX_PERMUTATIONS:
                errors["base"] = "too_many_permutations"
            else:
                used, allowed = self._budget_numbers(entry, ignore)
                if used + 24 / interval > allowed:
                    errors[CONF_INTERVAL_HOURS] = "over_budget"

        data = {
            CONF_PROGRAMS: programs,
            CONF_ORIGINS: origins,
            CONF_DESTINATIONS: destinations,
            CONF_CABINS: cabins,
            CONF_MIN_SEATS: min_seats,
            CONF_MAX_POINTS: max_points,
            CONF_DAYS_AHEAD: days_ahead,
            CONF_DATE_FROM: date_from.isoformat() if date_from else None,
            CONF_DATE_TO: date_to.isoformat() if date_to else None,
            CONF_REWARD_ONLY: bool(user_input.get(CONF_REWARD_ONLY, DEFAULT_REWARD_ONLY)),
            CONF_INTERVAL_HOURS: interval,
            CONF_COOLDOWN_HOURS: cooldown,
        }
        return data, errors

    @staticmethod
    def _schema(defaults: Mapping[str, Any]) -> vol.Schema:
        """Build the form, pre-filled from defaults."""

        def _text(value: Any) -> str:
            if isinstance(value, list):
                return ", ".join(value)
            return value or ""

        def _suggest(key: str) -> dict[str, Any]:
            value = defaults.get(key)
            return {"suggested_value": value} if value not in (None, "", []) else {}

        return vol.Schema(
            {
                vol.Optional(CONF_NAME, description=_suggest(CONF_NAME)): TextSelector(),
                vol.Required(
                    CONF_PROGRAMS, default=defaults.get(CONF_PROGRAMS) or DEFAULT_PROGRAMS
                ): _select(PROGRAMS, _PROGRAM_LABELS),
                vol.Required(
                    CONF_ORIGINS,
                    description={"suggested_value": _text(defaults.get(CONF_ORIGINS))},
                ): TextSelector(),
                vol.Required(
                    CONF_DESTINATIONS,
                    description={"suggested_value": _text(defaults.get(CONF_DESTINATIONS))},
                ): TextSelector(),
                vol.Optional(
                    CONF_CABINS, description=_suggest(CONF_CABINS)
                ): _select(CABINS, _CABIN_LABELS),
                vol.Required(
                    CONF_MIN_SEATS, default=defaults.get(CONF_MIN_SEATS) or DEFAULT_MIN_SEATS
                ): _number(1, max(PROGRAM_MAX_SEATS.values())),
                vol.Optional(
                    CONF_MAX_POINTS, description=_suggest(CONF_MAX_POINTS)
                ): _number(0, 2_000_000, 1000),
                vol.Optional(
                    CONF_DAYS_AHEAD, description=_suggest(CONF_DAYS_AHEAD)
                ): _number(0, MAX_DAYS_AHEAD),
                vol.Optional(
                    CONF_DATE_FROM, description=_suggest(CONF_DATE_FROM)
                ): DateSelector(),
                vol.Optional(
                    CONF_DATE_TO, description=_suggest(CONF_DATE_TO)
                ): DateSelector(),
                vol.Required(
                    CONF_REWARD_ONLY,
                    default=defaults.get(CONF_REWARD_ONLY, DEFAULT_REWARD_ONLY),
                ): BooleanSelector(),
                vol.Required(
                    CONF_INTERVAL_HOURS,
                    default=defaults.get(CONF_INTERVAL_HOURS) or DEFAULT_INTERVAL_HOURS,
                ): _number(MIN_INTERVAL_HOURS, MAX_INTERVAL_HOURS),
                vol.Required(
                    CONF_COOLDOWN_HOURS,
                    default=defaults.get(CONF_COOLDOWN_HOURS, DEFAULT_COOLDOWN_HOURS),
                ): _number(0, 168),
            }
        )
