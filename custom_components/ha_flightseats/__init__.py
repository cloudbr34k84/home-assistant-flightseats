"""FlightSeats.io integration: watch cached Qantas and Velocity reward seats."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

from .api import (
    FlightSeatsAuthError,
    FlightSeatsClient,
    FlightSeatsError,
    FlightSeatsForbiddenError,
    FlightSeatsRateLimitError,
)
from .budget import QuotaBudget, QuotaLowError
from .const import CONF_API_KEY, DOMAIN, SIGNAL_WATCHES_UPDATED, SUBENTRY_TYPE_WATCH
from .coordinator import FlightSeatsWatchCoordinator
from .data import FlightSeatsConfigEntry, FlightSeatsData
from .entity import ENTITY_ID_SUFFIX, account_device_info
from .matching import WatchConfig
from .repairs import async_clear_not_gold_issue, async_create_not_gold_issue
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
    entry.async_on_unload(store.async_save_now)

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
        api_key=entry.data[CONF_API_KEY],
        client=client,
        budget=budget,
        store=store,
        coordinators=coordinators,
        account_device_id=account_device.id,
    )

    # An account without watches still needs a connection check.
    if not coordinators:
        try:
            await budget.acquire(manual=False)
            response = await client.async_check_connection()
        except FlightSeatsAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except FlightSeatsForbiddenError as err:
            async_create_not_gold_issue(hass, entry)
            raise ConfigEntryError(
                translation_domain=DOMAIN, translation_key="not_gold"
            ) from err
        except FlightSeatsRateLimitError as err:
            budget.rate_limited(err.rate_limit)
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN, translation_key="rate_limited"
            ) from err
        except QuotaLowError as err:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="quota_low",
                translation_placeholders={"remaining": str(err.remaining)},
            ) from err
        except FlightSeatsError as err:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN, translation_key="cannot_connect"
            ) from err
        else:
            async_clear_not_gold_issue(hass, entry)
            budget.update(response.rate_limit)

    # A watch with no saved data polls once here; with fresh saved data it does
    # not touch the API at all, so a restart costs no quota.
    for coordinator in coordinators.values():
        await coordinator.async_config_entry_first_refresh()

    _async_migrate_entity_ids(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Add/remove watches in place; changed searches or credentials reload safely.
    entry.async_on_unload(entry.add_update_listener(_async_update_entry))
    return True


@callback
def _async_migrate_entity_ids(
    hass: HomeAssistant, entry: FlightSeatsConfigEntry
) -> None:
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


async def _async_update_entry(
    hass: HomeAssistant, entry: FlightSeatsConfigEntry
) -> None:
    """Tie in-flight watch reconciliation to the entry's unload lifecycle."""
    if entry.state is not ConfigEntryState.LOADED:
        return
    await entry.async_create_background_task(
        hass, _async_reconcile_watches(hass, entry), "Reconcile FlightSeats watches"
    )


async def _async_reconcile_watches(
    hass: HomeAssistant, entry: FlightSeatsConfigEntry
) -> None:
    """Reconcile watches without reloading existing platforms on additions."""
    runtime = entry.runtime_data
    async with runtime.watch_lock:
        watches = {
            sid: sub
            for sid, sub in entry.subentries.items()
            if sub.subentry_type == SUBENTRY_TYPE_WATCH
        }
        if entry.data[CONF_API_KEY] != runtime.api_key or any(
            coordinator.config != WatchConfig.from_data(watches[sid].data)
            or coordinator.watch_name != watches[sid].title
            for sid, coordinator in runtime.coordinators.items()
            if sid in watches
        ):
            hass.config_entries.async_schedule_reload(entry.entry_id)
            return

        for sid in runtime.coordinators.keys() - watches.keys():
            await runtime.coordinators.pop(sid).async_shutdown()
        runtime.store.prune(set(watches))
        for sid in watches.keys() - runtime.coordinators.keys():
            coordinator = FlightSeatsWatchCoordinator(
                hass, entry, watches[sid], runtime.client, runtime.budget, runtime.store
            )
            # A failed first poll leaves the new watch unavailable and retrying;
            # it must not prevent existing watches from continuing to work.
            await coordinator.async_refresh()
            if sid not in entry.subentries:
                await coordinator.async_shutdown()
                continue
            runtime.coordinators[sid] = coordinator

        runtime.budget.watches_polling = len(runtime.coordinators)
        runtime.budget.estimated_daily_usage = sum(
            24 / c.config.interval_hours for c in runtime.coordinators.values()
        )
        runtime.budget.async_notify_listeners()
        async_dispatcher_send(hass, f"{SIGNAL_WATCHES_UPDATED}_{entry.entry_id}")


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: FlightSeatsConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow orphan devices to be removed; active watches are deleted as subentries."""
    active = {entry.entry_id, *entry.subentries}
    return not any(
        domain == DOMAIN and identifier in active
        for domain, identifier in device_entry.identifiers
    )


async def async_unload_entry(
    hass: HomeAssistant, entry: FlightSeatsConfigEntry
) -> bool:
    """Unload the platforms and flush saved state."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: FlightSeatsConfigEntry
) -> None:
    """Delete saved state when the account is removed."""
    async_clear_not_gold_issue(hass, entry)
    await FlightSeatsStore(hass, entry.entry_id).async_remove()
