"""Silver reliability: failures, cleanup, reauthentication and edge cases."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from custom_components.ha_flightseats.api import RateLimit
from custom_components.ha_flightseats.const import DOMAIN, SUBENTRY_TYPE_WATCH

from .conftest import (
    API_KEY,
    SEARCH_URL,
    WATCH_DATA,
    flight,
    payload,
    rate_headers,
    setup_entry,
)
from .test_integration import (
    BEST_POINTS,
    BUTTON,
    MATCHING,
    SEATS,
    TAXES,
    _coordinator,
    _respond,
)


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
async def test_button_reports_api_failure(hass, aioclient_mock, mock_entry, status):
    """The button raises on a failed request, including swallowed coordinator errors."""
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    _respond(aioclient_mock, status=status)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {"entity_id": BUTTON}, blocking=True
        )
    await hass.async_block_till_done()
    assert hass.states.get(BEST_POINTS).state == STATE_UNAVAILABLE
    if status == 401:
        assert any(
            f["context"]["source"] == "reauth"
            for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        )


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
async def test_search_reports_api_failure(hass, aioclient_mock, mock_entry, status):
    """The search action fails explicitly and starts reauth for invalid credentials."""
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    _respond(aioclient_mock, status=status)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "search",
            {"origins": "SYD", "destinations": "MEL"},
            blocking=True,
            return_response=True,
        )
    await hass.async_block_till_done()
    if status == 401:
        assert any(
            f["context"]["source"] == "reauth"
            for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"programs": []},
        {"date_from": "2027-03-20", "date_to": "2027-03-01"},
        {"date_to": "2020-01-01"},
    ],
)
async def test_search_invalid_input_spends_no_quota(
    hass, aioclient_mock, mock_entry, extra
):
    await setup_entry(hass, mock_entry, aioclient_mock, payload())
    calls = len(aioclient_mock.mock_calls)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "search",
            {"origins": "SYD", "destinations": "MEL", **extra},
            blocking=True,
            return_response=True,
        )
    assert len(aioclient_mock.mock_calls) == calls


async def test_search_low_quota(hass, aioclient_mock, mock_entry):
    await setup_entry(hass, mock_entry, aioclient_mock, payload())
    mock_entry.runtime_data.budget.update(RateLimit(remaining=2))
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "search",
            {"origins": "SYD", "destinations": "MEL"},
            blocking=True,
            return_response=True,
        )
    assert len(aioclient_mock.mock_calls) == 1


async def test_unload_cancels_catchup_and_listeners(
    hass, aioclient_mock, mock_entry, freezer
):
    """Quota catchup cannot issue a request after unloading the entry."""
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    runtime = mock_entry.runtime_data
    coordinator = _coordinator(mock_entry)
    reset = dt_util.utcnow() + timedelta(minutes=5)
    runtime.budget.update(RateLimit(remaining=0, reset=int(reset.timestamp())))
    await coordinator.async_refresh()
    assert coordinator._catch_up_unsub is not None
    await coordinator.async_refresh()  # only one catchup timer
    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    assert coordinator._catch_up_unsub is None
    assert not list(coordinator.async_contexts())
    assert not runtime.budget._listeners
    calls = len(aioclient_mock.mock_calls)
    freezer.move_to(reset + timedelta(minutes=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(aioclient_mock.mock_calls) == calls


async def test_quota_reset_refreshes_and_recovers(
    hass, aioclient_mock, mock_entry, freezer
):
    """Resume after daily reset without waiting another six-hour interval."""
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    coordinator = _coordinator(mock_entry)
    reset = dt_util.utcnow() + timedelta(minutes=5)
    mock_entry.runtime_data.budget.update(
        RateLimit(remaining=0, reset=int(reset.timestamp()))
    )
    await coordinator.async_refresh()
    assert hass.states.get(BEST_POINTS).state == STATE_UNAVAILABLE
    _respond(aioclient_mock, payload(flight(points=170000)))
    freezer.move_to(reset + timedelta(minutes=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(BEST_POINTS).state == "170000"
    assert coordinator._catch_up_unsub is None


async def test_unload_failure_does_not_save_or_shutdown(
    hass, aioclient_mock, mock_entry
):
    """Resources remain intact if a platform refuses to unload."""
    await setup_entry(hass, mock_entry, aioclient_mock, payload())
    with (
        patch.object(hass.config_entries, "async_unload_platforms", return_value=False),
        patch.object(mock_entry.runtime_data.store, "async_save_now") as save,
    ):
        assert not await hass.config_entries.async_unload(mock_entry.entry_id)
    save.assert_not_called()
    assert _coordinator(mock_entry)._listeners
    assert not _coordinator(mock_entry)._shutdown_requested


async def test_remove_deletes_persisted_state(
    hass, aioclient_mock, mock_entry, hass_storage
):
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    key = f"{DOMAIN}.{mock_entry.entry_id}"
    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    assert key in hass_storage
    await hass.config_entries.async_remove(mock_entry.entry_id)
    assert key not in hass_storage


async def test_missing_result_reports_unknown(hass, aioclient_mock, mock_entry):
    """No result is unknown rather than a fabricated zero or off value."""
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    _coordinator(mock_entry).async_set_updated_data(None)
    await hass.async_block_till_done()
    for entity_id in (SEATS, BEST_POINTS, TAXES, MATCHING):
        assert hass.states.get(entity_id).state == STATE_UNKNOWN


async def test_unknown_subentry_is_ignored(hass, aioclient_mock):
    """An unsupported saved subentry does not prevent loading supported watches."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"api_key": API_KEY},
        subentries_data=[
            ConfigSubentryData(
                data=WATCH_DATA,
                subentry_type=SUBENTRY_TYPE_WATCH,
                title="SYD → LAX BUS",
                unique_id=None,
            ),
            ConfigSubentryData(
                data={}, subentry_type="future", title="Future", unique_id=None
            ),
        ],
    )
    await setup_entry(hass, entry, aioclient_mock, payload())
    assert entry.state is ConfigEntryState.LOADED
    assert len(entry.runtime_data.coordinators) == 1
    assert hass.states.get(SEATS).state == "off"


