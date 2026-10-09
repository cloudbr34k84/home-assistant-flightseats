"""Event entity: new availability, price drops and seats that went away."""
from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import EVENT_TYPES, SUBENTRY_TYPE_WATCH
from .coordinator import FlightSeatsWatchCoordinator
from .data import FlightSeatsConfigEntry
from .entity import FlightSeatsWatchEntity

PARALLEL_UPDATES = 0


class AvailabilityEvent(FlightSeatsWatchEntity, EventEntity):
    """Fires once per poll for each kind of change, with the best match as data."""

    _attr_translation_key = "availability"
    _attr_event_types = EVENT_TYPES

    def __init__(self, coordinator: FlightSeatsWatchCoordinator) -> None:
        """Initialise the event entity."""
        super().__init__(coordinator, "availability")
        self._last_poll_id = 0

    async def async_added_to_hass(self) -> None:
        """Ignore the data that already exists when the entity is added."""
        await super().async_added_to_hass()
        if self.coordinator.data is not None:
            self._last_poll_id = self.coordinator.data.poll_id

    @callback
    def _handle_coordinator_update(self) -> None:
        """Trigger events for a poll we have not seen yet."""
        data = self.coordinator.data
        if data is not None and data.poll_id != self._last_poll_id:
            self._last_poll_id = data.poll_id
            for event in data.events:
                self._trigger_event(event["event_type"], event["data"])
        super()._handle_coordinator_update()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FlightSeatsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one event entity per watch."""
    for subentry in entry.subentries.values():
        coordinator = entry.runtime_data.coordinators.get(subentry.subentry_id)
        if subentry.subentry_type != SUBENTRY_TYPE_WATCH or coordinator is None:
            continue
        async_add_entities(
            [AvailabilityEvent(coordinator)],
            config_subentry_id=subentry.subentry_id,
        )
