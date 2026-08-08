"""The packed state word is where a careless change breaks someone's heating."""

from __future__ import annotations

import pytest

from custom_components.maxa_advantix.const import MACHINE_STATES
from custom_components.maxa_advantix.states import (
    compose,
    decompose,
    with_conditioning,
    with_dhw,
)


@pytest.mark.parametrize(
    ("conditioning", "dhw", "expected"),
    [
        ("off", False, 0),
        ("cool", False, 1),
        ("heat", False, 2),
        ("off", True, 4),
        ("cool", True, 5),
        ("heat", True, 6),
    ],
)
def test_compose(conditioning, dhw, expected):
    assert compose(conditioning, dhw) == expected


def test_compose_rejects_unknown_mode():
    with pytest.raises(ValueError, match="unknown conditioning mode"):
        compose("dehumidify", False)


def test_round_trip_for_every_legal_state():
    """Every value the controller accepts must survive a decompose/compose pair."""
    for state in MACHINE_STATES:
        conditioning, dhw = decompose(state)
        assert compose(conditioning, dhw) == state


def test_illegal_and_missing_states_degrade_quietly():
    """A machine answering nonsense must not break the UI."""
    assert decompose(None) == ("off", False)
    assert decompose(3) == ("off", False)  # refused by the controller
    assert decompose(7) == ("off", False)
    assert decompose(999) == ("off", False)


@pytest.mark.parametrize("state", list(MACHINE_STATES))
def test_changing_conditioning_preserves_dhw(state):
    """The whole reason these helpers exist."""
    _, dhw_before = decompose(state)
    for mode in ("off", "cool", "heat"):
        new_state = with_conditioning(state, mode)
        conditioning_after, dhw_after = decompose(new_state)
        assert conditioning_after == mode
        assert dhw_after is dhw_before


@pytest.mark.parametrize("state", list(MACHINE_STATES))
def test_changing_dhw_preserves_conditioning(state):
    conditioning_before, _ = decompose(state)
    for enabled in (True, False):
        new_state = with_dhw(state, enabled)
        conditioning_after, dhw_after = decompose(new_state)
        assert dhw_after is enabled
        assert conditioning_after == conditioning_before


def test_turning_heating_off_leaves_hot_water_on():
    """The specific bug this module prevents, stated as a test."""
    heating_and_dhw = 6
    assert with_conditioning(heating_and_dhw, "off") == 4  # DHW only, not standby


def test_turning_hot_water_off_leaves_heating_on():
    heating_and_dhw = 6
    assert with_dhw(heating_and_dhw, False) == 2  # heating only, not standby