async def test_prunes_deleted_watch_cache(
    hass, aioclient_mock, mock_entry, hass_storage
):
    key = f"{DOMAIN}.{mock_entry.entry_id}"
    hass_storage[key] = {
        "version": 1,
        "key": key,
        "data": {"quota": {}, "watches": {"deleted": {"matches": []}}},
    }
    await setup_entry(hass, mock_entry, aioclient_mock, payload())
    assert "deleted" not in mock_entry.runtime_data.store.data["watches"]


async def test_reauth_reloads_and_keeps_entities(hass, aioclient_mock, mock_entry):
    """The new key is used by runtime actions, with all registry identities preserved."""
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    old_client = mock_entry.runtime_data.client
    registry = er.async_get(hass)
    entity_ids = {
        e.entity_id: e.unique_id
        for e in er.async_entries_for_config_entry(registry, mock_entry.entry_id)
    }
    watch_ids = set(mock_entry.subentries)
    result = await mock_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "fs_live_replaced"}
    )
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.LOADED
    assert mock_entry.runtime_data.client is not old_client
    assert set(mock_entry.subentries) == watch_ids
    assert {
        e.entity_id: e.unique_id
        for e in er.async_entries_for_config_entry(registry, mock_entry.entry_id)
    } == entity_ids
    _respond(aioclient_mock, payload(flight()))
    await hass.services.async_call(
        "button", "press", {"entity_id": BUTTON}, blocking=True
    )
    assert (
        aioclient_mock.mock_calls[-1][3]["Authorization"] == "Bearer fs_live_replaced"
    )


async def test_failed_setup_flushes_quota(
    hass, aioclient_mock, mock_entry, hass_storage
):
    """A setup retry keeps the request already spent instead of resetting the budget."""
    aioclient_mock.get(SEARCH_URL, status=500, json={}, headers=rate_headers())
    mock_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    saved = hass_storage[f"{DOMAIN}.{mock_entry.entry_id}"]["data"]
    assert saved["quota"]["requests_today"] == 1
    assert not saved["watches"]


async def test_button_recovers_unavailable_watch(hass, aioclient_mock, mock_entry):
    """A failed data fetch does not disable the user's recovery button."""
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    _respond(aioclient_mock, status=500)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {"entity_id": BUTTON}, blocking=True
        )
    assert hass.states.get(BEST_POINTS).state == STATE_UNAVAILABLE
    assert hass.states.get(BUTTON).state != STATE_UNAVAILABLE
    _respond(aioclient_mock, payload(flight(points=160000)))
    await hass.services.async_call(
        "button", "press", {"entity_id": BUTTON}, blocking=True
    )
    assert hass.states.get(BEST_POINTS).state == "160000"
