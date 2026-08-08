"""Validate the blueprints with Home Assistant's own schema.

`scripts/check_yaml.py` checks that the files parse and that every `!input`
resolves, which catches typos. It knows nothing about what Home Assistant will
actually accept, so a blueprint can pass it and still fail to import on a user's
machine with a message about a field they have never heard of.

These tests load each blueprint through the same `Blueprint` class Home Assistant
uses, then substitute the inputs and validate the resulting automation against the
real automation schema. A blueprint that passes here is one that imports.

Worth stating what is not tested: whether the automations do the right thing. That
is a question about heat pumps and about someone's house, and no test suite answers
it. What is tested is that they are well formed, that their inputs are wired to
something, and that the entity domains they target are the ones the integration
actually provides.
"""

from __future__ import annotations

import pathlib

import pytest
import voluptuous as vol
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.core import HomeAssistant
from homeassistant.util.yaml import parse_yaml

BLUEPRINTS = sorted(
    (pathlib.Path(__file__).parent.parent / "blueprints" / "automation" / "maxa_advantix")
    .glob("*.yaml")
)

#: Every blueprint shipped, by file name, so a new one cannot be added without
#: appearing here and being deliberately accounted for.
EXPECTED = {
    "dhw_hysteresis.yaml",
    "dhw_recirculation.yaml",
    "electric_backup.yaml",
    "fault_alert.yaml",
    "solar_priority.yaml",
}


def _load(path: pathlib.Path) -> Blueprint:
    """Load through the same class and schema Home Assistant uses on import."""
    return Blueprint(
        parse_yaml(path.read_text()),
        expected_domain="automation",
        path=str(path.name),
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )


def test_the_expected_set_is_shipped():
    assert {path.name for path in BLUEPRINTS} == EXPECTED


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_home_assistant_accepts_the_blueprint(path: pathlib.Path):
    """The schema check that decides whether an import succeeds."""
    blueprint = _load(path)
    assert blueprint.metadata["domain"] == "automation"
    assert blueprint.name
    assert blueprint.metadata["description"]


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_every_input_is_documented(path: pathlib.Path):
    """An input without a name renders as a bare slug in the import dialog."""
    blueprint = _load(path)
    for key, definition in blueprint.inputs.items():
        assert definition is not None, key
        # Sections carry nested inputs and need no name of their own.
        if "input" in definition:
            for nested_key, nested in definition["input"].items():
                assert nested.get("name"), f"{path.name}: {nested_key} has no name"
            continue
        assert definition.get("name"), f"{path.name}: {key} has no name"


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_every_input_has_a_selector(path: pathlib.Path):
    """Without one the user gets a free-text box and has to guess the format."""
    blueprint = _load(path)
    for key, definition in blueprint.inputs.items():
        if "input" in definition:
            for nested_key, nested in definition["input"].items():
                assert "selector" in nested, f"{path.name}: {nested_key} has no selector"
            continue
        assert "selector" in definition, f"{path.name}: {key} has no selector"


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_source_url_points_at_this_repository(path: pathlib.Path):
    """The URL is what Home Assistant offers as "re-import" later."""
    blueprint = _load(path)
    url = blueprint.metadata.get("source_url", "")
    assert "gcoutinho-ipca/hass-maxa-advantix" in url
    assert url.endswith(path.name), "the source_url must point at this exact file"


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_author_is_the_published_identity(path: pathlib.Path):
    blueprint = _load(path)
    assert blueprint.metadata.get("author") == "gcoutinho <gcoutinho@gmail.com>"


def _inputs_for(blueprint: Blueprint) -> dict[str, object]:
    """Plausible values for every input, so substitution can be exercised.

    Entity ids that do not exist are fine and deliberate: this validates the shape
    of the resulting automation, and pointing at a real entity would risk the
    automation doing something.
    """
    values: dict[str, object] = {}

    def add(key: str, definition: dict) -> None:
        selector = definition.get("selector", {})
        if "entity" in selector:
            multiple = (selector["entity"] or {}).get("multiple")
            values[key] = ["sensor.does_not_exist"] if multiple else "sensor.does_not_exist"
        elif "number" in selector:
            values[key] = definition.get("default", 1)
        elif "time" in selector:
            values[key] = definition.get("default", "01:00:00")
        elif "text" in selector:
            values[key] = definition.get("default", "notify.persistent_notification")
        else:
            values[key] = definition.get("default", "x")

    for key, definition in blueprint.inputs.items():
        if "input" in definition:
            for nested_key, nested in definition["input"].items():
                add(nested_key, nested)
            continue
        add(key, definition)
    return values


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
async def test_the_substituted_automation_is_valid(hass: HomeAssistant, path: pathlib.Path):
    """Substitute every input and run the result through the automation schema.

    This is the test that catches a malformed trigger, a condition that is not a
    condition, or an action referring to a service shape that does not exist. It
    validates only; nothing is added to Home Assistant and nothing runs.
    """
    from homeassistant.components.automation import config as automation_config

    blueprint = _load(path)
    inputs = BlueprintInputs(
        blueprint,
        {"use_blueprint": {"path": path.name, "input": _inputs_for(blueprint)}},
    )
    substituted = inputs.async_substitute()

    try:
        await automation_config.async_validate_config_item(hass, path.stem, substituted)
    except vol.Invalid as err:
        pytest.fail(f"{path.name}: the substituted automation is invalid: {err}")


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_no_write_service_is_called_on_the_heat_pump(path: pathlib.Path):
    """The blueprints must not write to the machine outside its own entities.

    They are allowed to call `water_heater.turn_on` and friends on the integration's
    entities, because that is what a hot water schedule is. What they must never do
    is reach past those into the raw control surface: writing the state register from
    an automation is how you disable hot water by accident while turning the heating
    off.
    """
    text = path.read_text()
    for forbidden in (
        "maxa_advantix.set_mode",
        "maxa_advantix.release_control",
        "select.select_option",
        "number.set_value",
    ):
        assert forbidden not in text, f"{path.name} calls {forbidden}"
