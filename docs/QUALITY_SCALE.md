# Integration quality scale

Scope: all supplied Bronze, Silver, Gold and Platinum requirements, applied to
custom distribution. `custom_components/ha_flightseats/quality_scale.yaml` lists all
54 rules, each recorded as `done` or justified `exempt` for the current custom
integration. This is not a claim of Core acceptance or an official tier award.

This is a custom integration's implementation checklist, not an official Home
Assistant quality-scale award. The manifest deliberately has no quality-scale
claim. User documentation lives in this repository rather than home-assistant.io.

## Bronze evidence

| Rule | Evidence |
|---|---|
| `action-setup` | `__init__.async_setup` registers search independently of entries. `services._async_search` rejects an unloaded account. Tests cover no account and failed startup. |
| `appropriate-polling` | Six-hour default for cached availability, four requests/day per watch. No interval selector; legacy saved schedules are preserved. Shared quota guards, spacing, backoff and manual polling remain. |
| `brands` | **Done for custom distribution.** Eight PNG icon/logo variants are bundled under `custom_components/ha_flightseats/brand/`, using 256×256 standard and 512×512 HD images with transparency. HA 2026.3+ supports local brands; this integration requires HA 2026.8+. Absence from home-assistant/brands is not a custom-integration blocker. |
| `common-modules` | Coordinator in `coordinator.py`, shared watch entity in `entity.py`. |
| `config-flow` | Password selector, translated labels and field descriptions. Credentials in entry data, watch criteria in subentry data. An optional watch name labels a user-created saved search rather than overriding an API device name. No account options flow is needed. |
| `config-flow-test-coverage` | 100% line and branch coverage of `config_flow.py`; user, reauth, key reconfiguration, watch creation/editing, duplicate account, validation and error recovery. Defensive tests also cover values rejected by frontend selectors. CI enforces 100%. |
| `dependency-transparency` | No integration-specific external requirements; HTTP uses HA's shared aiohttp session. Source is included in this repository. |
| `docs-actions` | README search field table, defaults, example, response structure and errors. |
| `docs-conditions` | Exempt: no custom conditions. README explains standard state/numeric conditions. |
| `docs-high-level-description` | README introduces FlightSeats.io, Qantas/Velocity cached reward data and the Gold subscription requirement. |
| `docs-installation-instructions` | README prerequisites, HACS/manual installation and UI setup. |
| `docs-removal-instructions` | README entry deletion, file removal, automation cleanup, data deletion and subscription/key management. |
| `docs-triggers` | Exempt: no custom triggers. README explains standard event-entity state triggers and event types. |
| `entity-event-setup` | CoordinatorEntity handles watch subscriptions; account sensor registers its budget listener in `async_added_to_hass` with `async_on_remove`. |
| `entity-unique-id` | Watch IDs use subentry ID plus entity key; quota IDs use entry ID plus key. |
| `has-entity-name` | Shared watch entity and account sensor set `_attr_has_entity_name = True`. |
| `runtime-data` | Typed `FlightSeatsConfigEntry`/`FlightSeatsData` in `data.py`; setup assigns `entry.runtime_data`. |
| `test-before-configure` | Minimal API search before accepting a key; translated error handling and recovery tests for each credential flow. |
| `test-before-setup` | Watch first refresh raises setup/auth errors before forwarding platforms. A fresh persisted result is reused to protect quota; failures are detected at the next scheduled update. Accounts without watches probe the API and report auth, plan, quota or temporary errors. |
| `unique-config-entry` | Singleton manifest plus DOMAIN unique ID and duplicate abort; tests assert the account unique ID. |

## Branding scope correction

