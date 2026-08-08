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

from dataclasses import dataclass
from typing import Final

from homeassistant.const import (
    PERCENTAGE,
    UnitOfPower,
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
    #: which contiguous read block this register belongs to
    block: str = "misc"
    #: created but disabled in the entity registry (optional hardware)
    enabled_default: bool = True
    #: shown under the device's diagnostics section rather than as a control
    diagnostic: bool = False
    suggested_display_precision: int | None = None


# Contiguous blocks: the coordinator reads each block in a single Modbus
# transaction and then distributes the values. At 9600 baud a transaction costs
# 15-40 ms of line time, so 20 individual reads cost noticeably more than the
# 12 block reads below. The bus is the scarce resource, not CPU.
BLOCKS: Final[dict[str, tuple[int, int]]] = {
    "state": (200, 1),
    "command": (7202, 1),  # active call bits (space / DHW)
    "cooling_circuit": (253, 2),  # evaporation / condensation
    "compressor": (305, 1),
    "water": (400, 15),  # 400..414 inlet, outlet, DHW tank, pressures
    "refrigerant": (422, 14),  # 422..435 suction, outdoor, discharge
    "flow": (444, 1),
    "actuators": (7000, 2),  # fan, circulator
    "setpoints": (7203, 3),  # cooling, heating, DHW
    "defrost": (7214, 1),
    "legionella": (7216, 1),
    "alarms": (950, 3),  # 950 / 951 / 952
}

READ_REGISTERS: Final[tuple[ReadRegister, ...]] = (
    ReadRegister(
        "machine_state",
        200,
        icon="mdi:heat-pump",
        state_class=None,
        sentinel=False,
        block="state",
    ),
    ReadRegister(
        "water_inlet",
        400,
        0.1,
        UnitOfTemperature.CELSIUS,
        "temperature",
        icon="mdi:import",
        block="water",
        suggested_display_precision=1,
    ),
    ReadRegister(
        "water_outlet",
        401,
        0.1,
        UnitOfTemperature.CELSIUS,
        "temperature",
        icon="mdi:export",
        block="water",
        suggested_display_precision=1,
    ),
    ReadRegister(
        "dhw_tank",
        405,
        0.1,
        UnitOfTemperature.CELSIUS,
        "temperature",
        icon="mdi:water-boiler",
        block="water",
        suggested_display_precision=1,
    ),
    ReadRegister(
        "high_pressure",
        406,
        0.01,
        UnitOfPressure.BAR,
        "pressure",
        icon="mdi:gauge-full",
        block="water",
        suggested_display_precision=2,
    ),
    ReadRegister(
        "low_pressure",
        414,
        0.01,
        UnitOfPressure.BAR,
        "pressure",
        icon="mdi:gauge-low",
        block="water",
        suggested_display_precision=2,
    ),
    ReadRegister(
        "suction_temp",
        422,
        0.1,
        UnitOfTemperature.CELSIUS,
        "temperature",
        icon="mdi:thermometer-low",
        block="refrigerant",
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
        block="refrigerant",
        suggested_display_precision=1,
    ),
    ReadRegister(
        "discharge_temp",
        433,
        0.1,
        UnitOfTemperature.CELSIUS,
        "temperature",
        icon="mdi:thermometer-high",
        block="refrigerant",
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
        block="flow",
        enabled_default=False,
    ),
    ReadRegister(
        "evaporation_temp",
        253,
        0.1,
        UnitOfTemperature.CELSIUS,
        "temperature",
        icon="mdi:snowflake-thermometer",
        block="cooling_circuit",
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
        block="cooling_circuit",
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
        block="compressor",
        diagnostic=True,
    ),
    ReadRegister(
        "fan",
        7000,
        0.1,
        PERCENTAGE,
        None,
        icon="mdi:fan",
        block="actuators",
        suggested_display_precision=0,
    ),
    ReadRegister(
        "circulator",
        7001,
        0.1,
        PERCENTAGE,
        None,
        icon="mdi:pump",
        block="actuators",
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
        block="setpoints",
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
        block="setpoints",
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
        block="setpoints",
        enabled_default=False,
        suggested_display_precision=1,
    ),
)

#: block holding the three alarm words; decoded in `alarms.py`
ALARM_BLOCK: Final = "alarms"
ALARM_FIRST_REGISTER: Final = 950

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

# Derived, not a register: water ΔT = outlet − inlet. The manufacturer's design
# figure is 5 K with 8 K as the tolerated maximum; sustained values above that
# mean a flow restriction, which is exactly the fault that started this project.
DELTA_T_NOMINAL: Final = 5.0
DELTA_T_MAX: Final = 8.0

# Derived thermal power, kW = flow(l/min) / 60 * 4.186 * ΔT. Only computed when
# a real flow reading exists, never from a sentinel.
THERMAL_POWER_UNIT: Final = UnitOfPower.KILO_WATT
WATER_HEAT_CAPACITY: Final = 4.186  # kJ/(kg·K)
