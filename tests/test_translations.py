"""Translation files must stay in step with each other and with the code.

`hassfest` checks that `strings.json` is well formed; it does not check that the
translation keys the entities actually set have an entry, nor that the language
files have not drifted apart. Both failures are invisible until a user sees a raw
key like `mode_switches` in their dashboard.

Deliberately written without importing the integration, so it also runs in an
environment that has no Home Assistant installed.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import pytest

COMPONENT = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "maxa_advantix"
STRINGS = COMPONENT / "strings.json"
TRANSLATIONS = COMPONENT / "translations"

#: platform module -> the section of `entity` its keys live in
PLATFORMS = (
    "sensor",
    "binary_sensor",
    "climate",
    "water_heater",
    "select",
    "number",
    "switch",
    "button",
)


def _load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _keys(node: Any, prefix: str = "") -> set[str]:
    """Flatten a nested dict into dotted paths, so two files can be compared."""
    if not isinstance(node, dict):
        return {prefix}
    return set().union(
        *(_keys(value, f"{prefix}.{key}" if prefix else key) for key, value in node.items())
    ) or {prefix}


def _declared_translation_keys(platform: str) -> set[str]:
    """Collect the translation keys the platform module assigns, by reading its source.

    Regex rather than import, so this test does not need Home Assistant. The two
    forms used in this codebase are a class attribute and an assignment in
    `__init__`, and both are covered.
    """
    source = (COMPONENT / f"{platform}.py").read_text()
    literal = set(re.findall(r'_attr_translation_key\s*=\s*["\']([\w]+)["\']', source))
    return literal


def test_strings_and_english_translation_are_identical():
    """`translations/en.json` is a copy of `strings.json`, not a separate document."""
    assert _load(STRINGS) == _load(TRANSLATIONS / "en.json")


@pytest.mark.parametrize("language", ["pt", "it"])
def test_translations_have_the_same_keys_as_the_base(language: str):
    base = _keys(_load(STRINGS))
    other = _keys(_load(TRANSLATIONS / f"{language}.json"))
    missing = base - other
    extra = other - base
    assert not missing, f"{language}.json is missing: {sorted(missing)}"
    assert not extra, f"{language}.json has keys the base does not: {sorted(extra)}"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_every_declared_translation_key_has_a_name(platform: str):
    """A key without an entry renders as the raw slug in the user's language."""
    strings = _load(STRINGS)
    section = strings["entity"].get(platform, {})
    for key in _declared_translation_keys(platform):
        assert key in section, f"entity.{platform}.{key} is missing from strings.json"
        assert "name" in section[key] or "state" in section[key], (
            f"entity.{platform}.{key} has neither a name nor states"
        )


def test_machine_state_options_match_everywhere():
    """The enum appears in three places and drift between them is a silent bug."""
    strings = _load(STRINGS)
    selector = set(strings["selector"]["machine_state"]["options"])
    sensor = set(strings["entity"]["sensor"]["machine_state"]["state"])
    select = set(strings["entity"]["select"]["machine_state"]["state"])
    assert selector == sensor == select
    assert selector == {
        "standby",
        "cooling",
        "heating",
        "dhw",
        "cooling_dhw",
        "heating_dhw",
    }


def test_state_slugs_are_english_and_lowercase():
    """Slugs are public API: they end up in other people's automations."""
    for slug in _load(STRINGS)["selector"]["machine_state"]["options"]:
        assert re.fullmatch(r"[a-z][a-z_]*", slug), slug


def test_every_service_in_services_yaml_is_documented():
    """A service with no strings entry shows up unnamed in the UI."""
    import yaml

    services = yaml.safe_load((COMPONENT / "services.yaml").read_text())
    documented = _load(STRINGS)["services"]
    assert set(services) == set(documented)
    for name, spec in services.items():
        fields = set(spec.get("fields") or {})
        described = set(documented[name].get("fields") or {})
        assert fields == described, f"{name}: fields {fields} vs described {described}"
