# FlightSeats.io for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Watch cached Qantas and Virgin Australia Velocity **reward seat availability** from Home Assistant, and get an event when a seat you care about opens up.

Data comes from the [FlightSeats.io API](https://flightseats.io/api/reference). It needs a **FlightSeats.io Gold plan** and your own API key. The data is cached, not live airline inventory: always confirm on the airline's site before booking.

## What this does

You save one or more **watches** (for example "SYD or BNE to LAX, Business, 2 seats, under 250,000 points"). Each watch is polled on a slow schedule and becomes a device with sensors, a binary sensor and an event entity. Automations decide what to do with that, for example send a notification when `New availability` fires.

Version 0.1 covers watches, sensors, change events and quota protection. History and statistics are planned for later releases (see [CHANGELOG.md](CHANGELOG.md)).

### Entities

Account device **FlightSeats.io API** (diagnostic):

| Entity | Notes |
|---|---|
| Requests remaining today | From the API's rate-limit headers; attributes show limit, used, reset time and estimated daily use |
| Quota resets at | Timestamp (UTC midnight) |
| Daily request limit | Disabled by default |

Each **watch** device:

| Entity | Notes |
|---|---|
| Seats available | On when at least one fare matches the watch. Attributes echo the watch settings |
| Best points | Lowest points among matches, with flight, date, cabin, seats, tax and `last_seen` as attributes |
| Taxes for best fare | In the currency the API returns |
| Matching flights | Count; attribute `results` holds the top 10 (not stored in the recorder) |
| Data freshness | Timestamp of the newest `lastSeen` among matches |
| Earliest date | Disabled by default |
| Availability (event) | `new_availability`, `price_drop`, `availability_gone` |
| Check now (button) | Polls immediately, if enough quota is left |

Points and taxes appear to be per passenger: in a live check they did not change when the requested number of seats changed. Departure and arrival times are the airline's local times as strings; the API gives no time zone.

### Action

`ha_flightseats.search` runs one ad-hoc search and returns the flights as response data. It uses one request from the daily allowance and shares the same safety reserve.

## Installation

### HACS (custom repository)

1. HACS, Integrations, three-dot menu, Custom repositories.
2. Add `https://github.com/cloudbr34k84/home-assistant-flightseats` as an Integration.
3. Install **FlightSeats.io** and restart Home Assistant.

### Manual

Copy `custom_components/ha_flightseats` into your Home Assistant `custom_components` folder and restart.

## Configuration

1. Settings, Devices & services, **Add integration**, **FlightSeats.io**.
2. Paste your API key (create it under *API Access* in your FlightSeats.io dashboard). Checking the key uses one request.
3. On the integration page choose **Add watch** and fill in the form:
   - **Origins / destinations**: airport codes separated by commas (up to 30 each).
   - **Date window**: *Days ahead* for a rolling window, or *From/To* for fixed dates, or leave all empty for the program's full search horizon. The API rejects searches where origins x destinations x days is over 10,000; the form checks this for you.
   - **Minimum seats**, **cabins**, **maximum points**, **reward fares only**.
   - **Check every (hours)** and **alert cooldown**.

### Quota: 200 requests a day, shared

The API allows 200 requests per UTC day and 10 per minute. The allowance belongs to the Gold account, so it is **shared with the FlightSeats.io website and any other API key**. The integration protects it like this:

- Every check is one request. The form refuses a watch that would push the combined plan over 190 requests a day.
- Requests are spaced at least 7 seconds apart.
- Scheduled checks stop when 10 or fewer requests remain; the button and the search action can use the last few down to 3.
- It trusts the API's own remaining count over its own.
- The last result and the quota counters are saved, so a Home Assistant restart does not trigger new requests while the saved data is still fresh.

### Quiet, trustworthy alerts

- The first successful check only sets a baseline; it never raises events.
- A seat is reported as **gone** only after it is missing from two complete checks in a row. If the API returned its maximum number of results, nothing is inferred from what is missing.
- A seat that disappears and comes back inside the alert cooldown does not raise a second `new_availability`.
- At most one event of each type is raised per check, carrying the best match and up to five matches.
- Brief outages keep the last data; entities go unavailable after three failed checks in a row.

### Example automation

```yaml
alias: Reward seat found
triggers:
  - trigger: state
    entity_id: event.syd_lax_bus_availability
conditions:
  - condition: template
    value_template: "{{ trigger.to_state.state not in ['unknown', 'unavailable'] }}"
  - condition: template
    value_template: "{{ trigger.to_state.attributes.event_type == 'new_availability' }}"
actions:
  - action: script.notify_household
    data:
      message: >
        {{ trigger.to_state.attributes.count }} new seat(s) SYD to LAX:
        {{ trigger.to_state.attributes.points }} points + ${{ trigger.to_state.attributes.tax }}
        on {{ trigger.to_state.attributes.date }}
        ({{ trigger.to_state.attributes.flight_numbers | join(', ') }}).
        Confirm on the airline site before booking.
```

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| "Invalid API key" | The key was revoked or mistyped. Create a new one and use *Reconfigure* |
| Repair "FlightSeats.io needs a Gold plan" | The account is not on an active Gold plan |
| Entities show the last values and `Requests remaining today` is low | The shared daily allowance is nearly used. Checks resume after the reset (UTC midnight) |
| `Matching flights` has `api_limit_reached: true` | More than 500 flights matched. Narrow the watch (fewer airports, shorter window) |
| Watch says the window expired | A fixed *To* date has passed. Edit the watch |

Diagnostics (device page, three-dot menu) redact the API key and make no API request.

## Recovery

Removing the integration deletes its saved data file. Watches are stored in the config entry, so reinstalling means adding them again. Replacing the key does not remove watches.

## Terms

The FlightSeats.io API is for personal or internal use. Do not resell or bulk-redistribute its data. This project is not affiliated with FlightSeats.io, Qantas or Virgin Australia.
