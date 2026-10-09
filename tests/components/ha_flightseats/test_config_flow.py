"""Tests for the config flow and the watch subentry flow."""
try:  # Home Assistant 2026.10 serialises forms with probatio
    from probatio import to_field_list as serialise
except ImportError:  # older versions use voluptuous-serialize
    from voluptuous_serialize import convert as serialise

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ha_flightseats.const import (
    CONF_API_KEY,
    CONF_COOLDOWN_HOURS,
    CONF_DAYS_AHEAD,
    CONF_DESTINATIONS,
    CONF_INTERVAL_HOURS,
    CONF_MIN_SEATS,
    CONF_ORIGINS,
    CONF_PROGRAMS,
    CONF_REWARD_ONLY,
    DOMAIN,
    SUBENTRY_TYPE_WATCH,
)

from .conftest import API_KEY, SEARCH_URL, WATCH_DATA, payload, rate_headers, setup_entry


async def _start(hass, key=API_KEY):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: key}
    )


async def test_user_flow_creates_entry(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(SEARCH_URL, json=payload(), headers=rate_headers())
    result = await _start(hass)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_API_KEY: API_KEY}
    assert len(aioclient_mock.mock_calls) == 1  # validation costs one request


async def test_user_flow_errors(hass: HomeAssistant, aioclient_mock):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    for status, error in ((401, "invalid_auth"), (403, "not_gold"), (500, "cannot_connect")):
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            SEARCH_URL, status=status, json={"error": {"message": "x"}}, headers=rate_headers()
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: API_KEY}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": error}
    aioclient_mock.clear_requests()
    aioclient_mock.get(SEARCH_URL, json=payload(), headers=rate_headers())
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_only_one_entry(hass: HomeAssistant, aioclient_mock, mock_entry):
    mock_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT


async def test_reauth_updates_key(hass: HomeAssistant, aioclient_mock, mock_entry):
    aioclient_mock.get(SEARCH_URL, json=payload(), headers=rate_headers())
    mock_entry.add_to_hass(hass)
    result = await mock_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "fs_live_new"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_entry.data[CONF_API_KEY] == "fs_live_new"


SECTIONS = {
    "filters": ("cabins", CONF_MIN_SEATS, "max_points", CONF_REWARD_ONLY),
    "dates": (CONF_DAYS_AHEAD, "date_from", "date_to"),
    "schedule": (CONF_INTERVAL_HOURS, CONF_COOLDOWN_HOURS),
}


def _watch_input(**overrides):
    """Build form input as the UI sends it: top-level fields plus section dictionaries."""
    flat = {
        CONF_PROGRAMS: ["QF"],
        CONF_ORIGINS: ["syd", "mel"],
        CONF_DESTINATIONS: ["LAX"],
        CONF_MIN_SEATS: 2,
        CONF_REWARD_ONLY: True,
        CONF_INTERVAL_HOURS: 6,
        CONF_COOLDOWN_HOURS: 12,
        **overrides,
    }
    nested = {k: v for k, v in flat.items() if not any(k in f for f in SECTIONS.values())}
    for name, fields in SECTIONS.items():
        nested[name] = {k: flat[k] for k in fields if k in flat}
    return nested


async def _add_watch(hass, entry, user_input):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_WATCH), context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.subentries.async_configure(result["flow_id"], user_input)


async def test_add_watch(hass: HomeAssistant, aioclient_mock, mock_entry):
    await setup_entry(hass, mock_entry, aioclient_mock, payload())
    result = await _add_watch(hass, mock_entry, _watch_input(**{CONF_DAYS_AHEAD: 30}))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "SYD/MEL → LAX"
    await hass.async_block_till_done()
    subentries = [s for s in mock_entry.subentries.values() if s.title == "SYD/MEL → LAX"]
    assert subentries[0].data[CONF_ORIGINS] == ["SYD", "MEL"]
    assert subentries[0].data[CONF_DAYS_AHEAD] == 30


