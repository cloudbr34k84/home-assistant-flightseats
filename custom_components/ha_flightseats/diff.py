"""Change detection between polls, with protection against false events.

Rules:
* The first successful poll only sets a baseline; it never raises events.
* A match is reported as gone only after it is missing from several
  consecutive *complete* polls. A truncated response (API result limit hit)
  proves nothing about what is absent.
* A match that reappears within the cooldown does not raise a second
  new_availability event.
* Events are coalesced: at most one event per type per poll.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    ABSENT_POLLS_BEFORE_GONE,
    EVENT_AVAILABILITY_GONE,
    EVENT_NEW_AVAILABILITY,
    EVENT_PRICE_DROP,
    MAX_EVENT_MATCHES,
)

_LAST_FIRED_KEEP = timedelta(days=7)


def empty_state() -> dict[str, Any]:
    """Return the state before any poll has happened."""
    return {"baselined": False, "known": {}, "last_fired": {}}


def _event(
    event_type: str, matches: list[dict[str, Any]], now: datetime
) -> dict[str, Any]:
    """Build one coalesced event payload from its matches."""
    ordered = sorted(matches, key=lambda m: (m["points"], m["date"]))
    best = ordered[0]
    data = {
        "count": len(ordered),
        "program": best["program"],
        "origin": best["origin"],
        "destination": best["destination"],
        "date": best["date"],
        "cabin": best["cabin"],
        "seats": best["seats"],
        "points": best["points"],
        "tax": best["tax"],
        "currency": best["currency"],
        "flight_numbers": best["flight_numbers"],
        "last_seen": best["last_seen"],
        "detected_at": now.isoformat(),
        "matches": ordered[:MAX_EVENT_MATCHES],
    }
    if "previous_points" in best:
        data["previous_points"] = best["previous_points"]
    return {"event_type": event_type, "data": data}


def diff_matches(
    state: dict[str, Any],
    matches: list[dict[str, Any]],
    *,
    complete: bool,
    cooldown: timedelta,
    now: datetime | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (new_state, events) for a successful poll."""
    now = now or dt_util.utcnow()
    new_state = deepcopy(state)
    known: dict[str, Any] = new_state["known"]
    last_fired: dict[str, str] = new_state["last_fired"]
    current = {match["key"]: match for match in matches}

    if not new_state["baselined"]:
        new_state["baselined"] = True
        new_state["known"] = {
            key: {"match": match, "absent": 0} for key, match in current.items()
        }
        return new_state, []

    opened: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    gone: list[dict[str, Any]] = []

    for key, match in current.items():
        entry = known.get(key)
        if entry is None:
            known[key] = {"match": match, "absent": 0}
            fired = dt_util.parse_datetime(last_fired.get(key, ""))
            if fired is None or now - fired >= cooldown:
                opened.append(match)
                last_fired[key] = now.isoformat()
            continue
        previous_points = entry["match"]["points"]
        if match["points"] < previous_points:
            dropped.append({**match, "previous_points": previous_points})
        entry["match"] = match
        entry["absent"] = 0

    if complete:
        for key in list(known):
            if key in current:
                continue
            known[key]["absent"] += 1
            if known[key]["absent"] >= ABSENT_POLLS_BEFORE_GONE:
                gone.append(known.pop(key)["match"])

    for key, stamp in list(last_fired.items()):
        fired = dt_util.parse_datetime(stamp)
        if fired is None or now - fired > max(cooldown * 2, _LAST_FIRED_KEEP):
            del last_fired[key]

    events = []
    if opened:
        events.append(_event(EVENT_NEW_AVAILABILITY, opened, now))
    if dropped:
        events.append(_event(EVENT_PRICE_DROP, dropped, now))
    if gone:
        events.append(_event(EVENT_AVAILABILITY_GONE, gone, now))
    return new_state, events
