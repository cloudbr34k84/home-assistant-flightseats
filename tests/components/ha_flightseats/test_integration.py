"""End-to-end tests: setup, quota protection, events and failure handling."""

from datetime import datetime, timezone
from unittest.mock import PropertyMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir

from custom_components.ha_flightseats.api import RateLimit
from custom_components.ha_flightseats.const import DOMAIN, ISSUE_NOT_GOLD
from custom_components.ha_flightseats.coordinator import WatchData

from .conftest import SEARCH_URL, flight, payload, rate_headers, setup_entry

BEST_POINTS = "sensor.syd_lax_bus_best_points_flightseats"
TAXES = "sensor.syd_lax_bus_taxes_for_best_fare_flightseats"
MATCHING = "sensor.syd_lax_bus_matching_flights_flightseats"
FRESHNESS = "sensor.syd_lax_bus_data_freshness_flightseats"
SEATS = "binary_sensor.syd_lax_bus_seats_available_flightseats"
EVENT = "event.syd_lax_bus_availability_flightseats"
BUTTON = "button.syd_lax_bus_check_now_flightseats"
REMAINING = "sensor.flightseats_io_api_requests_remaining_today"


def _coordinator(entry):
    return next(iter(entry.runtime_data.coordinators.values()))


def _respond(aioclient_mock, body=None, *, status=200, remaining=150):
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        SEARCH_URL,
        json=body if body is not None else payload(),
        status=status,
        headers=rate_headers(remaining),
    )


async def test_setup_creates_entities(hass: HomeAssistant, aioclient_mock, mock_entry):
    body = payload(
        flight(points=200000, date="2027-03-10"),
        flight(points=150000, date="2027-03-20", numbers=(("EK", 435), ("EK", 215))),
        flight(seats=1, points=100000),  # one seat: below the watch's minimum of 2
    )
    await setup_entry(hass, mock_entry, aioclient_mock, body, remaining=140)

    assert mock_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(SEATS).state == "on"
    assert hass.states.get(BEST_POINTS).state == "150000"
    assert hass.states.get(BEST_POINTS).attributes["flight_numbers"] == [
        "EK435",
        "EK215",
    ]
    assert hass.states.get(BEST_POINTS).attributes["seats_available"] == 2
    assert hass.states.get(TAXES).state == "890.5"
    assert hass.states.get(TAXES).attributes["unit_of_measurement"] == "AUD"
    matching = hass.states.get(MATCHING)
    assert matching.state == "2"
    assert len(matching.attributes["results"]) == 2
    assert matching.attributes["by_cabin"] == {"BUS": 2}
    assert hass.states.get(FRESHNESS).state.startswith("2027-02-01T03:04:05")
    assert hass.states.get(REMAINING).state == "140"
    assert hass.states.get(REMAINING).attributes["daily_limit"] == 200
    assert len(aioclient_mock.mock_calls) == 1
    # No event on the first poll: it only sets the baseline.
    assert hass.states.get(EVENT).attributes["event_type"] is None


async def test_no_matches(hass: HomeAssistant, aioclient_mock, mock_entry):
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight(seats=1)))
    assert hass.states.get(SEATS).state == "off"
    assert hass.states.get(BEST_POINTS).state == "unknown"
    assert hass.states.get(MATCHING).state == "0"


async def test_restart_costs_no_requests(
    hass: HomeAssistant, aioclient_mock, mock_entry, hass_storage
):
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    assert len(aioclient_mock.mock_calls) == 1
    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    assert mock_entry.state is ConfigEntryState.NOT_LOADED

    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert len(aioclient_mock.mock_calls) == 1  # restored from storage, not polled
    assert hass.states.get(BEST_POINTS).state == "190000"
    assert hass.states.get(SEATS).state == "on"


async def test_coordinator_restore_and_scheduling_edge_cases(
    hass: HomeAssistant, aioclient_mock, mock_entry
):
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    coordinator = _coordinator(mock_entry)

    assert not coordinator._is_fresh(WatchData([], {}, None, 0, True))
    coordinator._store.set_watch(coordinator.subentry_id, {"fetched_at": "bad"})
    assert coordinator._restore() is None
    coordinator._store.set_watch(
        coordinator.subentry_id,
        {"fetched_at": "2027-01-01T00:00:00", "matches": []},
    )
    restored = coordinator._restore()
    assert restored is not None
    assert restored.fetched_at == datetime(2027, 1, 1, tzinfo=timezone.utc)

    with patch.object(
        type(mock_entry.runtime_data.budget),
        "reset_at",
        new_callable=PropertyMock,
        return_value=None,
    ):
        coordinator._schedule_catch_up()
    assert coordinator._catch_up_unsub is None


