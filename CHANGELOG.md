# Changelog

## 0.2.0 (2026-11-10)

### Changes

- Add watches without reloading the account or interrupting existing watches. Deleting a watch removes its devices, entities and saved results and stops its polling.
- Report failed checks immediately as unavailable watch data. Check now and ad-hoc search report actionable errors, and connection failures retry after 30 minutes.
- Validate API access during startup, preserve quota counters after failed setup, and clean up polling, listeners and in-flight watch additions on unload.
- Explicitly reload after key replacement or reauthentication while preserving watch/device/entity identities. Rejected ad-hoc search credentials also start reauthentication.
- Translate public errors, scope Gold-plan repairs to the account, clear repairs after confirmed recovery/removal, and allow orphan device cleanup.
- Classify watch freshness as diagnostic and improve diagnostics privacy and behavior during watch deletion.
- Complete the Bronze-through-Platinum development checklist for custom distribution, with evidence and justified exemptions. Bundled branding meets current custom-integration guidance; this is not an official Home Assistant tier award.
- Expand setup, action, removal, data-update, troubleshooting and limitations documentation, including notification examples.
- Enforce strict typing and 100% line/branch coverage for every production module in CI; include the typed-package marker.
- Run the complete test suite against both the Home Assistant 2026.8.0 minimum and the 2026.11.0 development target.
- Add the repository banner to the README and refresh release-validation documentation.

### Upgrade notes

- Requires Home Assistant **2026.8.0 or newer**. Upgrading from v0.1.3 preserves watches, entity IDs and saved polling intervals. Upgrades from releases before v0.1.2 still apply the previously documented `_flightseats` entity-ID suffix migration.
- New watches use a six-hour polling interval; the watch form no longer offers an interval field. Use Home Assistant polling controls and Check now for a custom schedule, subject to quota limits.
- A failed or quota-blocked due check now makes watch data unavailable immediately, replacing the previous grace period. Check now remains available for recovery.
- Reconfigure an expired fixed-date watch to resume polling. No new API key is needed unless the current key is rejected.
- Availability history/archive features remain planned and are not included in this release.

### Validation

- **161 mocked tests pass** against Home Assistant 2026.8.0 and 2026.11.0 on Python 3.14.
- Strict mypy passes for all **19 production modules**. Every module has **100% line and branch coverage**.
- Ruff lint/format and release metadata checks pass. No live FlightSeats API requests are needed for these checks.

## 0.1.3 (2026-11-07)

- Add repository issue/PR templates, contribution guide and validated automatic tag releases.
- Consolidate HACS and Hassfest validation; improve HACS installation and release instructions.
- Correct minimum Home Assistant version to 2026.8 for existing device APIs.
- Harden API fare parsing, error privacy, watch input validation and search dates.
- Fix expired watch cache reuse and quota recovery without reset headers.
- Redact travel plans in diagnostics and tolerate damaged storage containers.
- Update tests to Home Assistant 2026.11, add regression coverage and CI linting.

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

Future releases may add availability history, long-term statistics, and a card or calendar.
