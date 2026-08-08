"""The example dashboard must reference entities that exist.

A Lovelace YAML is not validated by anything: Home Assistant renders a card for an
unknown entity as "Entity not found" and carries on. So an example dashboard is
exactly the kind of file that rots silently, and the person who finds out is the one
who pasted it in expecting it to work.

This checks the example against the entities the integration actually creates, by
loading it and reading the registry rather than by keeping a second list in step with
the first. Renaming an entity now fails here, which is the point: the rename is fine,
shipping an example that no longer matches it is not.

The device prefix in the example (`maxa_`) is a placeholder, since real ids are built
from the name the user gave the machine. What has to be right is everything after it.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify
from pytest_homeassistant_custom_component.common import MockConfigEntry

DASHBOARD = pathlib.Path(__file__).parent.parent / "examples" / "dashboard.yaml"

#: Matches every entity reference in the file, whether it sits under an `entity:`
#: key or inside a Jinja template. Templates are the half that a YAML-structure
#: walk would miss, and the alarm card is written entirely in one.
REFERENCE = re.compile(
    r"\b(sensor|binary_sensor|climate|water_heater|number|select|switch|button)"
    r"\.maxa_([a-z0-9_]+)"
)


@pytest.fixture
def dashboard_text() -> str:
    """The example, or a failure saying it is missing.

    Not a skip. A skipped test reads like a passing one in CI output, and the file
    being absent from the test image is the failure mode this fixture exists to
    catch: it happened once already with `blueprints/`.
    """
    assert DASHBOARD.is_file(), f"{DASHBOARD} is missing from the test tree"
    return DASHBOARD.read_text(encoding="utf-8")


def test_the_example_is_valid_yaml(dashboard_text: str) -> None:
    parsed = yaml.safe_load(dashboard_text)
    assert isinstance(parsed["views"], list) and parsed["views"]


def test_every_referenced_entity_exists(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, dashboard_text: str
) -> None:
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, loaded_entry.entry_id)

    # Entity ids are the device name slug plus the entity name slug, so stripping the
    # former leaves the part the example has to get right.
    prefix = f"{slugify(loaded_entry.title)}_"
    real: dict[str, set[str]] = {}
    for entry in entries:
        domain, _, object_id = entry.entity_id.partition(".")
        assert object_id.startswith(prefix), f"unexpected entity id {entry.entity_id}"
        real.setdefault(domain, set()).add(object_id.removeprefix(prefix))

    referenced = set(REFERENCE.findall(dashboard_text))
    assert referenced, "no entity references found; the regex or the file changed shape"

    missing = sorted(
        f"{domain}.maxa_{suffix}"
        for domain, suffix in referenced
        if suffix not in real.get(domain, set())
    )
    assert not missing, "the example dashboard references entities that do not exist: " + ", ".join(
        missing
    )


def test_referenced_entities_are_enabled_by_default(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, dashboard_text: str
) -> None:
    """A disabled entity renders as an empty card, which looks like a broken example.

    The forty per-alarm binary sensors ship disabled on purpose, so the example must
    stay off them and use the aggregate sensor instead.
    """
    registry = er.async_get(hass)
    prefix = f"{slugify(loaded_entry.title)}_"
    disabled = {
        f"{entry.entity_id.split('.')[0]}.maxa_"
        f"{entry.entity_id.partition('.')[2].removeprefix(prefix)}"
        for entry in er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
        if entry.disabled_by is not None
    }

    referenced = {f"{domain}.maxa_{suffix}" for domain, suffix in REFERENCE.findall(dashboard_text)}
    assert not referenced & disabled, (
        "the example references entities that are disabled by default: "
        + ", ".join(sorted(referenced & disabled))
    )
