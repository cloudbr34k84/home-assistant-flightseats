"""Gold lifecycle, diagnostics, translated errors and device metadata."""

import asyncio
import json
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant.common import MockConfigEntry

from custom_components.ha_flightseats import async_remove_config_entry_device
from custom_components.ha_flightseats.const import DOMAIN, ISSUE_NOT_GOLD
from custom_components.ha_flightseats.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.ha_flightseats.repairs import async_create_not_gold_issue

from .conftest import (
    API_KEY,
    flight,
    payload,
    setup_entry,
)
from .test_config_flow import _add_watch, _watch_input
from .test_integration import BEST_POINTS, REMAINING, _coordinator, _respond


async def test_add_and_remove_watch_without_reload(hass, aioclient_mock, mock_entry):
    """New entities appear while existing clients, coordinators and entities stay loaded."""
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    runtime = mock_entry.runtime_data
    coordinator = _coordinator(mock_entry)
    registry = er.async_get(hass)
    old_id = registry.async_get(BEST_POINTS).id
    result = await _add_watch(hass, mock_entry, {**_watch_input(), "name": "New watch"})
    assert result["unique_id"] is None
    await hass.async_block_till_done()
    assert mock_entry.runtime_data is runtime
    assert _coordinator(mock_entry) is coordinator
    assert registry.async_get(BEST_POINTS).id == old_id
    subentry = next(s for s in mock_entry.subentries.values() if s.title == "New watch")
    added = er.async_entries_for_config_entry(registry, mock_entry.entry_id)
    assert len([e for e in added if e.config_subentry_id == subentry.subentry_id]) == 8
    assert hass.states.get("sensor.new_watch_best_points_flightseats") is not None
    new_coordinator = runtime.coordinators[subentry.subentry_id]
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, subentry.subentry_id), mock_entry.entry_id
    )
    assert device is not None
    hass.config_entries.async_remove_subentry(mock_entry, subentry.subentry_id)
    await hass.async_block_till_done()
    assert mock_entry.runtime_data is runtime
    assert subentry.subentry_id not in runtime.coordinators
    assert new_coordinator._shutdown_requested
    assert dr.async_get(hass).async_get(device.id) is None
    assert not [
        e
        for e in er.async_entries_for_config_entry(registry, mock_entry.entry_id)
        if e.config_subentry_id == subentry.subentry_id
    ]
    assert subentry.subentry_id not in runtime.store.data["watches"]
    assert runtime.budget.watches_polling == 1
    assert hass.states.get(REMAINING).attributes["watches_polling"] == 1


async def test_new_watch_failure_does_not_reload_working_watch(
    hass, aioclient_mock, mock_entry
):
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    runtime = mock_entry.runtime_data
    _respond(aioclient_mock, status=500)
    await _add_watch(hass, mock_entry, {**_watch_input(), "name": "Offline"})
    await hass.async_block_till_done()
    assert mock_entry.runtime_data is runtime
    assert mock_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(BEST_POINTS).state == "190000"
    assert (
        hass.states.get("sensor.offline_best_points_flightseats").state
        == STATE_UNAVAILABLE
    )
    _respond(aioclient_mock, payload(flight(points=150000)))
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.offline_check_now_flightseats"},
        blocking=True,
    )
    assert hass.states.get("sensor.offline_best_points_flightseats").state == "150000"


async def test_remove_watch_during_first_poll(hass, aioclient_mock, mock_entry):
    """An in-flight search cannot recreate a watch the user has just deleted."""
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    runtime = mock_entry.runtime_data
    started, finish = asyncio.Event(), asyncio.Event()
    original_search = runtime.client.async_search

    async def delayed(params):
        started.set()
        await finish.wait()
        return await original_search(params)

    with patch.object(runtime.client, "async_search", side_effect=delayed):
        await _add_watch(hass, mock_entry, {**_watch_input(), "name": "Temporary"})
        await started.wait()
        subentry = next(
            s for s in mock_entry.subentries.values() if s.title == "Temporary"
        )
        hass.config_entries.async_remove_subentry(mock_entry, subentry.subentry_id)
        finish.set()
        await hass.async_block_till_done()
    assert subentry.subentry_id not in runtime.coordinators
    assert hass.states.get("sensor.temporary_best_points_flightseats") is None


async def test_stale_device_removal_guard(hass, aioclient_mock, mock_entry):
    await setup_entry(hass, mock_entry, aioclient_mock, payload())
    registry = dr.async_get(hass)
    account = registry.async_get(mock_entry.runtime_data.account_device_id)
    watch = registry.async_get_device_by_identifier(
        (DOMAIN, next(iter(mock_entry.subentries))), mock_entry.entry_id
    )
    assert not await async_remove_config_entry_device(hass, mock_entry, account)
    assert not await async_remove_config_entry_device(hass, mock_entry, watch)
    orphan = registry.async_get_or_create(
        config_entry_id=mock_entry.entry_id,
        identifiers={(DOMAIN, "orphan")},
        name="Old watch",
    )
    assert await async_remove_config_entry_device(hass, mock_entry, orphan)


