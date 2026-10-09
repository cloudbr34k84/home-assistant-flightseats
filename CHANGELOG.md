# Changelog

## 0.1.2

- Watch entity IDs now end with `_flightseats` (for example `sensor.syd_hkg_bus_best_points_flightseats`), so they are easy to find in searches and pickers. Friendly names are unchanged.
- Watch entities created by 0.1.0 and 0.1.1 are renamed automatically on the first start; their history is kept. Anything that refers to the old IDs (dashboards, automations) needs updating.

## 0.1.1

- Add watch form: Origins and Destinations are now a searchable multi-select of about 240 common airports (any other 3-letter code can still be typed). Filters, Date window and Schedule and alerts are grouped into sections, with the last two collapsed.
- `Requests remaining today` is `unknown` until the API has reported the shared count, and has an `as_of` attribute, instead of showing a full allowance that other projects using the same key may already have spent.

## 0.1.0

First release.

- Config flow with API key check, re-authentication and reconfigure.
- Watches as config subentries (programs, airports, date window, cabins, minimum seats, maximum points, reward-only, interval, alert cooldown).
- Per watch: Seats available, Best points, Taxes for best fare, Matching flights, Data freshness, Earliest date (disabled by default), Availability event, Check now button.
- Account diagnostics: Requests remaining today, Quota resets at, Daily request limit (disabled by default).
- Shared quota budget: spacing, reserve, header-driven counts, saved across restarts, no requests on restart while saved data is fresh.
- Change detection with false-event protection: baseline on first poll, gone only after two complete polls, cooldown, coalesced events.
- `ha_flightseats.search` action (response only).
- Diagnostics with the key redacted; repair issue when the account is not Gold.

Planned: 0.2 availability log and history sensors, 0.3 long-term statistics and a card or calendar.
