"""Account-scoped repairs shared by setup, watch polls and ad-hoc searches."""

from typing import TypedDict

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, ISSUE_NOT_GOLD
from .data import FlightSeatsConfigEntry

# Older supported HA versions have no registry link; remove their issues explicitly.
_SUPPORTS_ENTRY_LINK = hasattr(ir.IssueEntry, "config_entry_id")


class _IssueLink(TypedDict, total=False):
    """Optional link supported by recent Home Assistant versions."""

    config_entry_id: str


@callback
def async_create_not_gold_issue(
    hass: HomeAssistant, entry: FlightSeatsConfigEntry
) -> None:
    """Explain how to restore API access; persist across unloads."""
    link: _IssueLink = (
        {"config_entry_id": entry.entry_id} if _SUPPORTS_ENTRY_LINK else {}
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{ISSUE_NOT_GOLD}_{entry.entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_NOT_GOLD,
        learn_more_url="https://flightseats.io/pricing",
        **link,
    )


@callback
def async_clear_not_gold_issue(
    hass: HomeAssistant, entry: FlightSeatsConfigEntry
) -> None:
    """Clear the repair only when a request confirms API access."""
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_NOT_GOLD}_{entry.entry_id}")
    # Migrate the original singleton repair created before entry-scoped issues.
    ir.async_delete_issue(hass, DOMAIN, ISSUE_NOT_GOLD)
