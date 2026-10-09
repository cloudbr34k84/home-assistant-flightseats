"""Tests for watch matching and parsing."""
from datetime import date

from custom_components.ha_flightseats.api import Flight
from custom_components.ha_flightseats.matching import (
    WatchConfig,
    count_permutations,
    extract_matches,
    parse_codes,
    summarise,
    valid_codes,
)

from .conftest import flight


def _flights(*raw):
    return [Flight.from_dict(item) for item in raw]


def _config(**overrides):
    base = {
        "programs": ["QF"],
        "origins": ["SYD"],
        "destinations": ["LAX"],
        "cabins": ["BUS"],
        "min_seats": 2,
    }
    return WatchConfig.from_data({**base, **overrides})


def test_parse_and_validate_codes():
    assert parse_codes("syd, mel  syd") == ["SYD", "MEL"]
    assert parse_codes(["bne"]) == ["BNE"]
    assert parse_codes(None) == []
    assert valid_codes(["SYD", "MEL"])
    assert not valid_codes([])
    assert not valid_codes(["SYDX"])
    assert not valid_codes([f"A{c}{d}" for c in "ABCDEFGHIJ" for d in "ABCD"])


def test_extract_matches_filters_and_sorts():
    flights = _flights(
        flight(points=200000),
        flight(points=150000, date="2027-03-20"),
        flight(seats=1, points=100000),  # too few seats
        flight(cabin="ECO", points=50000),  # wrong cabin
        flight(is_reward=False, points=90000),  # not a reward fare
    )
    matches = extract_matches(flights, _config())
    assert [m["points"] for m in matches] == [150000, 200000]
    assert matches[0]["flight_numbers"] == ["QF11"]


def test_max_points_filter():
    flights = _flights(flight(points=200000), flight(points=150000, date="2027-03-20"))
    matches = extract_matches(flights, _config(max_points=160000))
    assert [m["points"] for m in matches] == [150000]


def test_partner_carrier_and_stops():
    item = flight(numbers=(("EK", 435), ("EK", 215)))
    match = extract_matches(_flights(item), _config())[0]
    assert match["flight_numbers"] == ["EK435", "EK215"]
    assert match["stops"] == 1
    assert match["departure"].endswith("T10:30")


def test_summarise():
    flights = _flights(
        flight(points=200000, date="2027-03-10"),
        flight(points=150000, date="2027-03-20", last_seen=None),
        flight(points=170000, date="2027-03-12", cabin="BUS", last_seen="2027-02-03T00:00:00Z"),
    )
    summary = summarise(extract_matches(flights, _config()))
    assert summary["best"]["points"] == 150000
    assert summary["earliest"]["date"] == "2027-03-10"
    assert summary["by_cabin"] == {"BUS": 3}
    assert summary["without_last_seen"] == 1
    assert summary["newest_last_seen"].isoformat().startswith("2027-02-03")


def test_summarise_empty():
    summary = summarise([])
    assert summary["best"] is None
    assert summary["newest_last_seen"] is None


def test_window_and_expiry():
    today = date(2027, 1, 10)
    rolling = _config(days_ahead=30)
    assert rolling.window(today) == (today, date(2027, 2, 9))
    fixed = _config(date_from="2026-12-01", date_to="2027-03-01")
    assert fixed.window(today) == (today, date(2027, 3, 1))
    assert not fixed.is_expired(today)
    assert _config(date_to="2027-01-01").is_expired(today)
    assert not _config(days_ahead=10, date_to="2027-01-01").is_expired(today)
    assert _config().window(today) == (None, None)


def test_count_permutations():
    today = date(2027, 1, 1)
    assert (
        count_permutations(2, 3, days_ahead=9, date_from=None, date_to=None, today=today)
        == 60
    )
    assert (
        count_permutations(
            1, 1, days_ahead=None, date_from=date(2027, 1, 1), date_to=date(2027, 1, 31), today=today
        )
        == 31
    )
    assert count_permutations(1, 1, days_ahead=None, date_from=None, date_to=None, today=today) == 365
