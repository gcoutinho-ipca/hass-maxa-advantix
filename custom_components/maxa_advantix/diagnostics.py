"""Config entry diagnostics: the "Download diagnostics" button.

One file with everything needed to understand a problem remotely: the last full
reading, the decoded alarms, and the bus health counters.

The gateway address is redacted, and the `last_error` string with it, because that
string can contain the address too. There are no credentials anywhere in this
integration, so nothing here is a secret in the usual sense. But a diagnostics
download gets attached to public issues, and an internal address next to a device
inventory is more of someone's network than they meant to publish.

What stays is what makes a report answerable: the port, the Modbus id, the
controller model, the blocks being polled and every reading. None of it says where
the machine lives.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import MaxaConfigEntry
from .const import (
    CONF_HOST,
    CONF_MODEL,
    CONF_PORT,
    CONF_SLAVE,
    KEY_ACTIVE_ALARMS,
    KEY_BUS,
    KEY_MODE_SWITCHES,
)
from .registers import READ_BLOCKS

TO_REDACT = {CONF_HOST, "last_error"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MaxaConfigEntry
) -> dict[str, Any]:
    """Build the diagnostics payload for one heat pump."""
    coordinator = entry.runtime_data
    reading = dict(coordinator.data or {})
    payload = {
        "config": {
            CONF_HOST: entry.data.get(CONF_HOST),
            CONF_PORT: entry.data.get(CONF_PORT),
            CONF_SLAVE: entry.data.get(CONF_SLAVE),
            CONF_MODEL: entry.data.get(CONF_MODEL),
            "scan_interval": coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None,
        },
        "blocks_polled": [[block.start, block.count] for block in READ_BLOCKS],
        "last_update_success": coordinator.last_update_success,
        "bus": reading.pop(KEY_BUS, {}),
        "active_alarms": reading.pop(KEY_ACTIVE_ALARMS, []),
        "mode_switches": reading.get(KEY_MODE_SWITCHES),
        "reading": reading,
    }
    return async_redact_data(payload, TO_REDACT)
