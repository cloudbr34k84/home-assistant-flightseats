"""Base entities and device info."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SIGNAL_WATCHES_UPDATED
from .coordinator import FlightSeatsWatchCoordinator

if TYPE_CHECKING:
    from .data import FlightSeatsConfigEntry

MANUFACTURER = "FlightSeats.io"
# Appended to every watch entity's ID so they are easy to find: sensor.syd_lax_bus_best_points_flightseats
ENTITY_ID_SUFFIX = "flightseats"


def account_device_info(entry_id: str) -> DeviceInfo:
    """Return the device that holds the quota diagnostics."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name="FlightSeats.io API",
        manufacturer=MANUFACTURER,
        model="Reward seat search API",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://flightseats.io/dashboard?tab=api",
    )


class FlightSeatsWatchEntity(CoordinatorEntity[FlightSeatsWatchCoordinator]):
    """Base class for entities that belong to one watch."""

    _attr_has_entity_name = True

    @property
    def suggested_object_id(self) -> str | None:
        """End the entity ID with _flightseats; friendly names are unchanged."""
        base = super().suggested_object_id
        return f"{base}_{ENTITY_ID_SUFFIX}" if base else base

    def __init__(self, coordinator: FlightSeatsWatchCoordinator, key: str) -> None:
        """Set the unique id and the watch's device."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.subentry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.subentry_id)},
            name=coordinator.watch_name,
            manufacturer=MANUFACTURER,
            model="Reward seat watch",
            entry_type=DeviceEntryType.SERVICE,
            via_device_id=coordinator.config_entry.runtime_data.account_device_id,
        )


@callback
def async_setup_watch_entities(
    hass: HomeAssistant,
    entry: FlightSeatsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[FlightSeatsWatchCoordinator], Iterable[FlightSeatsWatchEntity]],
) -> None:
    """Add each watch once per platform, including watches created after setup."""
    known: set[str] = set()

    @callback
    def _add_watches() -> None:
        coordinators = entry.runtime_data.coordinators
        known.intersection_update(coordinators)
        for subentry_id in coordinators.keys() - known:
            known.add(subentry_id)
            async_add_entities(
                factory(coordinators[subentry_id]), config_subentry_id=subentry_id
            )

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, f"{SIGNAL_WATCHES_UPDATED}_{entry.entry_id}", _add_watches
        )
    )
    _add_watches()
