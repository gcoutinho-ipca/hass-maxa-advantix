"""Raw machine state as a `select`: the direct control over register 7200.

`climate` and `water_heater` cover the normal cases and are what most users
should touch. This entity exists for the case they cannot express: setting the
combined state in a single write, which is what you want when switching between
"heating + hot water" and "cooling + hot water" without passing through an
intermediate state the three-way valve would have to chase.

If the machine refuses an option (a dry-contact input forcing cooling will do
that), the next poll shows the state it actually took. The UI does not lie about
what it asked for.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MaxaConfigEntry
from .const import KEY_MACHINE_STATE, MACHINE_STATE_VALUES, MACHINE_STATES
from .coordinator import MaxaCoordinator
from .entity import MaxaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MaxaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the raw machine-state select."""
    async_add_entities([MaxaStateSelect(entry.runtime_data)])


class MaxaStateSelect(MaxaEntity, SelectEntity):
    """The six values register 7200 accepts."""

    _attr_translation_key = "machine_state"
    _attr_options = list(MACHINE_STATES.values())
    _attr_icon = "mdi:state-machine"

    def __init__(self, coordinator: MaxaCoordinator) -> None:
        super().__init__(coordinator, "state_select")

    @property
    def current_option(self) -> str | None:
        raw = self.coordinator.data.get(KEY_MACHINE_STATE)
        return MACHINE_STATES.get(raw) if raw is not None else None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_state(MACHINE_STATE_VALUES[option])
