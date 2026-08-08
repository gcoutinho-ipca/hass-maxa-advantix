"""Setpoints as `number` entities, bounded by the manufacturer's ranges.

The `native_min/max` values mirror the documented ranges, so the slider cannot
even reach an illegal value. The validation in `safe_write` is the second line,
for everything that does not come through the UI: services, scripts, REST calls
and other people's automations.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MaxaConfigEntry
from .coordinator import MaxaCoordinator
from .entity import MaxaEntity
from .safe_write import (
    R_SET_COOLING,
    R_SET_DHW,
    R_SET_DHW_HEATER,
    R_SET_HEATING,
    SETPOINT_RANGES,
)


@dataclass(frozen=True)
class SetpointDef:
    """One writable setpoint and where to read its current value back."""

    key: str
    address: int
    #: coordinator data key holding the value read back, empty if not polled
    data_key: str
    icon: str
    enabled_default: bool = True
    diagnostic: bool = False


SETPOINTS: tuple[SetpointDef, ...] = (
    SetpointDef("cooling_setpoint", R_SET_COOLING, "cooling_setpoint", "mdi:snowflake"),
    SetpointDef("heating_setpoint", R_SET_HEATING, "heating_setpoint", "mdi:fire"),
    SetpointDef("dhw_setpoint", R_SET_DHW, "dhw_setpoint", "mdi:water-thermometer"),
    # The preheater setpoint (7208) is not part of the polled map: it only exists
    # on installations with a DHW preparation tank, and reading it everywhere
    # would spend a bus transaction for nothing. Write-only, disabled by default.
    SetpointDef(
        "dhw_heater_setpoint",
        R_SET_DHW_HEATER,
        "",
        "mdi:water-boiler",
        enabled_default=False,
        diagnostic=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MaxaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(MaxaSetpointNumber(coordinator, d) for d in SETPOINTS)


class MaxaSetpointNumber(MaxaEntity, NumberEntity):
    """A temperature setpoint written through the validated write layer."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: MaxaCoordinator, definition: SetpointDef) -> None:
        super().__init__(coordinator, definition.key)
        self._definition = definition
        low, high, _ = SETPOINT_RANGES[definition.address]
        self._attr_translation_key = definition.key
        self._attr_icon = definition.icon
        self._attr_native_min_value = low / 10
        self._attr_native_max_value = high / 10
        self._attr_entity_registry_enabled_default = definition.enabled_default
        if definition.diagnostic:
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def native_value(self) -> float | None:
        if not self._definition.data_key:
            return None  # not polled; write-only
        return self.coordinator.data.get(self._definition.data_key)

    async def async_set_native_value(self, value: float) -> None:
        # raw units are °C x 10
        await self.coordinator.async_set_setpoint(self._definition.address, round(value * 10))
