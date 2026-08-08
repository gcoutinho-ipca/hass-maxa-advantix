"""MAXA / Advantix heat pumps (i-HWAK family) over Modbus.

Local polling only: no cloud, no account, no outbound connection. The
integration talks to the controller through a Modbus-TCP gateway and is the
single master on that bus.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_READ_ONLY,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE,
    DEFAULT_READ_ONLY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import MaxaCoordinator
from .modbus_client import ModbusTCPClient
from .services import async_register_services

#: Telemetry. Always set up.
PLATFORMS_READ: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
]

#: Control. Skipped entirely in read-only mode, so the entities do not exist
#: rather than existing and refusing.
PLATFORMS_WRITE: list[Platform] = [
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.WATER_HEATER,
]

type MaxaConfigEntry = ConfigEntry[MaxaCoordinator]

# There is no YAML configuration for this integration, and saying so explicitly
# matters. `async_setup` exists below to register the services, and without this
# schema Home Assistant would accept a `maxa_advantix:` block in
# `configuration.yaml` without validating it, leaving the user waiting for an
# effect that never arrives. With it, that mistake becomes a clear error.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _read_only(entry: MaxaConfigEntry) -> bool:
    """Whether this entry is configured for telemetry only.

    Options win over data, so the setting can be changed after setup without
    reconfiguring the connection.
    """
    return entry.options.get(
        CONF_READ_ONLY, entry.data.get(CONF_READ_ONLY, DEFAULT_READ_ONLY)
    )


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
    coordinator = MaxaCoordinator(
        hass, entry, client, scan_interval, read_only=_read_only(entry)
    )

    # Fail setup cleanly if the machine does not answer right now: a retry is
    # scheduled by Home Assistant, which is better than a device full of
    # unavailable entities.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # The list is remembered on the coordinator rather than recomputed at unload.
    # Changing the read-only option triggers a reload, and by then the option has
    # already changed, so recomputing would try to unload platforms that were
    # never set up and leave the ones that were.
    platforms = list(PLATFORMS_READ)
    if not coordinator.read_only:
        platforms += PLATFORMS_WRITE
    coordinator.platforms = platforms

    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    # Make sure the coordinator's delayed post-write refresh cannot outlive the
    # entry: removing the integration must leave no timer behind.
    entry.async_on_unload(coordinator.async_shutdown)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MaxaConfigEntry) -> bool:
    """Unload the entry and exactly the platforms that were set up."""
    coordinator = entry.runtime_data
    return await hass.config_entries.async_unload_platforms(entry, coordinator.platforms)


async def _async_update_listener(hass: HomeAssistant, entry: MaxaConfigEntry) -> None:
    """Reload when options change, e.g. the scan interval or read-only mode."""
    await hass.config_entries.async_reload(entry.entry_id)
