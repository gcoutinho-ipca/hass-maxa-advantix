"""Binary sensors: overall fault, flow adequacy, defrost, legionella, per-alarm.

The forty individual alarm flags are created but **disabled by default**. That is
deliberate: a disabled entity costs nothing (no state, no recorder rows), yet the
user who needs to automate on "E042 appeared" can enable exactly that one from
the device page instead of writing a template against a bitmask.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MaxaConfigEntry
from .alarms import ALARMS, AlarmDef, is_active
from .const import KEY_ACTIVE_ALARMS, KEY_ALARM_COUNT, KEY_ALARM_REGISTERS, KEY_DELTA_T
from .coordinator import MaxaCoordinator
from .entity import MaxaEntity
from .registers import DELTA_T_MAX


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MaxaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the problem sensor, the flow check, the flags and one entity per alarm."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        MaxaProblemBinarySensor(coordinator),
        MaxaFlowRestrictedBinarySensor(coordinator),
        MaxaFlagBinarySensor(
            coordinator, "defrost_running", "mdi:snowflake-melt", BinarySensorDeviceClass.RUNNING
        ),
        MaxaFlagBinarySensor(
            coordinator, "defrost_requested", "mdi:snowflake-alert", None, enabled=False
        ),
        MaxaFlagBinarySensor(
            coordinator, "legionella_running", "mdi:bacteria", BinarySensorDeviceClass.RUNNING
        ),
        MaxaFlagBinarySensor(
            coordinator,
            "legionella_failed",
            "mdi:bacteria-outline",
            BinarySensorDeviceClass.PROBLEM,
        ),
    ]
    entities.extend(MaxaAlarmBinarySensor(coordinator, alarm) for alarm in ALARMS)
    async_add_entities(entities)


class MaxaProblemBinarySensor(MaxaEntity, BinarySensorEntity):
    """On when any alarm bit is set, whatever it is."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "problem"
    _attr_icon = "mdi:alert-circle"

    def __init__(self, coordinator: MaxaCoordinator) -> None:
        super().__init__(coordinator, "problem")

    @property
    def is_on(self) -> bool:
        return any(self.coordinator.data.get(KEY_ALARM_REGISTERS, [0, 0, 0]))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        active = self.coordinator.data.get(KEY_ACTIVE_ALARMS, [])
        return {
            "registers": self.coordinator.data.get(KEY_ALARM_REGISTERS, [0, 0, 0]),
            "count": self.coordinator.data.get(KEY_ALARM_COUNT, 0),
            "codes": [f"{a['code']} {a['description']}" for a in active],
        }


class MaxaFlowRestrictedBinarySensor(MaxaEntity, BinarySensorEntity):
    """Problem when ΔT exceeds the tolerated maximum: the water is too slow.

    This fires long before the machine's own flow switch does. The flow switch is
    documented as not being watched during hot-water production, which is
    precisely when a restricted DHW branch shows up, so on some installations
    ΔT is the only warning there is.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "flow_restricted"
    _attr_icon = "mdi:water-alert"

    def __init__(self, coordinator: MaxaCoordinator) -> None:
        super().__init__(coordinator, "flow_restricted")

    @property
    def is_on(self) -> bool | None:
        delta_t = self.coordinator.data.get(KEY_DELTA_T)
        if delta_t is None:
            return None
        return delta_t > DELTA_T_MAX

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "delta_t": self.coordinator.data.get(KEY_DELTA_T),
            "tolerated_maximum": DELTA_T_MAX,
        }


class MaxaFlagBinarySensor(MaxaEntity, BinarySensorEntity):
    """A single boolean already decoded by the coordinator."""

    def __init__(
        self,
        coordinator: MaxaCoordinator,
        key: str,
        icon: str,
        device_class: BinarySensorDeviceClass | None = None,
        enabled: bool = True,
    ) -> None:
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._attr_icon = icon
        self._attr_device_class = device_class
        self._attr_entity_registry_enabled_default = enabled

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get(self._key))


class MaxaAlarmBinarySensor(MaxaEntity, BinarySensorEntity):
    """One decoded alarm flag. Disabled by default; enable the ones you need."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: MaxaCoordinator, alarm: AlarmDef) -> None:
        super().__init__(coordinator, alarm.key)
        self._alarm = alarm
        # Alarm names are the manufacturer's fault codes plus a short English
        # description. They are not translated: the code is what a technician
        # reads off the machine's own display, and it is the same everywhere.
        self._attr_name = f"{alarm.code} {alarm.description}"

    @property
    def is_on(self) -> bool:
        return is_active(self.coordinator.data.get(KEY_ALARM_REGISTERS), self._alarm)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "code": self._alarm.code,
            "register": self._alarm.register,
            "bit": self._alarm.bit,
        }
