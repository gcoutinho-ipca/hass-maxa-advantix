"""MAXA / Advantix heat pumps (i-HWAK family) over Modbus.

Local polling only: no cloud, no account, no outbound connection. The
integration talks to the controller through a Modbus-TCP gateway and is the
single master on that bus.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE,
    DEFAULT_SCAN_INTERVAL,
)
from .coordinator import MaxaCoordinator
from .modbus_client import ModbusTCPClient
from .services import async_register_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.WATER_HEATER,
]

type MaxaConfigEntry = ConfigEntry[MaxaCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's services once, independently of any entry."""
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MaxaConfigEntry) -> bool:
    """Set up one heat pump from a config entry."""
    client = ModbusTCPClient(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        slave=entry.data[CONF_SLAVE],
    )
    scan_interval = entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )
    coordinator = MaxaCoordinator(hass, entry, client, scan_interval)

    # Fail setup cleanly if the machine does not answer right now: a retry is
    # scheduled by Home Assistant, which is better than a device full of
    # unavailable entities.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    # Make sure the coordinator's delayed post-write refresh cannot outlive the
    # entry: removing the integration must leave no timer behind.
    entry.async_on_unload(coordinator.async_shutdown)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MaxaConfigEntry) -> bool:
    """Unload the entry and its platforms."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: MaxaConfigEntry) -> None:
    """Reload when options change, e.g. a new scan interval."""
    await hass.config_entries.async_reload(entry.entry_id)
