"""Persistent state so a restart does not re-poll the quota-limited API."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION

_SAVE_DELAY = 30


class FlightSeatsStore:
    """Holds the budget counters and the last result of each watch."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Create the store for one config entry."""
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}"
        )
        self.data: dict[str, Any] = {"quota": {}, "watches": {}}

    async def async_load(self) -> None:
        """Load saved state, tolerating a missing or damaged file."""
        saved = await self._store.async_load()
        if isinstance(saved, dict):
            self.data["quota"] = saved.get("quota") or {}
            self.data["watches"] = saved.get("watches") or {}

    @callback
    def schedule_save(self) -> None:
        """Save soon; repeated calls within the delay collapse into one write."""
        self._store.async_delay_save(lambda: self.data, _SAVE_DELAY)

    async def async_save_now(self) -> None:
        """Write immediately (used on unload)."""
        await self._store.async_save(self.data)

    async def async_remove(self) -> None:
        """Delete the file when the config entry is removed."""
        await self._store.async_remove()

    def watch(self, subentry_id: str) -> dict[str, Any]:
        """Return the saved state of one watch, or an empty dict."""
        return self.data["watches"].get(subentry_id) or {}

    @callback
    def set_watch(self, subentry_id: str, state: dict[str, Any]) -> None:
        """Replace the saved state of one watch and schedule a save."""
        self.data["watches"][subentry_id] = state
        self.schedule_save()

    @callback
    def prune(self, valid_ids: set[str]) -> None:
        """Forget watches that no longer exist."""
        stale = set(self.data["watches"]) - valid_ids
        for subentry_id in stale:
            del self.data["watches"][subentry_id]
        if stale:
            self.schedule_save()
