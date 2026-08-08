"""UI configuration: gateway address, Modbus id, controller model, poll rate."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_HOST,
    CONF_MODEL,
    CONF_PORT,
    CONF_READ_ONLY,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE,
    DEFAULT_MODEL,
    DEFAULT_PORT,
    DEFAULT_READ_ONLY,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SLAVE,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    MODELS,
)
from .modbus_client import ModbusError, ModbusTCPClient
from .registers import STATE_REGISTER

_LOGGER = logging.getLogger(__name__)

#: The state register confirms there is a machine on the other end.
_PROBE_ADDRESS = STATE_REGISTER


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    """Connection form, pre-filled from `defaults` (used by reconfigure too)."""
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, vol.UNDEFINED)): TextSelector(),
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): NumberSelector(
                NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_SLAVE, default=defaults.get(CONF_SLAVE, DEFAULT_SLAVE)
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=247, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_MODEL, default=defaults.get(CONF_MODEL, DEFAULT_MODEL)
            ): SelectSelector(
                SelectSelectorConfig(options=list(MODELS), mode=SelectSelectorMode.DROPDOWN)
            ),
            # Offered here, and not only in the options, because the moment to
            # decide is before the control entities exist. Someone whose wall
            # controller is still wired should never be given a heating switch.
            vol.Required(
                CONF_READ_ONLY,
                default=defaults.get(CONF_READ_ONLY, DEFAULT_READ_ONLY),
            ): BooleanSelector(),
        }
    )


async def _probe(hass: HomeAssistant, host: str, port: int, slave: int) -> None:
    """Read the state register to prove there is a machine behind the gateway."""
    client = ModbusTCPClient(host, port, slave)
    await hass.async_add_executor_job(client.read_holding, _PROBE_ADDRESS, 1)


def _normalise(user_input: dict[str, Any]) -> dict[str, Any]:
    """Selectors hand back floats; the Modbus layer wants ints."""
    return {
        CONF_HOST: str(user_input[CONF_HOST]).strip(),
        CONF_PORT: int(user_input[CONF_PORT]),
        CONF_SLAVE: int(user_input[CONF_SLAVE]),
        CONF_MODEL: user_input.get(CONF_MODEL, DEFAULT_MODEL),
        CONF_READ_ONLY: bool(user_input.get(CONF_READ_ONLY, DEFAULT_READ_ONLY)),
    }


class MaxaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup and reconfiguration."""

    VERSION = 1

    async def _validate(self, data: dict[str, Any]) -> dict[str, str]:
        """Return a form-error mapping; empty means the connection works."""
        try:
            await _probe(self.hass, data[CONF_HOST], data[CONF_PORT], data[CONF_SLAVE])
        except ModbusError as err:
            _LOGGER.debug("Probe failed for %s: %s", data[CONF_HOST], err)
            return {"base": "cannot_connect"}
        except Exception:  # noqa: BLE001 - never let a surprise break the form
            _LOGGER.exception("Unexpected error probing %s", data[CONF_HOST])
            return {"base": "unknown"}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _normalise(user_input)
            await self.async_set_unique_id(
                f"{data[CONF_HOST]}:{data[CONF_PORT]}:{data[CONF_SLAVE]}"
            )
            self._abort_if_unique_id_configured()
            errors = await self._validate(data)
            if not errors:
                return self.async_create_entry(
                    title=f"{data[CONF_MODEL]} ({data[CONF_HOST]})", data=data
                )
            user_input = data

        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input or {}), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the gateway address or Modbus id without losing entity history."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _normalise(user_input)
            await self.async_set_unique_id(
                f"{data[CONF_HOST]}:{data[CONF_PORT]}:{data[CONF_SLAVE]}"
            )
            self._abort_if_unique_id_mismatch(reason="wrong_device")
            errors = await self._validate(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data_updates=data)
            user_input = data

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or dict(entry.data)),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> MaxaOptionsFlow:
        return MaxaOptionsFlow()


class MaxaOptionsFlow(OptionsFlow):
    """Tune the poll rate without reconfiguring the connection.

    Worth being deliberate about: at 9600 baud a full sweep is seven transactions
    and roughly 350 ms of line time, so intervals below about 15 s leave the bus
    with little idle time and make the machine's own display sluggish.

    Read-only mode lives here too, so it can be turned on without touching the
    connection. Changing either triggers a reload of the entry.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_READ_ONLY: bool(user_input[CONF_READ_ONLY]),
                }
            )

        entry = self.config_entry
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        read_only = entry.options.get(
            CONF_READ_ONLY, entry.data.get(CONF_READ_ONLY, DEFAULT_READ_ONLY)
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=interval): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=5,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_READ_ONLY, default=read_only): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
