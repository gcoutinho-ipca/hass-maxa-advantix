"""Space-conditioning side as a native `climate` entity.

Register 200 packs conditioning and hot water into one enum, so this entity
changes only its own half of the word and leaves the DHW half alone (see
`states.py`). Without that rule, turning the heating off would silently disable
hot water too: the kind of bug that gets discovered on a cold morning.

Two design choices worth stating, because both are visible to the user:

* **`current_temperature` is the outlet water, not room air.** This is a
  water-to-water/air-to-water machine with no room sensor of its own. Reporting
  the water it actually controls is honest; inventing a room temperature is not.
  Pair it with a room thermostat in Home Assistant if you want a room setpoint.
* **The target follows the mode.** The controller keeps separate cooling and
  heating setpoints (7203 / 7204) and honours whichever matches the current
  mode, so the entity's target and its limits change with the mode.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MaxaConfigEntry
from .const import KEY_MACHINE_STATE
from .coordinator import MaxaCoordinator
from .entity import MaxaEntity
from .safe_write import R_SET_COOLING, R_SET_HEATING, SETPOINT_RANGES
from .states import Conditioning, decompose

#: HVAC mode <-> the conditioning half of the machine state
_MODE_TO_CONDITIONING: dict[HVACMode, Conditioning] = {
    HVACMode.OFF: "off",
    HVACMode.COOL: "cool",
    HVACMode.HEAT: "heat",
}
_CONDITIONING_TO_MODE: dict[Conditioning, HVACMode] = {
    v: k for k, v in _MODE_TO_CONDITIONING.items()
}

#: which setpoint register and data key each mode uses
_SETPOINT_BY_MODE: dict[HVACMode, tuple[int, str]] = {
    HVACMode.COOL: (R_SET_COOLING, "cooling_setpoint"),
    HVACMode.HEAT: (R_SET_HEATING, "heating_setpoint"),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MaxaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([MaxaClimate(entry.runtime_data)])


class MaxaClimate(MaxaEntity, ClimateEntity):
    """Heating / cooling of the installation side."""

    _attr_translation_key = "conditioning"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_target_temperature_step = 0.5
    _attr_icon = "mdi:home-thermometer"

    def __init__(self, coordinator: MaxaCoordinator) -> None:
        super().__init__(coordinator, "climate")

    @property
    def hvac_mode(self) -> HVACMode:
        conditioning, _ = decompose(self.coordinator.data.get(KEY_MACHINE_STATE))
        return _CONDITIONING_TO_MODE[conditioning]

    @property
    def hvac_action(self) -> HVACAction:
        """What the machine is doing right now, as opposed to what it is set to.

        The mode alone is not enough: a machine in `heat` with no remote call, or
        with the circulator stopped, is idle. Reporting that difference is what
        makes the thermostat card trustworthy.
        """
        mode = self.hvac_mode
        if mode == HVACMode.OFF:
            return HVACAction.OFF
        if not self.coordinator.ambient_call:
            return HVACAction.IDLE
        if self.coordinator.data.get("defrost_running"):
            return HVACAction.DEFROSTING
        circulator = self.coordinator.data.get("circulator")
        if circulator is not None and circulator <= 0:
            return HVACAction.IDLE
        return HVACAction.COOLING if mode == HVACMode.COOL else HVACAction.HEATING

    @property
    def current_temperature(self) -> float | None:
        """Outlet water temperature: what this machine actually regulates."""
        return self.coordinator.data.get("water_outlet")

    @property
    def target_temperature(self) -> float | None:
        entry = _SETPOINT_BY_MODE.get(self.hvac_mode)
        return self.coordinator.data.get(entry[1]) if entry else None

    @property
    def min_temp(self) -> float:
        return self._range()[0]

    @property
    def max_temp(self) -> float:
        return self._range()[1]

    def _range(self) -> tuple[float, float]:
        """Manufacturer's range for the setpoint the current mode uses."""
        entry = _SETPOINT_BY_MODE.get(self.hvac_mode)
        if entry is None:
            # OFF has no active setpoint. Span both modes so the card still has
            # sensible bounds instead of collapsing to a single value.
            low = SETPOINT_RANGES[R_SET_COOLING][0]
            high = SETPOINT_RANGES[R_SET_HEATING][1]
            return low / 10, high / 10
        low, high, _ = SETPOINT_RANGES[entry[0]]
        return low / 10, high / 10

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "water_inlet": self.coordinator.data.get("water_inlet"),
            "outdoor": self.coordinator.data.get("outdoor"),
            "ambient_call": self.coordinator.ambient_call,
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self.coordinator.async_set_conditioning(_MODE_TO_CONDITIONING[hvac_mode])

    async def async_turn_on(self) -> None:
        """Resume conditioning. Heating is the safer default in a cold house."""
        await self.coordinator.async_set_conditioning("heat")

    async def async_turn_off(self) -> None:
        await self.coordinator.async_set_conditioning("off")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        entry = _SETPOINT_BY_MODE.get(self.hvac_mode)
        if entry is None:
            raise ServiceValidationError(
                "Select cooling or heating before setting a target temperature"
            )
        await self.coordinator.async_set_setpoint(entry[0], round(float(temperature) * 10))
