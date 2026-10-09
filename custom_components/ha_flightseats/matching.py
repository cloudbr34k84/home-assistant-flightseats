"""Watch configuration and matching of API results against it."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .api import Flight, SearchParams
from .const import (
    ASSUMED_HORIZON_DAYS,
    MAX_CODES,
    CONF_CABINS,
    CONF_COOLDOWN_HOURS,
    CONF_DATE_FROM,
    CONF_DATE_TO,
    CONF_DAYS_AHEAD,
    CONF_DESTINATIONS,
    CONF_INTERVAL_HOURS,
    CONF_MAX_POINTS,
    CONF_MIN_SEATS,
    CONF_ORIGINS,
    CONF_PROGRAMS,
    CONF_REWARD_ONLY,
    DEFAULT_COOLDOWN_HOURS,
    DEFAULT_INTERVAL_HOURS,
    DEFAULT_MIN_SEATS,
    DEFAULT_PROGRAMS,
    DEFAULT_REWARD_ONLY,
    RESULT_LIMIT,
)


_IATA = re.compile(r"^[A-Z]{3}$")


def parse_codes(value: str | Iterable[str] | None) -> list[str]:
    """Split "syd, mel" or ["syd", "mel"] into unique upper-case codes."""
    if not value:
        return []
    parts = re.split(r"[,\s]+", value) if isinstance(value, str) else list(value)
    codes: list[str] = []
    for part in parts:
        code = str(part).strip().upper()
        if code and code not in codes:
            codes.append(code)
    return codes


def valid_codes(codes: list[str]) -> bool:
    """Return True for 1..30 well-formed IATA airport codes."""
    return 1 <= len(codes) <= MAX_CODES and all(_IATA.match(code) for code in codes)


@dataclass(frozen=True)
class WatchConfig:
    """A saved search (one config subentry)."""

    programs: list[str]
    origins: list[str]
    destinations: list[str]
    cabins: list[str] = field(default_factory=list)
    min_seats: int = DEFAULT_MIN_SEATS
    max_points: int | None = None
    days_ahead: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    reward_only: bool = DEFAULT_REWARD_ONLY
    interval_hours: int = DEFAULT_INTERVAL_HOURS
    cooldown_hours: int = DEFAULT_COOLDOWN_HOURS

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> WatchConfig:
        """Build a watch from stored subentry data."""
        return cls(
            programs=list(data.get(CONF_PROGRAMS) or DEFAULT_PROGRAMS),
            origins=list(data.get(CONF_ORIGINS) or []),
            destinations=list(data.get(CONF_DESTINATIONS) or []),
            cabins=list(data.get(CONF_CABINS) or []),
            min_seats=int(data.get(CONF_MIN_SEATS) or DEFAULT_MIN_SEATS),
            max_points=int(data[CONF_MAX_POINTS]) if data.get(CONF_MAX_POINTS) else None,
            days_ahead=int(data[CONF_DAYS_AHEAD]) if data.get(CONF_DAYS_AHEAD) else None,
            date_from=dt_util.parse_date(data[CONF_DATE_FROM]) if data.get(CONF_DATE_FROM) else None,
            date_to=dt_util.parse_date(data[CONF_DATE_TO]) if data.get(CONF_DATE_TO) else None,
            reward_only=bool(data.get(CONF_REWARD_ONLY, DEFAULT_REWARD_ONLY)),
            interval_hours=int(data.get(CONF_INTERVAL_HOURS) or DEFAULT_INTERVAL_HOURS),
            cooldown_hours=int(
                data[CONF_COOLDOWN_HOURS]
                if data.get(CONF_COOLDOWN_HOURS) is not None
                else DEFAULT_COOLDOWN_HOURS
            ),
        )

    def window(self, today: date) -> tuple[date | None, date | None]:
        """Return the (date_from, date_to) to send; None lets the API choose."""
        if self.days_ahead:
            return today, today + timedelta(days=self.days_ahead)
        start = self.date_from
        if start is not None and start < today:
            start = today
        return start, self.date_to

    def is_expired(self, today: date) -> bool:
        """Return True when a fixed window lies entirely in the past."""
        return not self.days_ahead and self.date_to is not None and self.date_to < today

    def search_params(self, today: date) -> SearchParams:
        """Build the API query for this watch."""
        date_from, date_to = self.window(today)
        return SearchParams(
            programs=self.programs,
            origins=self.origins,
            destinations=self.destinations,
            date_from=date_from,
            date_to=date_to,
            cabins=self.cabins,
            seats=self.min_seats,
            limit=RESULT_LIMIT,
            reward_only=self.reward_only,
        )


def count_permutations(
    origins: int,
    destinations: int,
    *,
    days_ahead: int | None,
    date_from: date | None,
    date_to: date | None,
    today: date,
) -> int:
    """Return origins x destinations x days as the API counts it."""
    if days_ahead:
        days = days_ahead + 1
    elif date_from is not None and date_to is not None:
        days = (date_to - max(date_from, today)).days + 1
    elif date_to is not None:
        days = (date_to - today).days + 1
    else:
        days = ASSUMED_HORIZON_DAYS
    return origins * destinations * max(days, 1)


def _stops(flight: Flight) -> int:
    return max(len(flight.segments) - 1, 0)


def match_dict(flight: Flight, fare: Any) -> dict[str, Any]:
    """Return a JSON-serialisable record for one flight and fare."""
    numbers = flight.flight_numbers
    key = "|".join(
        [
            flight.program,
            flight.origin,
            flight.destination,
            flight.date.isoformat(),
            "+".join(numbers),
            fare.cabin,
            "R" if fare.is_reward else "S",
        ]
    )
    return {
        "key": key,
        "program": flight.program,
        "origin": flight.origin,
        "destination": flight.destination,
        "date": flight.date.isoformat(),
        "cabin": fare.cabin,
        "seats": fare.seats,
        "points": fare.points,
        "tax": fare.tax,
        "currency": fare.currency,
        "is_reward": fare.is_reward,
        "flight_numbers": numbers,
        "departure": flight.segments[0].departure if flight.segments else None,
        "arrival": flight.segments[-1].arrival if flight.segments else None,
        "duration_minutes": flight.duration_minutes,
        "stops": _stops(flight),
        "last_seen": flight.last_seen.isoformat() if flight.last_seen else None,
    }


def extract_matches(flights: list[Flight], config: WatchConfig) -> list[dict[str, Any]]:
    """Return fares that satisfy the watch, cheapest first."""
    matches: list[dict[str, Any]] = []
    for flight in flights:
        for fare in flight.fares:
            if config.cabins and fare.cabin not in config.cabins:
                continue
            if fare.seats < config.min_seats:
                continue
            if config.reward_only and not fare.is_reward:
                continue
            if config.max_points is not None and fare.points > config.max_points:
                continue
            matches.append(match_dict(flight, fare))
    matches.sort(key=lambda m: (m["points"], m["date"], m["key"]))
    return matches


def summarise(matches: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the headline values the entities show."""
    by_program: dict[str, int] = {}
    by_cabin: dict[str, int] = {}
    seen: list[str] = []
    without_last_seen = 0
    for match in matches:
        by_program[match["program"]] = by_program.get(match["program"], 0) + 1
        by_cabin[match["cabin"]] = by_cabin.get(match["cabin"], 0) + 1
        if match["last_seen"]:
            seen.append(match["last_seen"])
        else:
            without_last_seen += 1
    best = min(matches, key=lambda m: (m["points"], m["date"]), default=None)
    earliest = min(matches, key=lambda m: (m["date"], m["points"]), default=None)
    parsed = [dt_util.parse_datetime(value) for value in seen]
    parsed = [value for value in parsed if value is not None]
    return {
        "best": best,
        "earliest": earliest,
        "by_program": by_program,
        "by_cabin": by_cabin,
        "newest_last_seen": max(parsed) if parsed else None,
        "oldest_last_seen": min(parsed) if parsed else None,
        "without_last_seen": without_last_seen,
    }
