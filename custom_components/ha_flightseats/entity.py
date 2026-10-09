"""Base entities and device info."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FlightSeatsWatchCoordinator

MANUFACTURER = "FlightSeats.io"


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