The earlier review incorrectly applied Core's upstream repository requirement to
this custom integration. No missing or broken bundled logo was established.
[Official custom branding guidance](https://contributors.home-assistant.io/blog/2026/02/24/brands-proxy-api/)
and the [brands README](https://github.com/home-assistant/brands/blob/master/README.md)
confirm that custom integrations ship images locally. Branding is complete for
this project's current distribution; no brands PR is required.

If FlightSeats is later submitted to Core, track an asset submission under
`core_integrations/<accepted domain>/` separately and obtain the required upstream
review. This checklist records custom implementation readiness, not an official
Core tier or a Core-rule exemption.

## Silver evidence

All ten Silver requirements have been reviewed; nine are `done` and the no-options-flow
rule is `exempt`. Bronze and Silver implementation checks are complete for this
custom integration. This does not confer an official Home Assistant quality-scale tier.

| Rule | Evidence |
|---|---|
| `action-exceptions` | Search maps input/quota errors to `ServiceValidationError`, API failures to `HomeAssistantError`. Check now surfaces unsuccessful coordinator refreshes as action errors and low quota as validation errors. Tests cover HTTP 400/401/403/429/500, invalid action input, quota floors and button recovery. |
| `config-entry-unloading` | Platforms unload through `async_unload_entry`. `entry.async_on_unload` flushes storage on successful unload and failed setup. DataUpdateCoordinator registers its own shutdown hook, which cancels polling and quota-reset timers. Tests verify no request after unload, listener cleanup, failed-platform unload, saved quota after setup failure, and storage deletion on removal. |
| `docs-configuration-parameters` | Exempt: no options flow. README explains editing watch subentries and replacing the account key. |
| `docs-installation-parameters` | README field table uses the UI labels and supplies defaults, bounds, allowed selections, API key source and date/seat constraints. |
| `entity-unavailable` | Failed API calls and quota-blocked due checks raise `UpdateFailed`; watch data entities become unavailable immediately. Successful empty results remain available. Missing result values are unknown. Check now stays available to recover; account quota entities represent the stored budget, not API connectivity, and expose `as_of`. |
| `integration-owner` | Manifest lists `@cloudbr34k84`; `.github/CODEOWNERS` assigns repository review ownership. |
| `log-when-unavailable` | Coordinator owns outage/recovery messages. Repeated failures do not produce integration-level warnings; regression test asserts one failure and one recovery log for three failed polls. |
| `parallel-updates` | Sensor, binary sensor and event platforms set 0 because they use fetched data. Button sets 1; the shared budget serializes quota acquisition and spaces API calls, including search actions. |
| `reauthentication-flow` | Setup/coordinator authentication failures and rejected search credentials start reauth. Successful reauth validates the new key and explicitly reloads the entry. Test verifies the new runtime client/header, retained watch IDs and unchanged entity registry identities. No stable account identity is available from this search API; README explains that limitation. |
| `test-coverage` | CI collects branch coverage and checks each module independently with `.github/scripts/check_coverage.py`. Every module must exceed 95% combined line/branch coverage; config flow and diagnostics must remain 100%. Missing modules or branch data fail the check. |

## Gold evidence

All 21 Gold requirements are reviewed: **18 done, 3 exempt**. The exemptions are
network discovery, discovery address updates and physical-device documentation.
This remains a repository checklist for custom distribution, not an official Core award.

| Rule | Evidence |
|---|---|
| `devices` | **done** — Account and watch service devices have stable identifiers, manufacturer/model and parent links; no invented hardware metadata. |
| `diagnostics` | **done** — Redacts keys, route/date criteria and titles; tolerates pending watch removal; no API calls. CI requires 100% diagnostics coverage. |
| `discovery` | **exempt** — FlightSeats.io is a fixed cloud API authenticated with a user-provided key; there is no discoverable network device or service announcement. |
| `discovery-update-info` | **exempt** — No device discovery or changing local network address; the cloud endpoint is fixed. |
| `docs-data-update` | **done** — README explains six-hour polling, cached upstream timestamps, startup cache reuse, retry/catchup and shared limits. |
| `docs-examples` | **done** — README includes ad-hoc search, new-availability and points-threshold examples using real entity-ID conventions. |
| `docs-known-limitations` | **done** — README lists cached data, no bookings/pagination, result/event limits, currencies/timezones and event-state limitations. |
| `docs-supported-devices` | **exempt** — No physical devices are integrated. README instead documents the supported cloud service and QF/VA programs. |
| `docs-supported-functions` | **done** — README entity tables cover all four platforms, account/watch grouping, disabled entities and the search action. |
| `docs-troubleshooting` | **done** — README covers credentials, plan access, quota, connectivity, expired windows, result caps, disabled entities and diagnostics. |
| `docs-use-cases` | **done** — README describes family-seat watches, points targets and managing shared quota. |
| `dynamic-devices` | **done** — Reconciles new/deleted watches in place; platforms subscribe for additions; existing searches keep running. Edits reload for new criteria. |
| `entity-category` | **done** — Account budget sensors and watch data freshness are diagnostic; availability, fares, counts, events and Check now are primary functionality. |
| `entity-device-class` | **done** — Taxes use monetary, freshness/reset use timestamp, earliest departure uses date. No fitting class exists for reward points or seat availability. |
| `entity-disabled-by-default` | **done** — Earliest date and daily request limit are disabled initially; existing user choices remain intact. |
| `entity-translations` | **done** — All entity labels use strings.json translation keys and has_entity_name; user-defined watch names are retained. |
| `exception-translations` | **done** — All public HomeAssistantError subclasses, including setup and coordinator failures, use translated keys. |
| `icon-translations` | **done** — All custom entity/action icons are declared in icons.json, with no Python icon attributes. |
| `reconfiguration-flow` | **done** — Account key and watch criteria can be reconfigured, with validation/error recovery and stable entity identities. |
| `repair-issues` | **done** — Plan-access failures from startup, polls and search create an account-scoped repair. Success/removal clears it; unload preserves it. Older supported HA versions use explicit removal cleanup. |
| `stale-devices` | **done** — Deleting a watch removes its subentry devices/entities and cache and stops polling. The removal hook permits orphan device deletion while protecting active configurations. |

The lifecycle tests add and remove watches without replacing the existing runtime,
client or coordinator; check recovery of a newly added unavailable watch; and
remove a watch while its first API request is still in flight. Device registry
tests verify parent links, diagnostics categories, default-disabled entities and
orphan removal guards. Credential-change tests retained from Silver verify that
reauthentication uses the new client without changing registry identities.

Repair tests cover startup without watches, scheduled polls, ad-hoc search,
unload/reload, confirmed recovery, and cleanup on older supported HA versions.
The HA 2026.8 [issue registry API](https://github.com/home-assistant/core/blob/2026.8.0/homeassistant/helpers/issue_registry.py)
does not accept `config_entry_id`; the helper supplies it only when supported.
The minimum remains HA 2026.8; the full suite targets HA 2026.11, not every
supported release.

All Home Assistant exception strings were checked for translation keys. English
translations match strings.json; no additional language is claimed. The icon and
entity-name mechanisms already existed and were retained.

## Platinum evidence

All three Platinum requirements are **done** for this custom repository.

| Rule | Evidence |
|---|---|
| `async-dependency` | `FlightSeatsClient` awaits aiohttp requests inside `asyncio.timeout`. Quota spacing awaits `asyncio.sleep`; persistent data uses HA's asynchronous `Store`. No blocking network dependency or executor-wrapped HTTP client is used. The bundled client is checked together with the integration. |
| `inject-websession` | Setup and key validation supply `async_get_clientsession(hass)` to the client constructor. A lifecycle test verifies that the runtime borrows that exact pool, unload leaves it open, and it remains usable afterward. |
| `strict-typing` | `pyproject.toml` enables mypy strict mode for all 19 production modules; pinned mypy runs in CI. The package ships `py.typed`, and aiohttp supplies its own typing marker. Entry handlers and flow helpers use `FlightSeatsConfigEntry`; raw/config dictionaries are explicitly annotated at dynamic boundaries. No `type: ignore`, `ignore_errors`, `ignore_missing_imports`, skipped imports or disabled error codes are used for the integration. |

The initial strict run found 16 errors. Fixes narrowed parsed timestamps to actual
datetimes, typed watch inputs as mappings and fare inputs as `Fare`, made the
normal polling interval unambiguously non-optional, and described optional repair
kwargs with a TypedDict. Schema imports are typed against current probatio while
retaining the supported legacy runtime import for HA compatibility.

Core's central `.strict-typing` registration and generated mypy config apply to
an actual Core submission. This repository enforces the equivalent local check
through its own `pyproject.toml` and CI, without creating a nonfunctional copy of
Core's marker file. The [Core hassfest quality-scale validator](https://github.com/home-assistant/core/blob/dev/script/hassfest/quality_scale.py)
explicitly limits its quality-scale validation to Core integrations. The manifest
continues to make no official tier claim.

## Verification

Use Python 3.14 and `requirements_dev.txt`:

```sh
python -m mypy
python -m coverage run --branch -m pytest tests -q
python -m coverage report --show-missing
python -m coverage json -o test-results/coverage.json
python .github/scripts/check_coverage.py test-results/coverage.json
ruff check custom_components tests .github/scripts/check_coverage.py
ruff format --check custom_components tests .github/scripts/check_coverage.py
```

Verified locally: **154 tests passed**, with five dependency deprecation warnings.
All **19 modules exceed 95% combined line/branch coverage**; the lowest is
`coordinator.py` at **95.97%**. Config flow and diagnostics remain at **100%**. Strict mypy reports
**no issues in 19 source files**. A negative type-check probe confirms that an
invalid API search argument is rejected instead of being treated as `Any`. Ruff lint/format,
whitespace, translation consistency and all 54 checklist entries passed checks.
The coverage gate also correctly rejects an exactly-95% module, a missing module,
or incomplete diagnostics coverage. README YAML/template syntax and public
exception translation keys were checked.

All API traffic in tests is mocked. These checks do not deploy or reload the live
integration or submit it to Core. Releases use the repository publication workflow,
which requires GitHub Tests, HACS and Hassfest checks; local tests do not replace
those checks.
