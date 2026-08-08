"""Action buttons: start the anti-legionella cycle, and hand control back."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MaxaConfigEntry
from .coordinator import MaxaCoordinator
from .entity import MaxaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MaxaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the anti-legionella and release-control buttons."""
    coordinator = entry.runtime_data
    async_add_entities([MaxaLegionellaButton(coordinator), MaxaReleaseButton(coordinator)])


class MaxaLegionellaButton(MaxaEntity, ButtonEntity):
    """Start the controller's own anti-legionella cycle.

    The machine runs and supervises the cycle itself, including its own high
    temperature limits. Starting it from here is safer than reproducing the
    thermal supervision in an automation.
    """

    _attr_translation_key = "start_legionella"
    _attr_icon = "mdi:bacteria"

    def __init__(self, coordinator: MaxaCoordinator) -> None:
        super().__init__(coordinator, "start_legionella")

    async def async_press(self) -> None:
        await self.coordinator.async_start_legionella()


class MaxaReleaseButton(MaxaEntity, ButtonEntity):
    """Clear the command, state and enable registers.

    The escape hatch. After this the controller is back on its own settings and
    its own panel, which is where you want it while you investigate something or
    let an installer work on the machine.
    """

    _attr_translation_key = "release_control"
    _attr_icon = "mdi:hand-back-left"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: MaxaCoordinator) -> None:
        super().__init__(coordinator, "release_control")

    async def async_press(self) -> None:
        await self.coordinator.async_release()
