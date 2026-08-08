"""Remote calls as switches (register 7202).

The distinction that trips people up: the *state* selects the mode, the *call* is
what makes the machine work. A pump set to `heating` with no ambient call is
correctly configured and completely idle.

`climate` and `water_heater` raise and drop these calls for you. These switches
are here for the automation that wants to hold a call across a mode change, or to
diagnose a machine that looks configured but never starts.

Both calls live in the same register, so each switch reads the other's current
value and rewrites both, because writing one alone would clear its neighbour.
"""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MaxaConfigEntry
from .const import KEY_COMMAND
from .coordinator import MaxaCoordinator
from .entity import MaxaEntity
from .safe_write import CMD_AMBIENT, CMD_DHW


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MaxaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            MaxaCallSwitch(coordinator, "ambient_call", CMD_AMBIENT, "mdi:home-thermometer"),
            MaxaCallSwitch(coordinator, "dhw_call", CMD_DHW, "mdi:water-boiler"),
        ]
    )


class MaxaCallSwitch(MaxaEntity, SwitchEntity):
    """One remote call bit."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: MaxaCoordinator, key: str, bit: int, icon: str
    ) -> None:
        super().__init__(coordinator, key)
        self._bit = bit
        self._attr_translation_key = key
        self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get(KEY_COMMAND, 0) & self._bit)

    async def _apply(self, turn_on: bool) -> None:
        ambient = self.coordinator.ambient_call
        dhw = self.coordinator.dhw_call
        if self._bit == CMD_AMBIENT:
            ambient = turn_on
        else:
            dhw = turn_on
        await self.coordinator.async_set_calls(ambient, dhw)

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._apply(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._apply(False)
