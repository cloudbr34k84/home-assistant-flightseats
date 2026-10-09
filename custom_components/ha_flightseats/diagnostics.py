"""Diagnostics for the FlightSeats.io integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY
from .data import FlightSeatsConfigEntry

TO_REDACT = [CONF_API_KEY]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FlightSeatsConfigEntry
) -> dict[str, Any]:
    """Return diagnostics. Makes no API request, so it costs no quota."""
    runtime = entry.runtime_data
    budget = runtime.budget
    watches = {}
    for subentry_id, coordinator in runtime.coordinators.items():
        data = coordinator.data
        watches[subentry_id] = {
            "title": coordinator.watch_name,
            "config": dict(entry.subentries[subentry_id].data),
            "last_update_success": coordinator.last_update_success,
            "update_interval_hours": (
                coordinator.update_interval.total_seconds() / 3600
                if coordinator.update_interval
                else None
            ),
            "matches": len(data.matches) if data else None,
            "complete": data.complete if data else None,
            "fetched_at": (
                data.fetched_at.isoformat() if data and data.fetched_at else None
            ),
        }
    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "budget": budget.as_dict()
        | {
            "effective_remaining": budget.effective_remaining,
            "watches_polling": budget.watches_polling,
            "estimated_daily_usage": budget.estimated_daily_usage,
        },
        "watches": watches,
    }
