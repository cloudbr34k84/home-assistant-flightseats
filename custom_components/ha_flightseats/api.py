"""Async client for the FlightSeats.io reward-seat search API."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import aiohttp
from homeassistant.util import dt as dt_util

from .const import API_BASE, API_SEARCH_PATH, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class FlightSeatsError(Exception):
    """Base error for the FlightSeats.io client."""


class FlightSeatsConnectionError(FlightSeatsError):
    """The API could not be reached, timed out or returned a server error."""


class FlightSeatsAuthError(FlightSeatsError):
    """The API key is missing, invalid or revoked (HTTP 401)."""


class FlightSeatsForbiddenError(FlightSeatsError):
    """The account is not on an active Gold plan (HTTP 403)."""


class FlightSeatsBadRequestError(FlightSeatsError):
    """The request was rejected (HTTP 400)."""


class FlightSeatsRateLimitError(FlightSeatsError):
    """A daily or per-minute rate limit was hit (HTTP 429)."""

    def __init__(self, message: str, rate_limit: RateLimit | None = None) -> None:
        """Keep the rate-limit headers that came with the 429."""
        super().__init__(message)
        self.rate_limit = rate_limit


@dataclass(frozen=True)
class RateLimit:
    """Values from the X-RateLimit-* response headers."""

    limit: int | None = None
    remaining: int | None = None
    reset: int | None = None  # UTC epoch seconds

    @classmethod
    def from_headers(cls, headers: Any) -> RateLimit:
        """Parse the rate-limit headers, tolerating missing or odd values."""

        def _int(name: str) -> int | None:
            try:
                return int(headers.get(name))
            except TypeError, ValueError:
                return None

        return cls(
            limit=_int("X-RateLimit-Limit"),
            remaining=_int("X-RateLimit-Remaining"),
            reset=_int("X-RateLimit-Reset"),
        )


@dataclass(frozen=True)
class Segment:
    """One leg of a flight."""

    origin: str
    destination: str
    marketing_carrier: str
    operating_carrier: str
    flight_number: str
    departure: str
    arrival: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Segment:
        """Build a segment from API data. Times stay as zoneless strings."""
        marketing = str(data.get("marketingCarrier") or "")
        return cls(
            origin=str(data.get("origin") or ""),
            destination=str(data.get("destination") or ""),
            marketing_carrier=marketing,
            operating_carrier=str(data.get("operatingCarrier") or marketing),
            flight_number=str(data.get("flightNumber") or ""),
            departure=str(data.get("departure") or ""),
            arrival=str(data.get("arrival") or ""),
        )

    @property
    def label(self) -> str:
        """Return e.g. QF11."""
        return f"{self.marketing_carrier}{self.flight_number}"


@dataclass(frozen=True)
class Fare:
    """One fare on a flight."""

    cabin: str
    seats: int
    points: int
    tax: float
    currency: str
    is_reward: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Fare | None:
        """Build a fare, or None when the essential fields are unusable."""
        try:
            cabin = data["cabin"]
            seats_raw = float(data.get("seats") or 0)
            points_raw = float(data["points"])
            tax = float(data.get("tax") or 0)
            reward = data.get("isReward", True)
            if (
                not isinstance(cabin, str)
                or not cabin
                or not isinstance(reward, bool)
                or not all(
                    math.isfinite(value) and value >= 0
                    for value in (seats_raw, points_raw, tax)
                )
                or not seats_raw.is_integer()
                or not points_raw.is_integer()
            ):
                return None
            return cls(
                cabin=cabin,
                seats=int(seats_raw),
                points=int(points_raw),
                tax=tax,
                currency=str(data.get("currency") or ""),
                is_reward=reward,
            )
        except KeyError, TypeError, ValueError, OverflowError:
            return None


@dataclass(frozen=True)
class Flight:
    """A cached flight with its fares."""

    program: str
    origin: str
    destination: str
    date: date
    last_seen: datetime | None
    duration_minutes: int | None
    segments: tuple[Segment, ...] = field(default_factory=tuple)
    fares: tuple[Fare, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Flight | None:
        """Build a flight, or None when it cannot be understood."""
        if not isinstance(data, dict):
            return None
        flight_date = dt_util.parse_date(str(data.get("date") or ""))
        if flight_date is None:
            return None
        last_seen = None
        if data.get("lastSeen"):
            last_seen = dt_util.parse_datetime(str(data["lastSeen"]))
            if last_seen is not None and last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=dt_util.UTC)
        if any(
            data.get(key) is not None and not isinstance(data[key], list)
            for key in ("fares", "segments")
        ):
            return None
        duration = data.get("durationMinutes")
        fares = tuple(
            fare
            for raw in data.get("fares") or []
            if isinstance(raw, dict) and (fare := Fare.from_dict(raw)) is not None
        )
        segments = tuple(
            Segment.from_dict(raw)
            for raw in data.get("segments") or []
            if isinstance(raw, dict)
        )
        return cls(
            program=str(data.get("program") or ""),
            origin=str(data.get("origin") or ""),
            destination=str(data.get("destination") or ""),
            date=flight_date,
            last_seen=last_seen,
            duration_minutes=duration if isinstance(duration, int) else None,
            segments=segments,
            fares=fares,
        )

    @property
    def flight_numbers(self) -> list[str]:
        """Return the flight numbers of every segment, e.g. ['QF11', 'QF93']."""
        return [segment.label for segment in self.segments if segment.flight_number]


@dataclass(frozen=True)
class SearchParams:
    """Query parameters for GET /api/v1/search."""

    programs: list[str]
    origins: list[str]
    destinations: list[str]
    date_from: date | None = None
    date_to: date | None = None
    cabins: list[str] = field(default_factory=list)
    seats: int = 1
    limit: int = 500
    reward_only: bool = True

    def to_query(self) -> list[tuple[str, str]]:
        """Return the query string pairs."""
        query = [
            ("programs", ",".join(self.programs)),
            ("origins", ",".join(self.origins)),
            ("destinations", ",".join(self.destinations)),
            ("seats", str(self.seats)),
            ("limit", str(self.limit)),
            ("reward_only", "true" if self.reward_only else "false"),
        ]
        if self.date_from:
            query.append(("date_from", self.date_from.isoformat()))
        if self.date_to:
            query.append(("date_to", self.date_to.isoformat()))
        if self.cabins:
            query.append(("cabins", ",".join(self.cabins)))
        return query


@dataclass(frozen=True)
class SearchResponse:
    """Parsed search response."""

    flights: list[Flight]
    raw_count: int
    rate_limit: RateLimit


class FlightSeatsClient:
    """Thin wrapper around the search endpoint."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        """Initialise with a shared aiohttp session and the bearer key."""
        self._session = session
        self._headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    async def async_search(self, params: SearchParams) -> SearchResponse:
        """Run a search and return flights plus the rate-limit state."""
        url = f"{API_BASE}{API_SEARCH_PATH}"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(
                    url, params=params.to_query(), headers=self._headers
                ) as response:
                    rate_limit = RateLimit.from_headers(response.headers)
                    if response.status == 200:
                        body = await response.json()
                    else:
                        await self._raise_for_status(response, rate_limit)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise FlightSeatsConnectionError("Cannot reach FlightSeats.io") from err

        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            raise FlightSeatsConnectionError("Unexpected response from FlightSeats.io")
        flights = [
            flight for raw in results if (flight := Flight.from_dict(raw)) is not None
        ]
        discarded = len(results) - len(flights)
        if discarded:
            _LOGGER.debug("Ignored %d malformed flight records", discarded)
        return SearchResponse(
            flights=flights, raw_count=len(results), rate_limit=rate_limit
        )

    @staticmethod
    async def _raise_for_status(
        response: aiohttp.ClientResponse, rate_limit: RateLimit
    ) -> None:
        """Map non-200 responses to client exceptions."""
        message = f"HTTP {response.status}"
        if response.status == 400:
            raise FlightSeatsBadRequestError(message)
        if response.status == 401:
            raise FlightSeatsAuthError(message)
        if response.status == 403:
            raise FlightSeatsForbiddenError(message)
        if response.status == 429:
            raise FlightSeatsRateLimitError(message, rate_limit)
        if response.status >= 500:
            raise FlightSeatsConnectionError(f"FlightSeats.io server error: {message}")
        raise FlightSeatsError(f"Unexpected response from FlightSeats.io: {message}")
