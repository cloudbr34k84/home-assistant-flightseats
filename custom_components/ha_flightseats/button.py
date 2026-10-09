"""Button: check a watch now."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .budget import QuotaLowError
from .const import DOMAIN, SUBENTRY_TYPE_WATCH
from .coordinator import FlightSeatsWatchCoordinator
from .data import FlightSeatsConfigEntry
from .entity import FlightSeatsWatchEntity

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
            raise HomeAssistantError(
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
    for subentry in entry.subentries.values():
        coordinator = entry.runtime_data.coordinators.get(subentry.subentry_id)
        if subentry.subentry_type != SUBENTRY_TYPE_WATCH or coordinator is None:
            continue
        async_add_entities(
            [CheckNowButton(coordinator)],
            config_subentry_id=subentry.subentry_id,
        )
