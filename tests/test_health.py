"""Installation health checks, raised as repair issues.

What is being tested is a judgement call as much as a mechanism: these two
conditions are worth interrupting the user about, and other conditions are not. So
the tests pin the thresholds, pin the fact that the issues clear themselves, and pin
that they do not fire on the noise every bus produces.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.maxa_advantix.const import DOMAIN
from custom_components.maxa_advantix.health import (
    BUS_ERROR_THRESHOLD,
    BUS_MIN_TRANSACTIONS,
    ISSUE_BUS_ERRORS,
    ISSUE_MODE_THRASHING,
    MODE_THRASHING_THRESHOLD,
    async_check,
)

from .fake_client import FakeModbusClient


def _issue(hass: HomeAssistant, entry_id: str, issue: str):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{issue}_{entry_id}")


def _check(hass: HomeAssistant, entry_id: str, **overrides) -> None:
    arguments = {"error_rate": 0.0, "transactions": 1000, "switches_per_hour": 0}
    arguments.update(overrides)
    async_check(hass, entry_id, **arguments)


async def test_a_healthy_bus_raises_nothing(hass: HomeAssistant) -> None:
    _check(hass, "entry")
    assert _issue(hass, "entry", ISSUE_BUS_ERRORS) is None
    assert _issue(hass, "entry", ISSUE_MODE_THRASHING) is None


async def test_ordinary_bus_noise_raises_nothing(hass: HomeAssistant) -> None:
    """Healthy gateways return the odd timeout; that is not a fault to report."""
    _check(hass, "entry", error_rate=2.0)
    assert _issue(hass, "entry", ISSUE_BUS_ERRORS) is None


async def test_a_bad_first_read_does_not_raise(hass: HomeAssistant) -> None:
    """One failure out of three reads is 33 % and means nothing yet."""
    _check(hass, "entry", error_rate=33.0, transactions=BUS_MIN_TRANSACTIONS - 1)
    assert _issue(hass, "entry", ISSUE_BUS_ERRORS) is None


async def test_a_sustained_error_rate_raises(hass: HomeAssistant) -> None:
    _check(hass, "entry", error_rate=BUS_ERROR_THRESHOLD + 5)
    issue = _issue(hass, "entry", ISSUE_BUS_ERRORS)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.is_fixable is False
    assert issue.translation_key == ISSUE_BUS_ERRORS
    assert issue.translation_placeholders == {"error_rate": "15.0", "threshold": "10"}


async def test_the_error_issue_clears_itself(hass: HomeAssistant) -> None:
    """A blip must not leave a permanent scar in the UI."""
    _check(hass, "entry", error_rate=50.0)
    assert _issue(hass, "entry", ISSUE_BUS_ERRORS) is not None
    _check(hass, "entry", error_rate=0.0)
    assert _issue(hass, "entry", ISSUE_BUS_ERRORS) is None


async def test_normal_alternation_is_not_thrashing(hass: HomeAssistant) -> None:
    _check(hass, "entry", switches_per_hour=MODE_THRASHING_THRESHOLD - 1)
    assert _issue(hass, "entry", ISSUE_MODE_THRASHING) is None


async def test_thrashing_raises_with_the_count(hass: HomeAssistant) -> None:
    _check(hass, "entry", switches_per_hour=40)
    issue = _issue(hass, "entry", ISSUE_MODE_THRASHING)
    assert issue is not None
    assert issue.translation_placeholders == {"switches": "40", "threshold": "12"}


async def test_the_two_issues_are_independent(hass: HomeAssistant) -> None:
    _check(hass, "entry", error_rate=50.0, switches_per_hour=40)
    assert _issue(hass, "entry", ISSUE_BUS_ERRORS) is not None
    assert _issue(hass, "entry", ISSUE_MODE_THRASHING) is not None

    _check(hass, "entry", error_rate=0.0, switches_per_hour=40)
    assert _issue(hass, "entry", ISSUE_BUS_ERRORS) is None
    assert _issue(hass, "entry", ISSUE_MODE_THRASHING) is not None


async def test_issues_are_per_entry(hass: HomeAssistant) -> None:
    """Two heat pumps in one house must not report each other's problems."""
    _check(hass, "first", error_rate=50.0)
    _check(hass, "second", error_rate=0.0)
    assert _issue(hass, "first", ISSUE_BUS_ERRORS) is not None
    assert _issue(hass, "second", ISSUE_BUS_ERRORS) is None


# ── through the coordinator, against a machine ────────────────────────────────
async def test_the_switch_rate_counts_only_the_last_hour(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    """A total since startup cannot distinguish thrashing from a long uptime."""
    coordinator = loaded_entry.runtime_data
    assert coordinator.data["mode_switches_per_hour"] == 0

    for state in (2, 6, 2, 6):
        fake_client.registers[200] = state
        await coordinator.async_refresh()

    assert coordinator.data["mode_switches"] == 4
    assert coordinator.data["mode_switches_per_hour"] == 4


async def test_thrashing_through_the_coordinator_raises_the_issue(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    coordinator = loaded_entry.runtime_data
    for index in range(MODE_THRASHING_THRESHOLD + 2):
        fake_client.registers[200] = 2 if index % 2 else 6
        await coordinator.async_refresh()

    assert _issue(hass, loaded_entry.entry_id, ISSUE_MODE_THRASHING) is not None


async def test_unloading_clears_the_issues(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    """An issue about a machine that is no longer configured is just noise."""
    coordinator = loaded_entry.runtime_data
    for index in range(MODE_THRASHING_THRESHOLD + 2):
        fake_client.registers[200] = 2 if index % 2 else 6
        await coordinator.async_refresh()
    assert _issue(hass, loaded_entry.entry_id, ISSUE_MODE_THRASHING) is not None

    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert _issue(hass, loaded_entry.entry_id, ISSUE_MODE_THRASHING) is None


async def test_the_mode_switch_sensor_exposes_the_rate(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    from homeassistant.const import Platform
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{loaded_entry.entry_id}_mode_switches"
    )
    attributes = hass.states.get(entity_id).attributes
    assert attributes["per_hour"] == 0
    assert attributes["thrashing_threshold"] == MODE_THRASHING_THRESHOLD


@pytest.mark.parametrize(
    ("issue", "placeholders"),
    [
        (ISSUE_BUS_ERRORS, {"error_rate", "threshold"}),
        (ISSUE_MODE_THRASHING, {"switches", "threshold"}),
    ],
)
def test_translations_use_exactly_the_placeholders_supplied(issue, placeholders):
    """A placeholder mismatch renders as a broken sentence in the user's language."""
    import json
    import pathlib
    import re

    strings = json.loads(
        (
            pathlib.Path(__file__).parent.parent
            / "custom_components"
            / "maxa_advantix"
            / "strings.json"
        ).read_text()
    )
    text = strings["issues"][issue]["title"] + strings["issues"][issue]["description"]
    assert set(re.findall(r"\{(\w+)\}", text)) == placeholders
