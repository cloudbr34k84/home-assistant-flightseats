# Changelog

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
