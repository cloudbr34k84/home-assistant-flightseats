"""Button: check a watch now."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .budget import QuotaLowError
from .const import DOMAIN
from .coordinator import FlightSeatsWatchCoordinator
from .data import FlightSeatsConfigEntry
from .entity import FlightSeatsWatchEntity, async_setup_watch_entities

PARALLEL_UPDATES = 1


class CheckNowButton(FlightSeatsWatchEntity, ButtonEntity):
    """Polls the watch immediately, unless that would drain the quota reserve."""

    _attr_translation_key = "check_now"

    def __init__(self, coordinator: FlightSeatsWatchCoordinator) -> None:
        """Initialise the button."""
        super().__init__(coordinator, "check_now")

    @property
    def available(self) -> bool:
        """The button stays usable while a watch is in error, so it can recover."""
        return True

    async def async_press(self) -> None:
        """Run one poll."""
        try:
            await self.coordinator.async_manual_refresh()
        except QuotaLowError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="quota_low",
                translation_placeholders={"remaining": str(err.remaining)},
            ) from err


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FlightSeatsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one button per watch."""
    async_setup_watch_entities(
        hass,
        entry,
        async_add_entities,
        lambda coordinator: [CheckNowButton(coordinator)],
    )