@pytest.mark.parametrize("source", ["watch", "search", "empty_account"])
async def test_plan_repair_lifecycle(hass, aioclient_mock, mock_entry, source):
    """403 creates an actionable scoped repair; unload preserves it and recovery clears it."""
    if source == "empty_account":
        mock_entry = MockConfigEntry(domain=DOMAIN, data={"api_key": API_KEY})
        mock_entry.add_to_hass(hass)
        _respond(aioclient_mock, status=403)
        assert not await hass.config_entries.async_setup(mock_entry.entry_id)
    else:
        await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
        _respond(aioclient_mock, status=403)
        if source == "watch":
            await _coordinator(mock_entry).async_refresh()
        else:
            with pytest.raises(HomeAssistantError) as error:
                await hass.services.async_call(
                    DOMAIN,
                    "search",
                    {"origins": "SYD", "destinations": "LAX"},
                    blocking=True,
                    return_response=True,
                )
            assert error.value.translation_key == "not_gold"
    issue_id = f"{ISSUE_NOT_GOLD}_{mock_entry.entry_id}"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    if hasattr(issue, "config_entry_id"):
        assert issue.config_entry_id == mock_entry.entry_id
    assert issue.translation_key == "not_gold"
    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    _respond(aioclient_mock, payload())
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    # Watches with fresh caches have not confirmed access yet.
    if source == "search":
        assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
        await hass.services.async_call(
            DOMAIN,
            "search",
            {"origins": "SYD", "destinations": "LAX"},
            blocking=True,
            return_response=True,
        )
    elif source == "watch":
        await _coordinator(mock_entry).async_refresh()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_legacy_ha_repair_removed_with_entry(hass, aioclient_mock, mock_entry):
    """Supported older HA versions without issue-entry links still get cleanup."""
    await setup_entry(hass, mock_entry, aioclient_mock, payload())
    with patch("custom_components.ha_flightseats.repairs._SUPPORTS_ENTRY_LINK", False):
        async_create_not_gold_issue(hass, mock_entry)
    assert await hass.config_entries.async_remove(mock_entry.entry_id)
    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, f"{ISSUE_NOT_GOLD}_{mock_entry.entry_id}"
        )
        is None
    )


@pytest.mark.parametrize(
    "status,key", [(400, "search_rejected"), (500, "cannot_connect")]
)
async def test_translated_service_errors(hass, aioclient_mock, mock_entry, status, key):
    await setup_entry(hass, mock_entry, aioclient_mock, payload())
    _respond(aioclient_mock, status=status)
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            DOMAIN,
            "search",
            {"origins": "SYD", "destinations": "LAX"},
            blocking=True,
            return_response=True,
        )
    assert error.value.translation_domain == DOMAIN
    assert error.value.translation_key == key


async def test_device_metadata_and_entity_categories(hass, aioclient_mock, mock_entry):
    await setup_entry(hass, mock_entry, aioclient_mock, payload())
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), mock_entry.entry_id)
    assert len(devices) == 2
    assert all(
        d.manufacturer == "FlightSeats.io"
        and d.model
        and d.entry_type is dr.DeviceEntryType.SERVICE
        for d in devices
    )
    watch = next(d for d in devices if d.config_subentry_id)
    assert watch.via_device_id == mock_entry.runtime_data.account_device_id
    entities = er.async_get(hass)
    assert (
        entities.async_get(
            "sensor.syd_lax_bus_data_freshness_flightseats"
        ).entity_category
        is EntityCategory.DIAGNOSTIC
    )
    assert (
        entities.async_get("sensor.flightseats_io_api_daily_request_limit").disabled_by
        is er.RegistryEntryDisabler.INTEGRATION
    )
    assert (
        entities.async_get("sensor.syd_lax_bus_earliest_date_flightseats").disabled_by
        is er.RegistryEntryDisabler.INTEGRATION
    )


async def test_diagnostics_after_failure_contains_no_private_data(
    hass, aioclient_mock, mock_entry
):
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    _respond(aioclient_mock, status=500)
    await _coordinator(mock_entry).async_refresh()
    calls = len(aioclient_mock.mock_calls)
    report = await async_get_config_entry_diagnostics(hass, mock_entry)
    serialised = json.dumps(report, allow_nan=False)
    for secret in (API_KEY, "SYD", "LAX", "SYD → LAX BUS"):
        assert secret not in serialised
    assert not next(iter(report["watches"].values()))["last_update_success"]
    assert len(aioclient_mock.mock_calls) == calls


async def test_diagnostics_while_watch_removal_is_pending(
    hass, aioclient_mock, mock_entry
):
    """Diagnostics tolerate the gap between a subentry deletion and reconciliation."""
    await setup_entry(hass, mock_entry, aioclient_mock, payload())
    runtime = mock_entry.runtime_data
    subentry_id = next(iter(mock_entry.subentries))
    async with runtime.watch_lock:
        hass.config_entries.async_remove_subentry(mock_entry, subentry_id)
        report = await async_get_config_entry_diagnostics(hass, mock_entry)
        assert report["watches"] == {}
    await hass.async_block_till_done()
    assert not runtime.coordinators


async def test_unload_cancels_inflight_new_watch(hass, aioclient_mock, mock_entry):
    """Unloading cancels a new watch's pending network request and reconciliation."""
    await setup_entry(hass, mock_entry, aioclient_mock, payload())
    runtime = mock_entry.runtime_data
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def pending(params):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with patch.object(runtime.client, "async_search", side_effect=pending):
        await _add_watch(hass, mock_entry, {**_watch_input(), "name": "Pending"})
        await started.wait()
        assert await hass.config_entries.async_unload(mock_entry.entry_id)
        await hass.async_block_till_done()
    assert cancelled.is_set()
    assert len(runtime.coordinators) == 1
    assert hass.states.get("sensor.pending_best_points_flightseats") is None
