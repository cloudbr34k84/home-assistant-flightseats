"""Shared request budget for the FlightSeats.io daily and per-minute limits.

The 200 requests per UTC day allowance belongs to the Gold account and is
shared with the website and every API key, so the budget trusts the
X-RateLimit-* headers over its own count and keeps a reserve for manual use.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from .api import RateLimit
from .const import (
    DEFAULT_DAILY_LIMIT,
    MANUAL_FLOOR,
    MIN_REQUEST_SPACING,
    SCHEDULED_RESERVE,
)

_PER_MINUTE_BLOCK = 65.0


class QuotaLowError(Exception):
    """Raised instead of making a request that would eat into the reserve."""

    def __init__(self, remaining: int, floor: int, manual: bool) -> None:
        """Record how much is left and the floor that applied."""
        super().__init__(f"{remaining} requests remaining (floor {floor})")
        self.remaining = remaining
        self.floor = floor
        self.manual = manual


class QuotaBudget:
    """Tracks remaining requests and spaces calls to respect 10 per minute."""

    def __init__(self, saved: dict[str, Any] | None = None) -> None:
        """Restore counters saved before a restart."""
        saved = saved or {}
        self.limit: int = saved.get("limit") or DEFAULT_DAILY_LIMIT
        self.remaining: int | None = saved.get("remaining")
        self.reset: int | None = saved.get("reset")  # UTC epoch seconds
        self.requests_today: int = saved.get("requests_today", 0)
        self.counted_day: str = saved.get("counted_day", "")
        self.last_request_at: datetime | None = (
            dt_util.parse_datetime(saved["last_request_at"])
            if saved.get("last_request_at")
            else None
        )
        self.watches_polling: int = 0
        self.estimated_daily_usage: float = 0.0
        self._lock = asyncio.Lock()
        self._last_monotonic: float | None = None
        self._blocked_until: float = 0.0
        self._listeners: list[Callable[[], None]] = []
        self._save_callback: Callable[[], None] | None = None

    # -- persistence and listeners -------------------------------------

    def as_dict(self) -> dict[str, Any]:
        """Return the values worth keeping across a restart."""
        return {
            "limit": self.limit,
            "remaining": self.remaining,
            "reset": self.reset,
            "requests_today": self.requests_today,
            "counted_day": self.counted_day,
            "last_request_at": (
                self.last_request_at.isoformat() if self.last_request_at else None
            ),
        }

    def set_save_callback(self, save: Callable[[], None]) -> None:
        """Register a callback that schedules a save of the store."""
        self._save_callback = save

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        """Call update whenever the budget changes; returns an unsubscribe."""
        self._listeners.append(update)

        @callback
        def _remove() -> None:
            if update in self._listeners:
                self._listeners.remove(update)

        return _remove

    def _changed(self) -> None:
        if self._save_callback:
            self._save_callback()
        for update in list(self._listeners):
            update()

    # -- state ---------------------------------------------------------

    def _roll_day(self) -> None:
        """Reset the local counter at UTC midnight and when the API reset passed."""
        today = dt_util.utcnow().date().isoformat()
        if self.counted_day != today:
            self.counted_day = today
            self.requests_today = 0
        if self.reset is not None and dt_util.utcnow().timestamp() >= self.reset:
            self.remaining = None
            self.reset = None

    @property
    def effective_remaining(self) -> int:
        """Return the best estimate of requests left today."""
        self._roll_day()
        if self.remaining is not None:
            return self.remaining
        return max(self.limit - self.requests_today, 0)

    @property
    def used_today(self) -> int:
        """Return requests used today according to the latest information."""
        return max(self.limit - self.effective_remaining, 0)

    @property
    def reset_at(self) -> datetime | None:
        """Return when the daily allowance resets."""
        if self.reset is not None:
            return dt_util.utc_from_timestamp(self.reset)
        return (dt_util.utcnow() + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    # -- using the budget ----------------------------------------------

    async def acquire(self, *, manual: bool = False) -> None:
        """Wait for a free slot, or raise QuotaLowError.

        Scheduled polls stop at SCHEDULED_RESERVE remaining; the button and the
        search action may use the reserve down to MANUAL_FLOOR.
        """
        floor = MANUAL_FLOOR if manual else SCHEDULED_RESERVE
        async with self._lock:
            remaining = self.effective_remaining
            if remaining <= floor:
                raise QuotaLowError(remaining, floor, manual)
            blocked = self._blocked_until - time.monotonic()
            if blocked > 0:
                raise QuotaLowError(0, floor, manual)
            if self._last_monotonic is not None:
                wait = MIN_REQUEST_SPACING - (time.monotonic() - self._last_monotonic)
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_monotonic = time.monotonic()
            self.requests_today += 1
            if self.remaining is not None:
                # Count the request now; the response headers correct it.
                self.remaining = max(self.remaining - 1, 0)
            self.last_request_at = dt_util.utcnow()
        self._changed()

    def check_manual(self) -> None:
        """Raise QuotaLowError now if a manual request would be refused."""
        remaining = self.effective_remaining
        if remaining <= MANUAL_FLOOR:
            raise QuotaLowError(remaining, MANUAL_FLOOR, True)

    @callback
    def update(self, rate_limit: RateLimit) -> None:
        """Take the authoritative numbers from a response."""
        if rate_limit.limit:
            self.limit = rate_limit.limit
        if rate_limit.remaining is not None:
            self.remaining = rate_limit.remaining
        if rate_limit.reset is not None:
            self.reset = rate_limit.reset
        self._changed()

    @callback
    def rate_limited(self, rate_limit: RateLimit | None) -> None:
        """Handle a 429: stop for the rest of the day, or for a minute."""
        if rate_limit is not None:
            self.update(rate_limit)
        if rate_limit is None or rate_limit.remaining in (None, 0):
            self.remaining = 0
        else:
            self._blocked_until = time.monotonic() + _PER_MINUTE_BLOCK
        self._changed()
