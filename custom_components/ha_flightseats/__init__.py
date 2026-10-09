"""FlightSeats.io integration: watch cached Qantas and Velocity reward seats."""
from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import FlightSeatsClient
from .budget import QuotaBudget
from .const import CONF_API_KEY, DOMAIN, SUBENTRY_TYPE_WATCH
from .coordinator import FlightSeatsWatchCoordinator
from .data import FlightSeatsConfigEntry, FlightSeatsData
from .entity import ENTITY_ID_SUFFIX, account_device_info
from .services import async_setup_services
from .storage import FlightSeatsStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register actions once for the whole integration."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FlightSeatsConfigEntry) -> bool:
    """Set up the account, one coordinator per watch, and the platforms."""
    store = FlightSeatsStore(hass, entry.entry_id)
    await store.async_load()

    budget = QuotaBudget(store.data["quota"])

    def _save_budget() -> None:
        store.data["quota"] = budget.as_dict()
        store.schedule_save()

    budget.set_save_callback(_save_budget)

    client = FlightSeatsClient(async_get_clientsession(hass), entry.data[CONF_API_KEY])

    coordinators: dict[str, FlightSeatsWatchCoordinator] = {}
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_WATCH:
            continue
        coordinators[subentry.subentry_id] = FlightSeatsWatchCoordinator(
            hass, entry, subentry, client, budget, store
        )

    store.prune(set(coordinators))
    budget.watches_polling = len(coordinators)
    budget.estimated_daily_usage = sum(
        24 / coordinator.config.interval_hours for coordinator in coordinators.values()
    )
    account_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **account_device_info(entry.entry_id)
    )
    entry.runtime_data = FlightSeatsData(
        client=client,
        budget=budget,
        store=store,
        coordinators=coordinators,
        account_device_id=account_device.id,
    )

    # A watch with no saved data polls once here; with fresh saved data it does
    # not touch the API at all, so a restart costs no quota.
    for coordinator in coordinators.values():
        entry.async_on_unload(coordinator.async_shutdown)
        await coordinator.async_refresh()

    _async_migrate_entity_ids(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Adding, editing or removing a watch (a subentry) reloads the entry.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


@callback
def _async_migrate_entity_ids(hass: HomeAssistant, entry: FlightSeatsConfigEntry) -> None:
    """Give watch entities created before 0.1.2 the _flightseats ID suffix (history is kept)."""
    registry = er.async_get(hass)
    suffix = f"_{ENTITY_ID_SUFFIX}"
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.config_subentry_id is None or entity.entity_id.endswith(suffix):
            continue  # account entities already carry the name; renamed ones are done
        new_id = f"{entity.entity_id}{suffix}"
        if registry.async_get(new_id) is not None:
            continue
        _LOGGER.info("Renaming %s to %s", entity.entity_id, new_id)
        registry.async_update_entity(entity.entity_id, new_entity_id=new_id)


async def _async_reload_entry(hass: HomeAssistant, entry: FlightSeatsConfigEntry) -> None:
    """Reload after the entry or one of its subentries changed."""
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: FlightSeatsConfigEntry) -> bool:
    """Unload the platforms and flush saved state."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.store.async_save_now()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: FlightSeatsConfigEntry) -> None:
    """Delete saved state when the account is removed."""
    await FlightSeatsStore(hass, entry.entry_id).async_remove()
