"""Fixtures and helpers for the FlightSeats.io tests."""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ha_flightseats.const import (
    CONF_API_KEY,
    CONF_CABINS,
    CONF_COOLDOWN_HOURS,
    CONF_DESTINATIONS,
    CONF_INTERVAL_HOURS,
    CONF_MIN_SEATS,
    CONF_ORIGINS,
    CONF_PROGRAMS,
    CONF_REWARD_ONLY,
    DOMAIN,
    SUBENTRY_TYPE_WATCH,
)

SEARCH_URL = re.compile(r"https://flightseats\.io/api/v1/search.*")
API_KEY = "fs_live_test_key_not_real"


def rate_headers(remaining: int = 150) -> dict[str, str]:
    """Return rate-limit headers as the API sends them."""
    reset = int((dt_util.utcnow() + timedelta(hours=6)).timestamp())
    return {
        "X-RateLimit-Limit": "200",
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset),
    }


def flight(
    *,
    origin: str = "SYD",
    destination: str = "LAX",
    date: str = "2027-03-15",
    cabin: str = "BUS",
    seats: int = 2,
    points: int = 190000,
    tax: float = 890.5,
    numbers: tuple[tuple[str, int], ...] = (("QF", 11),),
    last_seen: str | None = "2027-02-01T03:04:05.123Z",
    is_reward: bool = True,
    program: str = "QF",
) -> dict[str, Any]:
    """Build one flight in the API's response shape."""
    return {
        "program": program,
        "origin": origin,
        "destination": destination,
        "date": date,
        "lastSeen": last_seen,
        "durationMinutes": 840,
        "segments": [
            {
                "origin": origin,
                "destination": destination,
                "marketingCarrier": carrier,
                "operatingCarrier": carrier,
                "flightNumber": number,
                "departure": f"{date}T10:30",
                "arrival": f"{date}T06:45",
            }
            for carrier, number in numbers
        ],
        "fares": [
            {
                "cabin": cabin,
                "seats": seats,
                "points": points,
                "tax": tax,
                "currency": "AUD",
                "isReward": is_reward,
            }
        ],
    }


def payload(*flights: dict[str, Any]) -> dict[str, Any]:
    """Wrap flights in a search response body."""
    return {"results": list(flights)}


@pytest.fixture(autouse=True)
def no_request_spacing():
    """Skip the 7 second gap between requests."""
    with patch("custom_components.ha_flightseats.budget.MIN_REQUEST_SPACING", 0):
        yield


@pytest.fixture(autouse=True)
def no_store_writes():
    """Keep tests from writing storage files."""
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        yield


WATCH_DATA = {
    CONF_PROGRAMS: ["QF"],
    CONF_ORIGINS: ["SYD"],
    CONF_DESTINATIONS: ["LAX"],
    CONF_CABINS: ["BUS"],
    CONF_MIN_SEATS: 2,
    CONF_REWARD_ONLY: True,
    CONF_INTERVAL_HOURS: 6,
    CONF_COOLDOWN_HOURS: 12,
}


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    """Return a config entry with one watch."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="FlightSeats.io",
        unique_id=DOMAIN,
        data={CONF_API_KEY: API_KEY},
        subentries_data=[
            ConfigSubentryData(
                data=WATCH_DATA,
                subentry_type=SUBENTRY_TYPE_WATCH,
                title="SYD → LAX BUS",
                unique_id=None,
            )
        ],
    )


async def setup_entry(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    body: dict[str, Any],
    remaining: int = 150,
) -> None:
    """Set up the entry with the API mocked to return body."""
    aioclient_mock.get(SEARCH_URL, json=body, headers=rate_headers(remaining))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
