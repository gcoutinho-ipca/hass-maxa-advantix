"""Read-only sensors, one per declared register plus the derived values.

The derived ones are the point of the integration. Anyone can read register 401;
knowing that outlet minus inlet above 8 K means a flow restriction, and putting
the manufacturer's limits in the attributes next to the number, is the part that
turns telemetry into a diagnosis.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MaxaConfigEntry
from .const import (
    KEY_ACTIVE_ALARMS,
    KEY_ALARM_COUNT,
    KEY_BUS,
    KEY_DELTA_T,
    KEY_MACHINE_STATE,
    KEY_MODE_SWITCHES,
    KEY_SWITCHES_PER_HOUR,
    MACHINE_STATES,
)
from .coordinator import MaxaCoordinator
from .entity import MaxaEntity
from .health import MODE_THRASHING_THRESHOLD
from .registers import DELTA_T_MAX, DELTA_T_NOMINAL, READ_REGISTERS, ReadRegister


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MaxaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One sensor per declared register, plus state and the derived values."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        MaxaStateSensor(coordinator),
        MaxaDeltaTSensor(coordinator),
        MaxaThermalPowerSensor(coordinator),
        MaxaActiveAlarmsSensor(coordinator),
        MaxaModeSwitchSensor(coordinator),
        MaxaLastModeChangeSensor(coordinator),
        MaxaBusErrorRateSensor(coordinator),
    ]
    entities.extend(
        MaxaRegisterSensor(coordinator, register)
        for register in READ_REGISTERS
        if register.key != KEY_MACHINE_STATE  # has a dedicated enum entity
    )
    async_add_entities(entities)


class MaxaRegisterSensor(MaxaEntity, SensorEntity):
    """Generic sensor built from a register definition."""

    def __init__(self, coordinator: MaxaCoordinator, register: ReadRegister) -> None:
        super().__init__(coordinator, register.key)
        self._register = register
        self._attr_translation_key = register.key
        self._attr_native_unit_of_measurement = register.unit
        self._attr_icon = register.icon
        self._attr_entity_registry_enabled_default = register.enabled_default
        self._attr_suggested_display_precision = register.suggested_display_precision
        if register.device_class:
            self._attr_device_class = SensorDeviceClass(register.device_class)
        if register.state_class:
            self._attr_state_class = SensorStateClass(register.state_class)
        if register.diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        """Unavailable when the probe did not answer, or answered a sentinel.

        `unknown` would be the wrong state here. It invites you to wait for a
        value, and there is nothing to wait for: the probe is not fitted, or the
        controller has marked it faulty.
        """
        return super().available and self.coordinator.data.get(self._register.key) is not None

    @property
    def native_value(self) -> float | int | None:
        return self.coordinator.data.get(self._register.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the source register: essential when reporting a bad reading."""
        return {"register": self._register.address}


class MaxaStateSensor(MaxaEntity, SensorEntity):
    """Machine state (register 200) as a translatable enum."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(MACHINE_STATES.values())
    _attr_translation_key = "machine_state"
    _attr_icon = "mdi:heat-pump"

    def __init__(self, coordinator: MaxaCoordinator) -> None:
        super().__init__(coordinator, KEY_MACHINE_STATE)

    @property
    def native_value(self) -> str | None:
        raw = self.coordinator.data.get(KEY_MACHINE_STATE)
        return MACHINE_STATES.get(raw) if raw is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"raw": self.coordinator.data.get(KEY_MACHINE_STATE), "register": 200}


class MaxaDeltaTSensor(MaxaEntity, SensorEntity):
    """Water ΔT (outlet - inlet). Design figure 5 K, tolerated maximum 8 K."""

    _attr_native_unit_of_measurement = "K"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:delta"
    _attr_translation_key = "delta_t"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: MaxaCoordinator) -> None:
        super().__init__(coordinator, KEY_DELTA_T)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get(KEY_DELTA_T)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        delta_t = self.coordinator.data.get(KEY_DELTA_T)
        return {
            "nominal": DELTA_T_NOMINAL,
            "tolerated_maximum": DELTA_T_MAX,
            "flow_restricted": delta_t is not None and delta_t > DELTA_T_MAX,
        }


class MaxaThermalPowerSensor(MaxaEntity, SensorEntity):
    """Thermal power, computed only when a real flow reading exists.

    Left unavailable rather than guessed when the optional flow meter is not
    fitted. Publishing a number derived from a sentinel is worse than publishing
    nothing: it looks like data.
    """

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "thermal_power"
    _attr_icon = "mdi:heat-wave"
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: MaxaCoordinator) -> None:
        super().__init__(coordinator, "thermal_power")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get("thermal_power")


class MaxaActiveAlarmsSensor(MaxaEntity, SensorEntity):
    """Active alarm codes as text; the decoded list goes in the attributes."""

    _attr_translation_key = "active_alarms"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator: MaxaCoordinator) -> None:
        super().__init__(coordinator, KEY_ACTIVE_ALARMS)

    @property
    def native_value(self) -> str:
        active = self.coordinator.data.get(KEY_ACTIVE_ALARMS, [])
        if not active:
            return "none"
        return ",".join(str(alarm["code"]) for alarm in active)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        active = self.coordinator.data.get(KEY_ACTIVE_ALARMS, [])
        return {
            "count": self.coordinator.data.get(KEY_ALARM_COUNT, 0),
            "alarms": [f"{a['code']} {a['description']}" for a in active],
            "registers": self.coordinator.data.get("alarm_registers", []),
        }


class MaxaModeSwitchSensor(MaxaEntity, SensorEntity):
    """Mode switches since startup: the metric that exposed the original fault.

    A three-way valve needs about a minute to travel. A machine switching modes
    hundreds of times a day is a machine whose valve never finishes moving, and
    the count makes that visible long before the alarms do.
    """

    _attr_translation_key = "mode_switches"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:swap-horizontal"

    def __init__(self, coordinator: MaxaCoordinator) -> None:
        super().__init__(coordinator, KEY_MODE_SWITCHES)

    @property
    def native_value(self) -> int:
        return self.coordinator.data.get(KEY_MODE_SWITCHES, 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The rate, which is what actually distinguishes normal from thrashing.

        A total since startup grows forever and says nothing on its own. The
        per-hour figure is the one worth putting on a dashboard, and the one the
        installation health check acts on.
        """
        return {
            "per_hour": self.coordinator.data.get(KEY_SWITCHES_PER_HOUR, 0),
            "thrashing_threshold": MODE_THRASHING_THRESHOLD,
        }


class MaxaLastModeChangeSensor(MaxaEntity, SensorEntity):
    """When the machine last changed mode. Pairs with the switch counter."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_mode_change"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:clock-outline"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: MaxaCoordinator) -> None:
        super().__init__(coordinator, "last_mode_change")

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.get("last_mode_change")


class MaxaBusErrorRateSensor(MaxaEntity, SensorEntity):
    """Modbus error rate, in %. Catches a gateway that is degrading."""

    _attr_translation_key = "bus_error_rate"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:lan-connect"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: MaxaCoordinator) -> None:
        super().__init__(coordinator, "bus_error_rate")

    @property
    def native_value(self) -> float:
        return self.coordinator.data.get(KEY_BUS, {}).get("error_rate", 0.0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self.coordinator.data.get(KEY_BUS, {}))
