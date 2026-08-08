"""Shared entity base: ties every entity to the coordinator and one device."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HOST, CONF_MODEL, DEFAULT_MODEL, DOMAIN, MANUFACTURER
from .coordinator import MaxaCoordinator


class MaxaEntity(CoordinatorEntity[MaxaCoordinator]):
    """Base class for every MAXA entity.

    One device per config entry, so a house with two heat pumps gets two devices
    and the entity names stay short (`has_entity_name` puts the device name in
    front automatically).
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: MaxaCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.entry
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=entry.data.get(CONF_MODEL, DEFAULT_MODEL),
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )

    @property
    def available(self) -> bool:
        """Unavailable when the last poll failed, or when there is no data yet."""
        return super().available and self.coordinator.data is not None
