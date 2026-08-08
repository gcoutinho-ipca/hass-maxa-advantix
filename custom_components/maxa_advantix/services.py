"""Services, for scripts and automations.

Registered once for the integration rather than per entry, and targeted with a
`config_entry_id` so a house with two heat pumps can address either. With a
single machine configured the parameter can be omitted.

`read_register` deserves a note: it exists so that owners of other controller
generations can map their own machine and report back what they find, without
installing a second Modbus integration alongside this one and creating a second
master on the bus. It reads only: there is deliberately no `write_register`
counterpart, because an unvalidated write is exactly what the manufacturer warns
against.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, MACHINE_STATE_VALUES, MACHINE_STATES
from .coordinator import MaxaCoordinator
from .modbus_client import ModbusError
from .safe_write import R_SET_DHW, SETPOINT_RANGES

SERVICE_SET_MODE = "set_mode"
SERVICE_SET_DHW_SETPOINT = "set_dhw_setpoint"
SERVICE_START_LEGIONELLA = "start_legionella"
SERVICE_RELEASE_CONTROL = "release_control"
SERVICE_READ_REGISTER = "read_register"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"

_DHW_LOW, _DHW_HIGH, _ = SETPOINT_RANGES[R_SET_DHW]

_TARGET = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}

_SCHEMA_SET_MODE = vol.Schema(
    {**_TARGET, vol.Required("mode"): vol.In(list(MACHINE_STATES.values()))}
)
_SCHEMA_SET_DHW = vol.Schema(
    {
        **_TARGET,
        vol.Required("temperature"): vol.All(
            vol.Coerce(float), vol.Range(min=_DHW_LOW / 10, max=_DHW_HIGH / 10)
        ),
    }
)
_SCHEMA_TARGET_ONLY = vol.Schema(_TARGET)
_SCHEMA_READ = vol.Schema(
    {
        **_TARGET,
        vol.Required("address"): vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
        vol.Optional("count", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=32)),
    }
)


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> MaxaCoordinator:
    """Find the coordinator this call is aimed at."""
    entries = list(hass.config_entries.async_entries(DOMAIN))
    requested = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if requested:
        target = next((e for e in entries if e.entry_id == requested), None)
    elif len(entries) == 1:
        target = entries[0]
    elif not entries:
        raise ServiceValidationError("No MAXA heat pump is configured")
    else:
        raise ServiceValidationError(
            "More than one heat pump is configured; pass config_entry_id"
        )
    if target is None or getattr(target, "runtime_data", None) is None:
        raise ServiceValidationError("Heat pump not found, or not loaded")
    return target.runtime_data


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register every service once. Safe to call on each entry setup."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_MODE):
        return

    async def _set_mode(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        await coordinator.async_set_state(MACHINE_STATE_VALUES[call.data["mode"]])

    async def _set_dhw_setpoint(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        await coordinator.async_set_setpoint(R_SET_DHW, round(call.data["temperature"] * 10))

    async def _start_legionella(call: ServiceCall) -> None:
        await _coordinator(hass, call).async_start_legionella()

    async def _release_control(call: ServiceCall) -> None:
        await _coordinator(hass, call).async_release()

    async def _read_register(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call)
        address: int = call.data["address"]
        count: int = call.data["count"]
        try:
            values = await hass.async_add_executor_job(
                coordinator.client.read_holding, address, count
            )
        except ModbusError as err:
            raise ServiceValidationError(f"Read of register {address} failed: {err}") from err
        result: dict[str, Any] = {
            "address": address,
            "count": count,
            "values": values,
            # Same words unsigned: alarm and status registers use bit 15, so the
            # signed view of those is meaningless.
            "unsigned": [v & 0xFFFF for v in values],
        }
        return result

    hass.services.async_register(DOMAIN, SERVICE_SET_MODE, _set_mode, schema=_SCHEMA_SET_MODE)
    hass.services.async_register(
        DOMAIN, SERVICE_SET_DHW_SETPOINT, _set_dhw_setpoint, schema=_SCHEMA_SET_DHW
    )
    hass.services.async_register(
        DOMAIN, SERVICE_START_LEGIONELLA, _start_legionella, schema=_SCHEMA_TARGET_ONLY
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RELEASE_CONTROL, _release_control, schema=_SCHEMA_TARGET_ONLY
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_READ_REGISTER,
        _read_register,
        schema=_SCHEMA_READ,
        supports_response=SupportsResponse.ONLY,
    )
