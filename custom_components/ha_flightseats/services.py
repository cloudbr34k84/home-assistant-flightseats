"""Actions registered by the integration."""
from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .api import (
    Flight,
    FlightSeatsAuthError,
    FlightSeatsBadRequestError,
    FlightSeatsError,
    FlightSeatsForbiddenError,
    FlightSeatsRateLimitError,
    SearchParams,
)
from .budget import QuotaLowError
from .const import (
    CABINS,
    DOMAIN,
    MAX_PERMUTATIONS,
    PROGRAM_MAX_SEATS,
    PROGRAMS,
)
from .matching import count_permutations, parse_codes, valid_codes

SERVICE_SEARCH = "search"
_MAX_SERVICE_LIMIT = 200

SEARCH_SCHEMA = vol.Schema(
    {
        vol.Optional("programs", default=PROGRAMS): vol.All(
            cv.ensure_list, [vol.In(PROGRAMS)]
        ),
        vol.Required("origins"): vol.Any(cv.string, [cv.string]),
        vol.Required("destinations"): vol.Any(cv.string, [cv.string]),
        vol.Optional("date_from"): cv.date,
        vol.Optional("date_to"): cv.date,
        vol.Optional("cabins", default=[]): vol.All(cv.ensure_list, [vol.In(CABINS)]),
        vol.Optional("seats", default=1): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=max(PROGRAM_MAX_SEATS.values()))
        ),
        vol.Optional("limit", default=100): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=_MAX_SERVICE_LIMIT)
        ),
        vol.Optional("reward_only", default=True): cv.boolean,
    }
)


def _flight_dict(flight: Flight) -> dict[str, Any]:
    return {
        "program": flight.program,
        "origin": flight.origin,
        "destination": flight.destination,
        "date": flight.date.isoformat(),
        "last_seen": flight.last_seen.isoformat() if flight.last_seen else None,
        "duration_minutes": flight.duration_minutes,
        "segments": [
            {
                "origin": segment.origin,
                "destination": segment.destination,
                "marketing_carrier": segment.marketing_carrier,
                "operating_carrier": segment.operating_carrier,
                "flight_number": segment.flight_number,
                "departure": segment.departure,
                "arrival": segment.arrival,
            }
            for segment in flight.segments
        ],
        "fares": [
            {
                "cabin": fare.cabin,
                "seats": fare.seats,
                "points": fare.points,
                "tax": fare.tax,
                "currency": fare.currency,
                "is_reward": fare.is_reward,
            }
            for fare in flight.fares
        ],
    }


def _validation_error(key: str, **placeholders: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders or None,
    )


async def _async_search(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    """Run an ad-hoc search that shares the quota guard."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise _validation_error("not_loaded")
    runtime = entries[0].runtime_data

    origins = parse_codes(call.data["origins"])
    destinations = parse_codes(call.data["destinations"])
    if not valid_codes(origins) or not valid_codes(destinations):
        raise _validation_error("invalid_codes")

    date_from: date | None = call.data.get("date_from")
    date_to: date | None = call.data.get("date_to")
    permutations = count_permutations(
        len(origins),
        len(destinations),
        days_ahead=None,
        date_from=date_from,
        date_to=date_to,
        today=dt_util.utcnow().date(),
    )
    if permutations > MAX_PERMUTATIONS:
        raise _validation_error("too_many_permutations", count=str(permutations))

    params = SearchParams(
        programs=call.data["programs"],
        origins=origins,
        destinations=destinations,
        date_from=date_from,
        date_to=date_to,
        cabins=call.data["cabins"],
        seats=call.data["seats"],
        limit=call.data["limit"],
        reward_only=call.data["reward_only"],
    )
    try:
        await runtime.budget.acquire(manual=True)
    except QuotaLowError as err:
        raise _validation_error("quota_low", remaining=str(err.remaining)) from err
    try:
        response = await runtime.client.async_search(params)
    except FlightSeatsRateLimitError as err:
        runtime.budget.rate_limited(err.rate_limit)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="rate_limited"
        ) from err
    except FlightSeatsAuthError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="auth_failed"
        ) from err
    except FlightSeatsForbiddenError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="not_gold"
        ) from err
    except FlightSeatsBadRequestError as err:
        raise HomeAssistantError(f"FlightSeats.io rejected the search: {err}") from err
    except FlightSeatsError as err:
        raise HomeAssistantError(f"FlightSeats.io search failed: {err}") from err

    runtime.budget.update(response.rate_limit)
    return {
        "count": len(response.flights),
        "results": [_flight_dict(flight) for flight in response.flights],
        "requests_remaining": runtime.budget.effective_remaining,
    }


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""

    async def _handle_search(call: ServiceCall) -> dict[str, Any]:
        return await _async_search(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEARCH,
        _handle_search,
        schema=SEARCH_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
