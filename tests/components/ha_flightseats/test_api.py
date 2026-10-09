"""Tests for the API client."""
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.ha_flightseats.api import (
    FlightSeatsAuthError,
    FlightSeatsBadRequestError,
    FlightSeatsClient,
    FlightSeatsConnectionError,
    FlightSeatsForbiddenError,
    FlightSeatsRateLimitError,
    SearchParams,
)

from .conftest import SEARCH_URL, flight, payload, rate_headers

PARAMS = SearchParams(programs=["QF", "VA"], origins=["SYD", "MEL"], destinations=["LAX"])


def _client(hass: HomeAssistant) -> FlightSeatsClient:
    return FlightSeatsClient(async_get_clientsession(hass), "fs_live_x")


async def test_search_parses_flights_and_headers(hass, aioclient_mock):
    body = payload(
        flight(numbers=(("EK", 435), ("EK", 215))),
        {"program": "QF"},  # unusable: no date
        flight(last_seen=None),
    )
    aioclient_mock.get(SEARCH_URL, json=body, headers=rate_headers(77))
    response = await _client(hass).async_search(PARAMS)
    assert len(response.flights) == 2
    assert response.raw_count == 3
    assert response.rate_limit.remaining == 77
    assert response.rate_limit.limit == 200
    first = response.flights[0]
    assert first.flight_numbers == ["EK435", "EK215"]
    assert first.last_seen.tzinfo is not None
    assert response.flights[1].last_seen is None
    sent = aioclient_mock.mock_calls[0]
    assert sent[3]["Authorization"] == "Bearer fs_live_x"
    assert "programs=QF%2CVA" in str(sent[1]) or "programs=QF,VA" in str(sent[1])


async def test_unknown_fields_and_bad_fares_are_ignored(hass, aioclient_mock):
    item = flight()
    item["somethingNew"] = {"a": 1}
    item["fares"].append({"cabin": "BUS"})  # no points
    aioclient_mock.get(SEARCH_URL, json=payload(item), headers=rate_headers())
    response = await _client(hass).async_search(PARAMS)
    assert len(response.flights[0].fares) == 1


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (400, FlightSeatsBadRequestError),
        (401, FlightSeatsAuthError),
        (403, FlightSeatsForbiddenError),
        (429, FlightSeatsRateLimitError),
        (500, FlightSeatsConnectionError),
    ],
)
async def test_error_mapping(hass, aioclient_mock, status, error):
    aioclient_mock.get(
        SEARCH_URL,
        status=status,
        json={"error": {"code": "x", "message": "nope"}},
        headers=rate_headers(0),
    )
    with pytest.raises(error) as err:
        await _client(hass).async_search(PARAMS)
    assert "fs_live_x" not in str(err.value)
    if status == 429:
        assert err.value.rate_limit.remaining == 0


async def test_connection_failure_and_bad_body(hass, aioclient_mock):
    aioclient_mock.get(SEARCH_URL, exc=TimeoutError)
    with pytest.raises(FlightSeatsConnectionError):
        await _client(hass).async_search(PARAMS)
    aioclient_mock.clear_requests()
    aioclient_mock.get(SEARCH_URL, json={"nope": 1})
    with pytest.raises(FlightSeatsConnectionError):
        await _client(hass).async_search(PARAMS)
