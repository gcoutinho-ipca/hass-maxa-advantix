"""Domestic hot water as a native `water_heater` entity.

Mirror image of `climate.py`: this entity owns the DHW half of the state word and
preserves the conditioning half. Turning hot water off must never stop the
heating, and vice versa.

The operation list has two entries rather than the usual four because that is
what the machine has. `heat_pump` means the DHW mode is selected and the remote
call is raised; `off` means it is not. There is no electric or high-demand mode
inside the controller. An immersion heater, if you have one, is a separate
switch in Home Assistant and belongs in an automation, not in this entity.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.water_heater import (
    STATE_HEAT_PUMP,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, STATE_OFF, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MaxaConfigEntry
from .const import KEY_MACHINE_STATE
from .coordinator import MaxaCoordinator
from .entity import MaxaEntity
from .safe_write import R_SET_DHW, SETPOINT_RANGES
from .states import decompose


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MaxaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the single water_heater entity for domestic hot water."""
    async_add_entities([MaxaWaterHeater(entry.runtime_data)])


class MaxaWaterHeater(MaxaEntity, WaterHeaterEntity):
    """Hot-water tank driven by the heat pump."""

    _attr_translation_key = "dhw"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_operation_list = [STATE_OFF, STATE_HEAT_PUMP]
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
        | WaterHeaterEntityFeature.ON_OFF
    )
    _attr_icon = "mdi:water-boiler"

    def __init__(self, coordinator: MaxaCoordinator) -> None:
        super().__init__(coordinator, "water_heater")
        low, high, _ = SETPOINT_RANGES[R_SET_DHW]
        self._attr_min_temp = low / 10
        self._attr_max_temp = high / 10

    @property
    def _dhw_selected(self) -> bool:
        _, dhw = decompose(self.coordinator.data.get(KEY_MACHINE_STATE))
        return dhw

    @property
    def current_operation(self) -> str:
        return STATE_HEAT_PUMP if self._dhw_selected else STATE_OFF

    @property
    def current_temperature(self) -> float | None:
        return self.coordinator.data.get("dhw_tank")

    @property
    def target_temperature(self) -> float | None:
        return self.coordinator.data.get("dhw_setpoint")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "dhw_call": self.coordinator.dhw_call,
            "legionella_running": self.coordinator.data.get("legionella_running"),
            "legionella_failed": self.coordinator.data.get("legionella_failed"),
        }

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        await self.coordinator.async_set_dhw_enabled(operation_mode == STATE_HEAT_PUMP)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dhw_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dhw_enabled(False)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.coordinator.async_set_setpoint(R_SET_DHW, round(float(temperature) * 10))
