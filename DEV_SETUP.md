# Local Development Setup

The repo uses the standard HACS layout. Home Assistant needs the integration folder directly under its own `custom_components/`, so a symlink bridges the two.

```
/homeassistant/
├── brads_dev/
│   └── home-assistant-flightseats/        <- repo (edit files here)
│       ├── custom_components/
│       │   └── ha_flightseats/            <- integration source
│       ├── tests/
│       └── docs/openapi.json              <- FlightSeats.io API spec
└── custom_components/
    └── ha_flightseats -> /homeassistant/brads_dev/home-assistant-flightseats/custom_components/ha_flightseats
```

Recreate the symlink if it is lost:

```bash
ln -s /homeassistant/brads_dev/home-assistant-flightseats/custom_components/ha_flightseats \
      /homeassistant/custom_components/ha_flightseats
```

## After making changes

| Change | What to do |
|---|---|
| Python logic | Reload the integration entry (or restart HA) |
| `manifest.json`, new files, `strings.json`, `icons.json`, `services.yaml` | Full HA restart |

Every reload is cheap: saved data is reused, so it costs no API requests while it is fresh.

## Tests

Tests never call the live API (200 requests a day, shared). Use a virtualenv:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest tests -q
```

## API key for manual checks

Put it in `.env` (git-ignored) as `FLIGHTSEATS_API_KEY=...`. Never commit it, and keep live calls to a minimum.