async def test_new_availability_event(hass: HomeAssistant, aioclient_mock, mock_entry):
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    _respond(
        aioclient_mock, payload(flight(), flight(date="2027-04-01", points=120000))
    )
    await _coordinator(mock_entry).async_manual_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(EVENT)
    assert state.attributes["event_type"] == "new_availability"
    assert state.attributes["points"] == 120000
    assert state.attributes["date"] == "2027-04-01"
    assert state.attributes["count"] == 1
    assert hass.states.get(BEST_POINTS).state == "120000"


async def test_price_drop_event(hass: HomeAssistant, aioclient_mock, mock_entry):
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight(points=200000)))
    _respond(aioclient_mock, payload(flight(points=180000)))
    await _coordinator(mock_entry).async_manual_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(EVENT)
    assert state.attributes["event_type"] == "price_drop"
    assert state.attributes["previous_points"] == 200000


async def test_gone_only_after_two_complete_polls(
    hass: HomeAssistant, aioclient_mock, mock_entry
):
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    coordinator = _coordinator(mock_entry)

    _respond(aioclient_mock, payload())
    await coordinator.async_manual_refresh()
    assert hass.states.get(EVENT).attributes["event_type"] is None
    assert hass.states.get(SEATS).state == "off"

    await coordinator.async_manual_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(EVENT).attributes["event_type"] == "availability_gone"


async def test_truncated_result_never_reports_gone(
    hass: HomeAssistant, aioclient_mock, mock_entry
):
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    coordinator = _coordinator(mock_entry)
    with patch("custom_components.ha_flightseats.coordinator.RESULT_LIMIT", 1):
        # One unrelated flight fills the limit, so the original fare is not proven gone.
        _respond(aioclient_mock, payload(flight(seats=1, date="2027-05-01")))
        for _ in range(4):
            await coordinator.async_manual_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(EVENT).attributes["event_type"] is None
    assert hass.states.get(MATCHING).attributes["api_limit_reached"] is True


async def test_failed_poll_unavailable_and_recovery_logged_once(
    hass: HomeAssistant, aioclient_mock, mock_entry, caplog
):
    """One outage/recovery message; stale values never look current."""
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    coordinator = _coordinator(mock_entry)
    caplog.clear()
    _respond(aioclient_mock, status=500)
    for _ in range(3):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(BEST_POINTS).state == STATE_UNAVAILABLE
        assert hass.states.get(SEATS).state == STATE_UNAVAILABLE
        assert hass.states.get(EVENT).state == STATE_UNAVAILABLE
        assert coordinator.data.matches  # retained for comparison on recovery
    errors = [r for r in caplog.records if "Error fetching" in r.message]
    assert len(errors) == 1
    assert not any("keeping the last data" in r.message for r in caplog.records)
    _respond(aioclient_mock, payload(flight()))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(BEST_POINTS).state == "190000"
    assert (
        len(
            [
                r
                for r in caplog.records
                if "Fetching" in r.message and "recovered" in r.message
            ]
        )
        == 1
    )
    assert coordinator.update_interval.total_seconds() == 6 * 3600


async def test_scheduled_poll_skipped_when_quota_low(
    hass: HomeAssistant, aioclient_mock, mock_entry
):
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    budget = mock_entry.runtime_data.budget
    budget.update(RateLimit(limit=200, remaining=8, reset=4_102_444_800))
    calls = len(aioclient_mock.mock_calls)

    await _coordinator(mock_entry).async_refresh()  # a scheduled (non-manual) poll
    await hass.async_block_till_done()

    assert len(aioclient_mock.mock_calls) == calls  # no request made
    assert hass.states.get(BEST_POINTS).state == STATE_UNAVAILABLE
    assert hass.states.get(REMAINING).state == "8"


async def test_button_polls_and_respects_floor(
    hass: HomeAssistant, aioclient_mock, mock_entry
):
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    budget = mock_entry.runtime_data.budget
    budget.update(RateLimit(limit=200, remaining=8, reset=4_102_444_800))
    calls = len(aioclient_mock.mock_calls)

    # Below the scheduled reserve but above the manual floor: allowed.
    await hass.services.async_call(
        "button", "press", {"entity_id": BUTTON}, blocking=True
    )
    assert len(aioclient_mock.mock_calls) == calls + 1

    budget.update(RateLimit(limit=200, remaining=2, reset=4_102_444_800))
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {"entity_id": BUTTON}, blocking=True
        )
    assert len(aioclient_mock.mock_calls) == calls + 1


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant, aioclient_mock, mock_entry
):
    aioclient_mock.get(
        SEARCH_URL,
        status=401,
        json={"error": {"code": "unauthorized", "message": "bad"}},
    )
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_not_gold_creates_repair(hass: HomeAssistant, aioclient_mock, mock_entry):
    aioclient_mock.get(
        SEARCH_URL, status=403, json={"error": {"code": "forbidden", "message": "no"}}
    )
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, f"{ISSUE_NOT_GOLD}_{mock_entry.entry_id}"
        )
        is not None
    )
    assert mock_entry.state is ConfigEntryState.SETUP_RETRY
    assert hass.states.get(BEST_POINTS) is None

    _respond(aioclient_mock, payload(flight()))
    assert await hass.config_entries.async_reload(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, f"{ISSUE_NOT_GOLD}_{mock_entry.entry_id}"
        )
        is None
    )


