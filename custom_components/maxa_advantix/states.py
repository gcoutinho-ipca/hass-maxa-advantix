"""Composition and decomposition of the machine state word.

Register 200 (read) / 7200 (write) packs two independent user intents into a
single enum: what the space-conditioning side should do, and whether domestic
hot water is allowed. That is why a `climate` entity and a `water_heater`
entity cannot each own the register: one would clobber the other.

The rule implemented here is: each platform changes only its own half and
preserves the other. Keeping it as two pure functions means it is testable
without Home Assistant, and there is exactly one place where the mapping of
the six legal values lives.

    state | conditioning | DHW
    ------+--------------+-----
      0   | off          | off
      1   | cool         | off
      2   | heat         | off
      4   | off          | on
      5   | cool         | on
      6   | heat         | on

Values 3 and 7 are rejected by the controller and are never produced here.
"""

from __future__ import annotations

from typing import Final, Literal

Conditioning = Literal["off", "cool", "heat"]

#: conditioning half -> (state without DHW, state with DHW)
_TABLE: Final[dict[str, tuple[int, int]]] = {
    "off": (0, 4),
    "cool": (1, 5),
    "heat": (2, 6),
}

#: raw state -> (conditioning half, DHW half)
_REVERSE: Final[dict[int, tuple[Conditioning, bool]]] = {
    0: ("off", False),
    1: ("cool", False),
    2: ("heat", False),
    4: ("off", True),
    5: ("cool", True),
    6: ("heat", True),
}


def compose(conditioning: Conditioning, dhw: bool) -> int:
    """Build the raw state value from the two independent halves."""
    if conditioning not in _TABLE:
        raise ValueError(f"unknown conditioning mode: {conditioning!r}")
    without, with_dhw = _TABLE[conditioning]
    return with_dhw if dhw else without


def decompose(state: int | None) -> tuple[Conditioning, bool]:
    """Split a raw state value into (conditioning, dhw).

    Unknown or missing values decompose to ("off", False) rather than raising:
    a machine that answers something unexpected must not break the UI.
    """
    if state is None:
        return "off", False
    return _REVERSE.get(state, ("off", False))


def with_conditioning(state: int | None, conditioning: Conditioning) -> int:
    """Change only the conditioning half, keeping DHW as it is."""
    _, dhw = decompose(state)
    return compose(conditioning, dhw)


def with_dhw(state: int | None, dhw: bool) -> int:
    """Change only the DHW half, keeping conditioning as it is."""
    conditioning, _ = decompose(state)
    return compose(conditioning, dhw)
