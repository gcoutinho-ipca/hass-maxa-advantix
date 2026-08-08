"""Decoding of alarm words 950 / 951 / 952 for the i-HWAK V4 controller.

Three 16-bit registers carry 48 alarm flags. The generic Modbus integration can
only publish the three raw numbers; turning them into "E042, insufficient DHW
heat exchange" is the difference between a number and a diagnosis.

One caveat worth knowing before reusing this table: the bitmap published for the
older V2/V3 family **differs** from the V4 one, and mixing them up sends you
chasing the wrong fault. This table is the V4 map. Keeping it isolated in its
own module is what makes supporting another generation a table swap.

Bit positions with no entry are reserved by the manufacturer and are counted by
`count()` but not named by `decode()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .registers import ALARM_FIRST_REGISTER


@dataclass(frozen=True)
class AlarmDef:
    """One alarm flag: where it lives and what it means."""

    code: str
    description: str
    #: index into the alarm word list: 0 = register 950, 1 = 951, 2 = 952
    word: int
    bit: int

    @property
    def register(self) -> int:
        """Absolute register number, for diagnostics and bug reports."""
        return ALARM_FIRST_REGISTER + self.word

    @property
    def key(self) -> str:
        """Stable entity key, e.g. `alarm_e042`."""
        return f"alarm_{self.code.lower()}"


def _defs() -> tuple[AlarmDef, ...]:
    """Flatten the per-word bit maps into one ordered tuple."""
    maps: dict[int, dict[int, tuple[str, str]]] = {
        0: {  # register 950
            0: ("E001", "High pressure"),
            1: ("E002", "Low pressure"),
            2: ("E003", "Compressor overload"),
            3: ("E004", "Fan overload"),
            4: ("E005", "Antifreeze"),
            5: ("E006", "Flow switch - no water flow"),
            6: ("E007", "Low DHW preheater temperature"),
            7: ("E008", "Lubrication failure"),
            8: ("E009", "High discharge temperature, compressor 1"),
            9: ("E010", "High solar collector temperature"),
            12: ("E013", "Compressor 2 overload"),
            13: ("E014", "Fan 2 overload"),
            15: ("E016", "Pump overload"),
        },
        1: {  # register 951
            1: ("E018", "High temperature"),
            2: ("E019", "High discharge temperature, compressor 2"),
            3: ("E020", "Pressure transducers swapped"),
            6: ("E023", "Compressor 3 overload"),
            7: ("E024", "Fan 3 overload"),
            9: ("E026", "Pump 2 overload"),
            11: ("E041", "Inconsistent temperature readings"),
            12: ("E042", "Insufficient DHW heat exchange"),
            13: ("E050", "High DHW storage temperature"),
            14: ("E101", "I/O module 1 offline"),
            15: ("E102", "I/O module 2 offline"),
        },
        2: {  # register 952 - probe faults
            0: ("E611", "Probe 1 fault"),
            1: ("E621", "Probe 2 fault"),
            2: ("E631", "Probe 3 fault"),
            3: ("E641", "Probe 4 fault"),
            4: ("E651", "Probe 5 fault"),
            5: ("E661", "Probe 6 fault"),
            6: ("E671", "Probe 7 fault"),
            7: ("E681", "Probe 8 fault"),
            8: ("E691", "Probe 9 fault"),
            9: ("E701", "Probe 10 fault"),
            10: ("E711", "Probe 11 fault"),
            11: ("E612", "Probe 1 fault, I/O module 1"),
            12: ("E622", "Probe 2 fault, I/O module 1"),
            13: ("E632", "Probe 3 fault, I/O module 1"),
            14: ("E642", "Probe 4 fault, I/O module 1"),
            15: ("E652", "Probe 5 fault, I/O module 1"),
        },
    }
    return tuple(
        AlarmDef(code, description, word, bit)
        for word, bits in maps.items()
        for bit, (code, description) in sorted(bits.items())
    )


ALARMS: Final[tuple[AlarmDef, ...]] = _defs()
ALARMS_BY_CODE: Final[dict[str, AlarmDef]] = {a.code: a for a in ALARMS}


def is_active(words: list[int] | None, alarm: AlarmDef) -> bool:
    """Whether a single alarm flag is set in the current reading."""
    if not words or alarm.word >= len(words):
        return False
    value = words[alarm.word]
    if value is None or value < 0:
        return False
    return bool(value & (1 << alarm.bit))


def decode(words: list[int] | None) -> list[dict[str, str | int]]:
    """Turn [950, 951, 952] into the list of named active alarms.

    Negative or missing words are skipped: they mean the read failed, and an
    unreadable register is not the same thing as forty absent alarms.
    """
    if not words:
        return []
    return [
        {
            "code": a.code,
            "description": a.description,
            "register": a.register,
            "bit": a.bit,
        }
        for a in ALARMS
        if is_active(words, a)
    ]


def count(words: list[int] | None) -> int:
    """How many flags are set in total, including reserved unnamed bits."""
    if not words:
        return 0
    return sum(
        bin(value & 0xFFFF).count("1") for value in words[:3] if value is not None and value >= 0
    )
