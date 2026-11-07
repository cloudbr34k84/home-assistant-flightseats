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

Every reload is cheap: saved data is reused, so it costs no API requests while it is fresh.

## Tests

Tests never call the live API (200 requests a day, shared). Use a virtualenv:

```bash
python3.14 -m venv .venv && . .venv/bin/activate
pip install -r requirements_dev.txt
pytest tests -q
```

## API key for manual checks

Put it in `.env` (git-ignored) as `FLIGHTSEATS_API_KEY=...`. Never commit it, and keep live calls to a minimum.

Tests require Python 3.14.2+ and pin Home Assistant 2026.11.0. Run `ruff check custom_components tests` and `ruff format --check custom_components tests` before submitting changes. Use a separate development HA instance.
