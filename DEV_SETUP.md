# Local Development Setup

The repository uses the standard HACS layout: source lives in
`custom_components/ha_flightseats/`, with tests in `tests/` and the saved API
specification in `docs/openapi.json`.

Develop against a separate Home Assistant instance. Copy the integration folder
into that instance's `custom_components/` directory and restart it. The live
`/homeassistant/custom_components/ha_flightseats` folder is currently a separate
copy; editing this repository does not automatically update it. Do not replace
it with a symlink unless you intend live reloads to execute repository edits.

## After making changes

| Change | What to do |
|---|---|
| Python logic | Reload the integration entry (or restart HA) |
| `manifest.json`, new files, `strings.json`, `icons.json`, `services.yaml` | Full HA restart |

Watches reuse fresh saved data on reload, so those checks cost no API requests. An account without watches uses one request during setup to validate access.

## Tests

Tests never call the live API (200 requests a day, shared). Use a virtualenv:

```bash
python3.14 -m venv .venv && . .venv/bin/activate
pip install -r requirements_dev.txt
python -m mypy
python -m coverage run --branch -m pytest tests -q
python -m coverage report --show-missing
python -m coverage json -o test-results/coverage.json
python .github/scripts/check_coverage.py test-results/coverage.json
```

## API key for manual checks

Put it in `.env` (git-ignored) as `FLIGHTSEATS_API_KEY=...`. Never commit it, and keep live calls to a minimum.

Tests require Python 3.14.2+ and pin Home Assistant 2026.11.0. Run `ruff check custom_components tests` and `ruff format --check custom_components tests` before submitting changes. Use a separate development HA instance.

## Strict typing

`python -m mypy` reads `pyproject.toml` and checks every integration source module
in strict mode. Mypy is pinned in `requirements_dev.txt` and runs in CI. Imported
packages remain visible to the checker; `follow_imports = "silent"` prevents
unrelated dependency diagnostics from becoming this repository's errors. There
are no integration-wide ignores, skipped imports or disabled mypy error codes.
Tests are checked at runtime by pytest; they are not part of the production-code
mypy target.

The bundled API client is included in the checked source and the integration
ships `py.typed`. Runtime validation retains the legacy voluptuous import for
supported older HA releases; type checking uses the probatio API used by the
pinned HA 2026.11 environment. HA's compatibility layer bridges that runtime API.
The full regression suite covers config and action schemas under the pinned HA
release; this does not claim runtime tests on every supported HA version.

Do not add a decorative local `.strict-typing` file: that file belongs to Core's
hassfest-generated mypy setup. This custom repository enforces strict checking
through its own actual configuration and workflow.
