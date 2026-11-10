"""Shared pytest fixtures."""

import sys

import pytest

try:
    import pytest_homeassistant  # noqa: F401
except ModuleNotFoundError:
    # HA 2026.8 uses the predecessor package name. Alias only the test helpers
    # imported by this suite so the same tests prove the declared minimum.
    import pytest_homeassistant_custom_component as _ha_test
    from pytest_homeassistant_custom_component import common as _common
    from pytest_homeassistant_custom_component import components as _components
    from pytest_homeassistant_custom_component import test_util as _test_util
    from pytest_homeassistant_custom_component.components import (
        diagnostics as _diagnostics,
    )
    from pytest_homeassistant_custom_component.test_util import aiohttp as _aiohttp

    sys.modules["pytest_homeassistant"] = _ha_test
    sys.modules["pytest_homeassistant.common"] = _common
    sys.modules["pytest_homeassistant.components"] = _components
    sys.modules["pytest_homeassistant.components.diagnostics"] = _diagnostics
    sys.modules["pytest_homeassistant.test_util"] = _test_util
    sys.modules["pytest_homeassistant.test_util.aiohttp"] = _aiohttp


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load the integration under test."""
    yield
