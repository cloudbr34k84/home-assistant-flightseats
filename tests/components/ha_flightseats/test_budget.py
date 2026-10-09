"""Tests for the shared request budget."""
import pytest

from custom_components.ha_flightseats.api import RateLimit
from custom_components.ha_flightseats.budget import QuotaBudget, QuotaLowError
from custom_components.ha_flightseats.const import MANUAL_FLOOR, SCHEDULED_RESERVE


async def test_acquire_counts_requests():
    budget = QuotaBudget()
    await budget.acquire()
    assert budget.requests_today == 1
    assert budget.effective_remaining == 199


async def test_headers_are_authoritative():
    budget = QuotaBudget()
    await budget.acquire()
    budget.update(RateLimit(limit=200, remaining=140, reset=4_102_444_800))
    assert budget.effective_remaining == 140
    assert budget.used_today == 60


async def test_scheduled_stops_at_reserve_manual_continues():
    budget = QuotaBudget()
    budget.update(RateLimit(limit=200, remaining=SCHEDULED_RESERVE, reset=4_102_444_800))
    with pytest.raises(QuotaLowError):
        await budget.acquire()
    await budget.acquire(manual=True)  # reserve is for manual use
    budget.update(RateLimit(limit=200, remaining=MANUAL_FLOOR, reset=4_102_444_800))
    with pytest.raises(QuotaLowError):
        await budget.acquire(manual=True)
    with pytest.raises(QuotaLowError):
        budget.check_manual()


async def test_daily_429_blocks_until_reset():
    budget = QuotaBudget()
    budget.rate_limited(RateLimit(limit=200, remaining=0, reset=4_102_444_800))
    with pytest.raises(QuotaLowError):
        await budget.acquire(manual=True)


async def test_per_minute_429_blocks_briefly():
    budget = QuotaBudget()
    budget.rate_limited(RateLimit(limit=200, remaining=120, reset=4_102_444_800))
    with pytest.raises(QuotaLowError):
        await budget.acquire(manual=True)


async def test_reset_time_in_past_clears_remaining():
    budget = QuotaBudget({"limit": 200, "remaining": 0, "reset": 1_000_000_000})
    await budget.acquire()  # reset long passed, so the day has started over
    assert budget.effective_remaining > SCHEDULED_RESERVE


async def test_state_round_trip_and_listener():
    budget = QuotaBudget()
    calls = []
    remove = budget.async_add_listener(lambda: calls.append(1))
    budget.update(RateLimit(limit=200, remaining=150, reset=4_102_444_800))
    assert calls == [1]
    remove()
    budget.update(RateLimit(limit=200, remaining=149, reset=4_102_444_800))
    assert calls == [1]
    restored = QuotaBudget(budget.as_dict())
    assert restored.remaining == 149


async def test_remaining_unknown_until_api_confirms():
    budget = QuotaBudget()
    assert budget.remaining_if_known is None  # a shared count must not be guessed
    budget.update(RateLimit(limit=200, remaining=185, reset=4_102_444_800))
    assert budget.remaining_if_known == 185
    assert budget.as_of is not None
    assert QuotaBudget(budget.as_dict()).remaining_if_known == 185


async def test_new_day_assumes_full_allowance_until_next_response():
    budget = QuotaBudget({"limit": 200, "remaining": 12, "reset": 1_000_000_000, "as_of": "2001-01-01T00:00:00+00:00"})
    assert budget.remaining_if_known == 200
