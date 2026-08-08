"""Declarative register map for the i-HWAK V4 family.

Verified against live readings from an RTU-to-TCP gateway (direct addressing:
`address` is the register number from the manual, with no off-by-one) and
cross-checked with the manufacturer's Modbus table for the V4 controller.

Every `ReadRegister` says how to turn a raw 16-bit integer into a measurement.
`scale` divides the value; `sentinel` enables the sentinel filter, so an absent
probe makes the entity unavailable instead of reporting 32766 as a reading.

The map is isolated in this module on purpose: supporting another controller
generation should be a matter of swapping this table, not of touching the
coordinator.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from homeassistant.const import (
    PERCENTAGE,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolumeFlowRate,
)


@dataclass(frozen=True)
class ReadRegister:
    """A readable register and how to interpret it."""

    key: str
    address: int
    scale: float = 1.0
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = "measurement"
    icon: str | None = None
    #: filter the manufacturer's "probe absent/faulty" sentinel values
    sentinel: bool = True
    #: created but disabled in the entity registry (optional hardware)
    enabled_default: bool = True
    #: shown under the device's diagnostics section rather than as a control
    diagnostic: bool = False
    suggested_display_precision: int | None = None


@dataclass(frozen=True)
class ReadBlock:
    """One contiguous Modbus read: `count` registers starting at `start`."""

    start: int
    count: int

    @property
    def end(self) -> int:
        """Last address covered, inclusive."""
        return self.start + self.count - 1

    def __contains__(self, address: int) -> bool:
        return self.start <= address <= self.end

    def __str__(self) -> str:
        return f"{self.start}-{self.end} ({self.count})"


# How far apart two needed registers can be before a second transaction is cheaper
# than reading the gap.
#
# At 9600 baud 8N1 a character takes about 1 ms, so a transaction costs roughly
# 30 ms of fixed overhead (request frame, line turnaround, reply header) and about
# 2 ms per register in the reply. Sweeping this parameter across the real register
# set gives:
#
#     max_gap   transactions   registers   line time
#           0             15          24      500 ms
#           4             12          32      427 ms
#           8              8          59      364 ms
#          10              7          69      355 ms   <- optimum starts here
#          16              7          69      355 ms   <- chosen
#          48              7          69      355 ms   <- optimum ends here
#          64              6         121      434 ms
#
# So the curve is flat between 10 and 48 and gets worse either side, and 16 sits
# comfortably in the middle of the flat region. Sixteen registers nobody wants is
# still cheaper than one more round trip; a hundred is not.
#
# `test_registers.py` asserts that the chosen value is still at the optimum, so
# changing it to something worse fails the build instead of quietly costing bus
# time on every poll.
MAX_GAP: Final = 16

# Ceiling on a single read. The protocol allows 125; staying well under keeps each
# reply small enough that one bad frame costs little to retry, leaves headroom for
# gateways that quietly cap their buffers below the spec, and is what stops the
# planner from merging the 400s with the 7000s into one enormous read.
MAX_BLOCK: Final = 64

# Cost model used by the tests, in milliseconds. Not used at runtime: the plan is
# computed once at import and the constants above are the tuned result.
TRANSACTION_OVERHEAD_MS: Final = 30.0
PER_REGISTER_MS: Final = 2.1


def plan_blocks(
    addresses: Iterable[int], max_gap: int = MAX_GAP, max_block: int = MAX_BLOCK
) -> tuple[ReadBlock, ...]:
    """Merge the addresses that must be read into as few transactions as possible.

    Sorted, then greedily extended: an address joins the current block when it fits
    under `max_block` and the gap since the previous one is at most `max_gap`.
    Greedy is optimal here because the addresses are sorted and the cost function is
    monotonic in block length, so there is nothing to gain by splitting earlier.

    Computing this instead of maintaining it by hand has a second benefit beyond the
    transaction count: adding a register to the map cannot leave it outside every
    block, which is a bug that reads as "that sensor is always unavailable".
    """
    wanted = sorted(set(addresses))
    if not wanted:
        return ()

    blocks: list[ReadBlock] = []
    start = previous = wanted[0]
    for address in wanted[1:]:
        gap = address - previous - 1
        length = address - start + 1
        if gap > max_gap or length > max_block:
            blocks.append(ReadBlock(start, previous - start + 1))
            start = address
        previous = address
    blocks.append(ReadBlock(start, previous - start + 1))
    return tuple(blocks)


READ_REGISTERS: Final[tuple[ReadRegister, ...]] = (
    ReadRegister(
        "machine_state",
        200,
        icon="mdi:heat-pump",
        state_class=None,
        sentinel=False,
    ),
    ReadRegister(
        "water_inlet",
        400,
        0.1,
        UnitOfTemperature.CELSIUS,
        "temperature",
        icon="mdi:import",
        suggested_display_precision=1,
    ),
    ReadRegister(
        "water_outlet",
        401,
        0.1,
        UnitOfTemperature.CELSIUS,
        "temperature",
        icon="mdi:export",
        suggested_display_precision=1,
    ),
    ReadRegister(
        "dhw_tank",
        405,
        0.1,
        UnitOfTemperature.CELSIUS,
        "temperature",
        icon="mdi:water-boiler",
        suggested_display_precision=1,
    ),
    ReadRegister(
        "high_pressure",
        406,
        0.01,
        UnitOfPressure.BAR,
        "pressure",
        icon="mdi:gauge-full",
        suggested_display_precision=2,
    ),
    ReadRegister(
        "low_pressure",
        414,
        0.01,
        UnitOfPressure.BAR,
        "pressure",
        icon="mdi:gauge-low",
        suggested_display_precision=2,
    ),
    ReadRegister(
        "suction_temp",
        422,
        0.1,
        UnitOfTemperature.CELSIUS,
        "temperature",
        icon="mdi:thermometer-low",
        enabled_default=False,
        diagnostic=True,
        suggested_display_precision=1,
    ),
    ReadRegister(
        "outdoor",
        428,
        0.1,
        UnitOfTemperature.CELSIUS,
        "temperature",
        icon="mdi:thermometer",
        suggested_display_precision=1,
    ),
    ReadRegister(
        "discharge_temp",
        433,
        0.1,
        UnitOfTemperature.CELSIUS,
        "temperature",
        icon="mdi:thermometer-high",
        enabled_default=False,
        diagnostic=True,
        suggested_display_precision=1,
    ),
    # Flow meter is optional hardware (needs parameter H22=45). Where it is not
    # fitted the register answers 32766, so the sentinel filter leaves the
    # entity unavailable. Disabled by default so nobody is offered a
    # measurement that does not exist.
    ReadRegister(
        "flow_rate",
        444,
        1.0,
        UnitOfVolumeFlowRate.LITERS_PER_MINUTE,
        None,
        icon="mdi:water-pump",
        enabled_default=False,
    ),
    ReadRegister(
        "evaporation_temp",
        253,
        0.1,
        UnitOfTemperature.CELSIUS,
        "temperature",
        icon="mdi:snowflake-thermometer",
        enabled_default=False,
        diagnostic=True,
        suggested_display_precision=1,
    ),
    ReadRegister(
        "condensation_temp",
        254,
        0.1,
        UnitOfTemperature.CELSIUS,
        "temperature",
        icon="mdi:sun-thermometer",
        enabled_default=False,
        diagnostic=True,
        suggested_display_precision=1,
    ),
    ReadRegister(
        "compressor_hours",
        305,
        1.0,
        UnitOfTime.HOURS,
        "duration",
        state_class="total_increasing",
        icon="mdi:timer-cog",
        diagnostic=True,
    ),
    ReadRegister(
        "fan",
        7000,
        0.1,
        PERCENTAGE,
        None,
        icon="mdi:fan",
        suggested_display_precision=0,
    ),
    ReadRegister(
        "circulator",
        7001,
        0.1,
        PERCENTAGE,
        None,
        icon="mdi:pump",
        suggested_display_precision=0,
    ),
    ReadRegister(
        "cooling_setpoint",
        7203,
        0.1,
        UnitOfTemperature.CELSIUS,
        "temperature",
        state_class=None,
        icon="mdi:snowflake",
        enabled_default=False,
        suggested_display_precision=1,
    ),
    ReadRegister(
        "heating_setpoint",
        7204,
        0.1,
        UnitOfTemperature.CELSIUS,
        "temperature",
        state_class=None,
        icon="mdi:fire",
        enabled_default=False,
        suggested_display_precision=1,
    ),
    ReadRegister(
        "dhw_setpoint",
        7205,
        0.1,
        UnitOfTemperature.CELSIUS,
        "temperature",
        state_class=None,
        icon="mdi:water-thermometer",
        enabled_default=False,
        suggested_display_precision=1,
    ),
)

#: machine state, read (200) and written (7200). Also the register the config
#: flow probes, because every controller in the family exposes it and reading it
#: has no side effects.
STATE_REGISTER: Final = 200

#: first of the three alarm words; decoded in `alarms.py`
ALARM_FIRST_REGISTER: Final = 950
ALARM_REGISTERS: Final = (950, 951, 952)

#: register 7214: bit 13 = defrost requested, bit 14 = defrost running
DEFROST_REGISTER: Final = 7214
DEFROST_BIT_REQUESTED: Final = 13
DEFROST_BIT_RUNNING: Final = 14

#: register 7216: bit 5 = anti-legionella cycle running, bit 6 = last one failed
LEGIONELLA_REGISTER: Final = 7216
LEGIONELLA_BIT_RUNNING: Final = 5
LEGIONELLA_BIT_FAILED: Final = 6

#: register 7202 read back: which remote calls the controller currently sees
COMMAND_REGISTER: Final = 7202

# Derived, not a register: water ΔT = outlet - inlet. The manufacturer's design
# figure is 5 K with 8 K as the tolerated maximum; sustained values above that
# mean a flow restriction, which is exactly the fault that started this project.
DELTA_T_NOMINAL: Final = 5.0
DELTA_T_MAX: Final = 8.0

# Derived thermal power, kW = flow(l/min) / 60 * 4.186 * ΔT. Only computed when
# a real flow reading exists, never from a sentinel.
WATER_HEAT_CAPACITY: Final = 4.186  # kJ/(kg·K)


# Registers the coordinator needs that are not entity-backed: status bitmaps and
# the command word read back. Listing them here rather than in the coordinator is
# what lets the block planner see the full picture.
STATUS_REGISTERS: Final = (
    *ALARM_REGISTERS,
    COMMAND_REGISTER,
    DEFROST_REGISTER,
    LEGIONELLA_REGISTER,
)

#: Every address a poll cycle must fetch.
REQUIRED_ADDRESSES: Final = (
    *(register.address for register in READ_REGISTERS),
    *STATUS_REGISTERS,
)

#: The read plan, computed once at import. Seven transactions for twenty-four
#: registers spread over 200 to 7216.
READ_BLOCKS: Final[tuple[ReadBlock, ...]] = plan_blocks(REQUIRED_ADDRESSES)
