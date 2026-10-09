"""Sanity checks for the bundled airport list."""
import re

from custom_components.ha_flightseats.airports import AIRPORTS


def test_airport_list_is_well_formed():
    assert len(AIRPORTS) > 200
    for code, label in AIRPORTS.items():
        assert re.fullmatch(r"[A-Z]{3}", code)
        assert label.startswith(f"{code} – ")
    for code in ("SYD", "MEL", "BNE", "PER", "AKL", "LAX", "SIN", "LHR", "DXB", "DOH", "HND"):
        assert code in AIRPORTS
    assert AIRPORTS["LHR"] != AIRPORTS["LGW"]
    assert "Heathrow" in AIRPORTS["LHR"] and "Gatwick" in AIRPORTS["LGW"]
