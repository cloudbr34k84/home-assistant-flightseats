"""Entity naming and entity ID migration tests."""
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import flight, payload, setup_entry


async def test_watch_entity_ids_end_with_flightseats(hass: HomeAssistant, aioclient_mock, mock_entry):
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    registry = er.async_get(hass)
    ids = {
        entry.entity_id
        for entry in er.async_entries_for_config_entry(registry, mock_entry.entry_id)
        if entry.config_subentry_id
    }
    assert "sensor.syd_lax_bus_best_points_flightseats" in ids
    assert "binary_sensor.syd_lax_bus_seats_available_flightseats" in ids
    assert "event.syd_lax_bus_availability_flightseats" in ids
    assert "button.syd_lax_bus_check_now_flightseats" in ids
    assert len(ids) == 8 and all(entity_id.endswith("_flightseats") for entity_id in ids)
    # Friendly names do not carry the suffix.
    state = hass.states.get("sensor.syd_lax_bus_best_points_flightseats")
    assert state.attributes["friendly_name"] == "SYD → LAX BUS Best points"
    # The account device keeps its own names, which already contain "flightseats".
    assert hass.states.get("sensor.flightseats_io_api_requests_remaining_today") is not None


async def test_disabled_entity_keeps_its_name_when_enabled(
    hass: HomeAssistant, aioclient_mock, mock_entry
):
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    registry = er.async_get(hass)
    entity_id = "sensor.syd_lax_bus_earliest_date_flightseats"
    registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["friendly_name"] == "SYD → LAX BUS Earliest date"


async def test_legacy_entity_ids_are_renamed(hass: HomeAssistant, aioclient_mock, mock_entry):
    await setup_entry(hass, mock_entry, aioclient_mock, payload(flight()))
    registry = er.async_get(hass)
    assert await hass.config_entries.async_unload(mock_entry.entry_id)

    # Put the registry back the way 0.1.0/0.1.1 left it.
    for entry in er.async_entries_for_config_entry(registry, mock_entry.entry_id):
        if entry.config_subentry_id:
            registry.async_update_entity(
                entry.entity_id, new_entity_id=entry.entity_id.removesuffix("_flightseats")
            )
    assert registry.async_get("sensor.syd_lax_bus_best_points") is not None

    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get("sensor.syd_lax_bus_best_points") is None
    assert registry.async_get("sensor.syd_lax_bus_best_points_flightseats") is not None
    assert hass.states.get("sensor.syd_lax_bus_best_points_flightseats").state == "190000"
    # Running again changes nothing (no _flightseats_flightseats).
    assert await hass.config_entries.async_reload(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get("sensor.syd_lax_bus_best_points_flightseats_flightseats") is None
    assert registry.async_get("sensor.flightseats_io_api_requests_remaining_today") is not None