async def test_search_action(hass: HomeAssistant, aioclient_mock, mock_entry):
    await setup_entry(
        hass, mock_entry, aioclient_mock, payload(flight()), remaining=100
    )
    _respond(aioclient_mock, payload(flight(), flight(date="2027-03-16")), remaining=99)
    result = await hass.services.async_call(
        DOMAIN,
        "search",
        {
            "origins": "syd",
            "destinations": ["LAX"],
            "cabins": ["BUS"],
            "date_from": "2027-03-01",
        },
        blocking=True,
        return_response=True,
    )
    assert result["count"] == 2
    assert result["results"][0]["fares"][0]["points"] == 190000
    assert result["requests_remaining"] == 99

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "search",
            {"origins": "SYDNEY", "destinations": "LAX"},
            blocking=True,
            return_response=True,
        )
    with pytest.raises(ServiceValidationError):  # 30 x 30 x 365 days
        codes = ",".join(f"A{c}{d}" for c in "ABCDEF" for d in "ABCDE")
        await hass.services.async_call(
            DOMAIN,
            "search",
            {"origins": codes, "destinations": codes},
            blocking=True,
            return_response=True,
        )


async def test_diagnostics_redact_key(
    hass: HomeAssistant, aioclient_mock, mock_entry, hass_client
):
    from pytest_homeassistant.components.diagnostics import (
        get_diagnostics_for_config_entry,
    )

    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, mock_entry)
    assert diagnostics["entry_data"]["api_key"] == "**REDACTED**"
    assert "fs_live_test_key_not_real" not in str(diagnostics)
    watch = next(iter(diagnostics["watches"].values()))
    assert watch["matches"] == 1
    assert diagnostics["budget"]["effective_remaining"] == 150


@pytest.mark.parametrize("with_watch", [False, True])
@pytest.mark.parametrize(
    "status,state",
    [
        (401, ConfigEntryState.SETUP_ERROR),
        (500, ConfigEntryState.SETUP_RETRY),
        (429, ConfigEntryState.SETUP_RETRY),
    ],
)
async def test_initial_connection_failure(
    hass, aioclient_mock, mock_entry, with_watch, status, state
):
    """Startup reports credentials or retries a temporary failure before loading platforms."""
    if not with_watch:
        from pytest_homeassistant.common import MockConfigEntry

        from .conftest import API_KEY

        mock_entry = MockConfigEntry(
            domain=DOMAIN, unique_id=DOMAIN, data={"api_key": API_KEY}
        )
    aioclient_mock.get(SEARCH_URL, status=status, json={}, headers=rate_headers())
    mock_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state is state
    assert hass.states.get(SEATS) is None
    assert hass.services.has_service(DOMAIN, "search")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "search",
            {"origins": "SYD", "destinations": "MEL"},
            blocking=True,
            return_response=True,
        )


async def test_account_without_watches(hass, aioclient_mock):
    """An account is validated even before the first watch is added."""
    from pytest_homeassistant.common import MockConfigEntry

    from .conftest import API_KEY

    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={"api_key": API_KEY})
    await setup_entry(hass, entry, aioclient_mock, payload(), remaining=140)
    assert entry.state is ConfigEntryState.LOADED
    assert len(aioclient_mock.mock_calls) == 1
    assert hass.states.get(REMAINING).state == "140"


async def test_action_exists_without_account(hass):
    """Register actions before any entry exists, with a useful validation error."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    assert hass.services.has_service(DOMAIN, "search")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "search",
            {"origins": "SYD", "destinations": "MEL"},
            blocking=True,
            return_response=True,
        )


async def test_account_setup_preserves_quota_reserve(hass, aioclient_mock):
    """An empty account cannot spend the saved reserve just to validate startup."""
    from homeassistant.exceptions import ConfigEntryNotReady
    from pytest_homeassistant.common import MockConfigEntry

    from custom_components.ha_flightseats import async_setup_entry
    from custom_components.ha_flightseats.budget import QuotaBudget

    from .conftest import API_KEY

    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={"api_key": API_KEY})
    entry.add_to_hass(hass)
    with (
        patch("custom_components.ha_flightseats.FlightSeatsStore.async_load"),
        patch(
            "custom_components.ha_flightseats.QuotaBudget",
            return_value=QuotaBudget({"remaining": 3}),
        ),
    ):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)
    assert not aioclient_mock.mock_calls
