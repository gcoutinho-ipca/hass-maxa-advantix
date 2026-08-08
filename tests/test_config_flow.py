"""Config flow: the probe, duplicate protection, and reconfiguration."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.maxa_advantix.const import (
    CONF_HOST,
    CONF_MODEL,
    CONF_PORT,
    CONF_READ_ONLY,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE,
    DOMAIN,
)
from custom_components.maxa_advantix.modbus_client import ModbusError

from .fake_client import FakeModbusClient

USER_INPUT = {
    CONF_HOST: "192.168.1.50",
    CONF_PORT: 502,
    CONF_SLAVE: 1,
    CONF_MODEL: "i-HWAK V4",
    CONF_READ_ONLY: False,
}


@pytest.fixture
def probe_ok(monkeypatch: pytest.MonkeyPatch, fake_client: FakeModbusClient) -> None:
    """Make the connection probe succeed, and the resulting setup work too.

    Both clients have to be replaced. The flow probes with the one imported into
    `config_flow`, and then creating the entry makes Home Assistant load the
    integration, which builds its own from `__init__`. Replacing only the first
    leaves the second opening a real socket.
    """
    monkeypatch.setattr(
        "custom_components.maxa_advantix.config_flow.ModbusTCPClient",
        lambda *args, **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "custom_components.maxa_advantix.ModbusTCPClient",
        lambda *args, **kwargs: fake_client,
    )


@pytest.fixture
def probe_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the connection probe fail the way an unreachable gateway does."""

    class Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def read_holding(self, _address, _count=1):
            raise ModbusError("timeout")

    monkeypatch.setattr("custom_components.maxa_advantix.config_flow.ModbusTCPClient", Client)
    monkeypatch.setattr("custom_components.maxa_advantix.ModbusTCPClient", Client)


async def test_user_flow_creates_an_entry(hass: HomeAssistant, probe_ok: None) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT
    assert "192.168.1.50" in result["title"]


async def test_unreachable_gateway_shows_an_error_and_keeps_the_form(
    hass: HomeAssistant, probe_fails: None
) -> None:
    """The user gets to correct the address instead of getting a broken entry."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_recovering_after_a_failed_attempt(
    hass: HomeAssistant, probe_fails: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"]

    class Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def read_holding(self, _address, _count=1):
            return [0] * _count

        def stats(self):
            return {
                "transactions": 1,
                "errors": 0,
                "timeouts": 0,
                "error_rate": 0.0,
                "last_error": None,
            }

    monkeypatch.setattr("custom_components.maxa_advantix.config_flow.ModbusTCPClient", Client)
    monkeypatch.setattr("custom_components.maxa_advantix.ModbusTCPClient", Client)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_the_same_machine_cannot_be_added_twice(
    hass: HomeAssistant, probe_ok: None, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_a_second_machine_on_another_slave_id_is_allowed(
    hass: HomeAssistant, probe_ok: None, config_entry: MockConfigEntry
) -> None:
    """These controllers support a network of machines behind one gateway."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_SLAVE: 2}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_options_flow_sets_the_scan_interval(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # Changing options triggers a reload through the update listener.
    await hass.async_block_till_done()
    assert loaded_entry.options[CONF_SCAN_INTERVAL] == 60
    assert loaded_entry.runtime_data.update_interval.total_seconds() == 60


async def test_reconfigure_updates_the_address(
    hass: HomeAssistant, probe_ok: None, loaded_entry: MockConfigEntry
) -> None:
    """Moving the gateway is the main reason this step exists, so it must not abort.

    Regression test. The unique id here is derived from the connection, because
    these controllers expose no serial number, so changing the host legitimately
    changes it. Guarding that with the usual device-id mismatch check aborted on
    precisely the case the step is for.
    """
    result = await loaded_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "192.168.1.51"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert loaded_entry.data[CONF_HOST] == "192.168.1.51"
    # The identity follows the connection, and the entry id does not change, so
    # entity unique ids and history survive.
    assert loaded_entry.unique_id == "192.168.1.51:502:1"


async def test_reconfigure_refuses_to_point_at_an_already_configured_machine(
    hass: HomeAssistant, probe_ok: None, loaded_entry: MockConfigEntry
) -> None:
    """Two entries pointing at the same machine would be two masters in one house."""
    other = MockConfigEntry(
        domain=DOMAIN,
        unique_id="192.168.1.60:502:1",
        data={**USER_INPUT, CONF_HOST: "192.168.1.60"},
    )
    other.add_to_hass(hass)

    result = await loaded_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "192.168.1.60"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert loaded_entry.data[CONF_HOST] == "192.168.1.50"
