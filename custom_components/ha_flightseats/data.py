"""Runtime data shared by every platform."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry

from .api import FlightSeatsClient
from .budget import QuotaBudget
from .storage import FlightSeatsStore

if TYPE_CHECKING:
    from .coordinator import FlightSeatsWatchCoordinator


@dataclass
class FlightSeatsData:
    """Objects stored on the config entry as runtime_data."""

    client: FlightSeatsClient
    budget: QuotaBudget
    store: FlightSeatsStore
    coordinators: dict[str, FlightSeatsWatchCoordinator]
    api_key: str
    account_device_id: str
    watch_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


type FlightSeatsConfigEntry = ConfigEntry[FlightSeatsData]
