"""Binary sensor: are there matching reward seats right now."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FlightSeatsWatchCoordinator
from .data import FlightSeatsConfigEntry
from .entity import FlightSeatsWatchEntity, async_setup_watch_entities

PARALLEL_UPDATES = 0


class SeatsAvailableBinarySensor(FlightSeatsWatchEntity, BinarySensorEntity):
    """On when at least one fare meets the watch's cabin, seats and points rules."""

    _attr_translation_key = "seats_available"

    def __init__(self, coordinator: FlightSeatsWatchCoordinator) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, "seats_available")

    @property
    def is_on(self) -> bool | None:
        """Return True when there is at least one matching fare."""
        if (data := self.coordinator.data) is None:
            return None
        return bool(data.matches)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the watch's criteria and the poll time."""
        config = self.coordinator.config
        if (data := self.coordinator.data) is None:
            return {}
        return {
            "matching_flights": len(data.matches),
            "programs": config.programs,
            "origins": config.origins,
            "destinations": config.destinations,
            "cabins": config.cabins,
            "min_seats": config.min_seats,
            "max_points": config.max_points,
            "days_ahead": config.days_ahead,
            "date_from": config.date_from.isoformat() if config.date_from else None,
            "date_to": config.date_to.isoformat() if config.date_to else None,
            "reward_only": config.reward_only,
            "window_expired": data.expired,
            "last_checked": data.fetched_at.isoformat() if data.fetched_at else None,
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FlightSeatsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one binary sensor per watch."""
    async_setup_watch_entities(
        hass,
        entry,
        async_add_entities,
        lambda coordinator: [SeatsAvailableBinarySensor(coordinator)],
    )