async def test_watch_validation_errors(hass: HomeAssistant, aioclient_mock, mock_entry):
    await setup_entry(hass, mock_entry, aioclient_mock, payload())
    # Fields inside sections report at the top ("base"); top-level fields report inline.
    cases = [
        (_watch_input(**{CONF_ORIGINS: ["SYDNEY"]}), CONF_ORIGINS, "invalid_codes"),
        (_watch_input(**{CONF_PROGRAMS: []}), CONF_PROGRAMS, "no_programs"),
        (_watch_input(**{CONF_PROGRAMS: ["QF"], CONF_MIN_SEATS: 7}), "base", "too_many_seats"),
        (_watch_input(**{CONF_DAYS_AHEAD: 30, "date_from": "2027-01-01"}), "base", "date_conflict"),
        (_watch_input(**{"date_from": "2027-05-01", "date_to": "2027-04-01"}), "base", "date_order"),
    ]
    for user_input, field, error in cases:
        result = await _add_watch(hass, mock_entry, user_input)
        assert result["type"] is FlowResultType.FORM, error
        assert result["errors"].get(field) == error, error
        hass.config_entries.subentries.async_abort(result["flow_id"])


async def test_watch_too_many_permutations(hass: HomeAssistant, aioclient_mock, mock_entry):
    await setup_entry(hass, mock_entry, aioclient_mock, payload())
    many = [f"A{c}{d}" for c in "ABCDEFGH" for d in "ABCD"]  # 32 codes: too many
    result = await _add_watch(hass, mock_entry, _watch_input(**{CONF_ORIGINS: many}))
    assert result["errors"][CONF_ORIGINS] == "invalid_codes"
    ten = [f"A{c}{d}" for c in "AB" for d in "ABCDE"]  # 10 x 10 x 365
    result = await _add_watch(
        hass, mock_entry, _watch_input(**{CONF_ORIGINS: ten, CONF_DESTINATIONS: ten})
    )
    assert result["errors"]["base"] == "too_many_permutations"


async def test_reconfigure_watch(hass: HomeAssistant, aioclient_mock, mock_entry):
    await setup_entry(hass, mock_entry, aioclient_mock, payload())
    subentry_id = next(iter(mock_entry.subentries))
    result = await hass.config_entries.subentries.async_init(
        (mock_entry.entry_id, SUBENTRY_TYPE_WATCH),
        context={"source": config_entries.SOURCE_RECONFIGURE, "subentry_id": subentry_id},
    )
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**_watch_input(**{CONF_INTERVAL_HOURS: 12}), "name": "Renamed"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert mock_entry.subentries[subentry_id].title == "Renamed"
    assert mock_entry.subentries[subentry_id].data[CONF_INTERVAL_HOURS] == 12


async def test_over_budget(hass: HomeAssistant, aioclient_mock):
    """Eight hourly watches already use 192 of the 190 requests allowed per day."""
    from homeassistant.config_entries import ConfigSubentryData
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={CONF_API_KEY: API_KEY},
        subentries_data=[
            ConfigSubentryData(
                data={**WATCH_DATA, CONF_INTERVAL_HOURS: 1},
                subentry_type=SUBENTRY_TYPE_WATCH,
                title=f"Watch {index}",
                unique_id=None,
            )
            for index in range(8)
        ],
    )
    await setup_entry(hass, entry, aioclient_mock, payload())
    result = await _add_watch(hass, entry, _watch_input())
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "over_budget"}


async def test_form_serialises_with_sections_and_airports(
    hass: HomeAssistant, aioclient_mock, mock_entry
):
    """The form must serialise the way the frontend receives it."""
    from homeassistant.helpers import config_validation as cv

    await setup_entry(hass, mock_entry, aioclient_mock, payload())
    result = await hass.config_entries.subentries.async_init(
        (mock_entry.entry_id, SUBENTRY_TYPE_WATCH), context={"source": config_entries.SOURCE_USER}
    )
    fields = serialise(result["data_schema"], custom_serializer=cv.custom_serializer)
    by_name = {field["name"]: field for field in fields}
    assert [f["name"] for f in fields][:4] == ["name", "programs", "origins", "destinations"]
    assert by_name["filters"]["type"] == "expandable"
    assert by_name["filters"]["expanded"] is True
    assert by_name["dates"]["expanded"] is False
    assert by_name["dates"]["type"] == "expandable"
    origins = by_name["origins"]["selector"]["select"]
    assert origins["multiple"] and origins["custom_value"]
    assert {"value": "SYD", "label": "SYD – Sydney, AU"} in origins["options"]
    assert len(origins["options"]) > 200
    assert result["description_placeholders"]["allowed"] == "190"
