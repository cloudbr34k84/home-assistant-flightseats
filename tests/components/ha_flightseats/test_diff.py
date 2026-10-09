"""Tests for change detection and false-event protection."""
from datetime import datetime, timedelta, timezone

from custom_components.ha_flightseats.api import Flight
from custom_components.ha_flightseats.diff import diff_matches, empty_state
from custom_components.ha_flightseats.matching import WatchConfig, extract_matches

from .conftest import flight

CONFIG = WatchConfig.from_data(
    {"programs": ["QF"], "origins": ["SYD"], "destinations": ["LAX"], "min_seats": 1}
)
COOLDOWN = timedelta(hours=12)
T0 = datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)


def _m(*raw):
    return extract_matches([Flight.from_dict(item) for item in raw], CONFIG)


def _types(events):
    return [event["event_type"] for event in events]


def test_first_poll_is_baseline_only():
    state, events = diff_matches(
        empty_state(), _m(flight()), complete=True, cooldown=COOLDOWN, now=T0
    )
    assert events == []
    assert state["baselined"]
    assert len(state["known"]) == 1


def test_new_availability_after_baseline():
    state, _ = diff_matches(empty_state(), _m(flight()), complete=True, cooldown=COOLDOWN, now=T0)
    both = _m(flight(), flight(date="2027-03-20", points=120000))
    state, events = diff_matches(state, both, complete=True, cooldown=COOLDOWN, now=T0)
    assert _types(events) == ["new_availability"]
    data = events[0]["data"]
    assert data["count"] == 1
    assert data["points"] == 120000
    assert data["date"] == "2027-03-20"
    assert data["matches"][0]["date"] == "2027-03-20"


def test_events_are_coalesced_per_poll():
    state, _ = diff_matches(empty_state(), _m(), complete=True, cooldown=COOLDOWN, now=T0)
    many = _m(*(flight(date=f"2027-03-{day:02d}", points=100000 + day) for day in range(1, 11)))
    _, events = diff_matches(state, many, complete=True, cooldown=COOLDOWN, now=T0)
    assert _types(events) == ["new_availability"]
    assert events[0]["data"]["count"] == 10
    assert len(events[0]["data"]["matches"]) == 5


def test_gone_needs_two_complete_polls():
    state, _ = diff_matches(empty_state(), _m(flight()), complete=True, cooldown=COOLDOWN, now=T0)
    state, events = diff_matches(state, [], complete=True, cooldown=COOLDOWN, now=T0)
    assert events == []
    state, events = diff_matches(state, [], complete=True, cooldown=COOLDOWN, now=T0)
    assert _types(events) == ["availability_gone"]
    assert state["known"] == {}


def test_reappearing_resets_absence():
    state, _ = diff_matches(empty_state(), _m(flight()), complete=True, cooldown=COOLDOWN, now=T0)
    state, _ = diff_matches(state, [], complete=True, cooldown=COOLDOWN, now=T0)
    state, events = diff_matches(state, _m(flight()), complete=True, cooldown=COOLDOWN, now=T0)
    assert events == []
    state, events = diff_matches(state, [], complete=True, cooldown=COOLDOWN, now=T0)
    assert events == []  # absence counter restarted


def test_truncated_poll_never_reports_gone():
    state, _ = diff_matches(empty_state(), _m(flight()), complete=True, cooldown=COOLDOWN, now=T0)
    for _ in range(5):
        state, events = diff_matches(state, [], complete=False, cooldown=COOLDOWN, now=T0)
        assert events == []
    assert len(state["known"]) == 1


def test_truncated_poll_still_reports_new():
    state, _ = diff_matches(empty_state(), _m(), complete=True, cooldown=COOLDOWN, now=T0)
    _, events = diff_matches(state, _m(flight()), complete=False, cooldown=COOLDOWN, now=T0)
    assert _types(events) == ["new_availability"]


def test_cooldown_suppresses_flapping():
    state, _ = diff_matches(empty_state(), _m(), complete=True, cooldown=COOLDOWN, now=T0)
    state, events = diff_matches(state, _m(flight()), complete=True, cooldown=COOLDOWN, now=T0)
    assert _types(events) == ["new_availability"]
    for step in (1, 2):  # gone after two empty polls
        state, gone = diff_matches(state, [], complete=True, cooldown=COOLDOWN, now=T0 + timedelta(hours=step))
    assert _types(gone) == ["availability_gone"]
    state, events = diff_matches(
        state, _m(flight()), complete=True, cooldown=COOLDOWN, now=T0 + timedelta(hours=3)
    )
    assert events == []  # back inside the cooldown
    state2, _ = diff_matches(state, [], complete=True, cooldown=COOLDOWN, now=T0 + timedelta(hours=4))
    state2, _ = diff_matches(state2, [], complete=True, cooldown=COOLDOWN, now=T0 + timedelta(hours=5))
    _, events = diff_matches(
        state2, _m(flight()), complete=True, cooldown=COOLDOWN, now=T0 + timedelta(hours=20)
    )
    assert _types(events) == ["new_availability"]  # cooldown over


def test_price_drop():
    state, _ = diff_matches(empty_state(), _m(flight(points=200000)), complete=True, cooldown=COOLDOWN, now=T0)
    _, events = diff_matches(state, _m(flight(points=180000)), complete=True, cooldown=COOLDOWN, now=T0)
    assert _types(events) == ["price_drop"]
    assert events[0]["data"]["previous_points"] == 200000
    _, events = diff_matches(state, _m(flight(points=210000)), complete=True, cooldown=COOLDOWN, now=T0)
    assert events == []  # increases are not events
