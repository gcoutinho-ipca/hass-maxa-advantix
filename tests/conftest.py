"""Shared fixtures.

The fake Modbus client is the important piece here. It answers block reads with a
plausible machine so tests exercise the real coordinator and the real entity
classes, and it records writes so the enable-bit sequence can be asserted on. The
alternative, mocking at the coordinator level, would test the mock.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.maxa_advantix.const import (
    CONF_HOST,
    CONF_MODEL,
    CONF_PORT,
    CONF_SLAVE,
    DEFAULT_MODEL,
    DOMAIN,
)

#: A machine in "heating + hot water", warm, with no alarms. Registers not listed
#: read as zero, which is what a real controller does for unused addresses.
DEFAULT_REGISTERS: dict[int, int] = {
    200: 6,  # heating + DHW
    253: 120,  # evaporation 12.0 °C
    254: 450,  # condensation 45.0 °C
    305: 1042,  # compressor hours
    400: 400,  # inlet 40.0 °C
    401: 455,  # outlet 45.5 °C
    405: 421,  # tank 42.1 °C
    406: 2450,  # high pressure 24.50 bar
    414: 780,  # low pressure 7.80 bar
    422: 95,  # suction 9.5 °C
    428: 182,  # outdoor 18.2 °C
    433: 720,  # discharge 72.0 °C
    444: 32766,  # flow probe absent: sentinel
    7000: 850,  # fan 85 %
    7001: 1000,  # circulator 100 %
    7202: 0b0110,  # both calls raised
    7203: 70,  # cooling setpoint 7.0 °C
    7204: 450,  # heating setpoint 45.0 °C
    7205: 470,  # DHW setpoint 47.0 °C
}


class FakeModbusClient:
    """Stands in for `ModbusTCPClient` without touching a socket."""

    def __init__(self, host: str = "192.168.1.50", port: int = 502, slave: int = 1) -> None:
        self.host = host
        self.port = port
        self.slave = slave
        self.registers: dict[int, int] = dict(DEFAULT_REGISTERS)
        self.writes: list[tuple[int, int]] = []
        self.read_calls: list[tuple[int, int]] = []
        self.fail_reads = False

    def read_holding(self, address: int, count: int = 1) -> list[int]:
        """Answer a block read from the register dictionary."""
        from custom_components.maxa_advantix.modbus_client import ModbusError

        if self.fail_reads:
            raise ModbusError("simulated failure")
        self.read_calls.append((address, count))
        return [self.registers.get(address + offset, 0) for offset in range(count)]

    def write_register(self, address: int, value: int) -> None:
        """Record the write and reflect it, so read-back works."""
        self.writes.append((address, value))
        self.registers[address] = value
        # The real controller mirrors the written state into the readable register.
        if address == 7200:
            self.registers[200] = value

    def stats(self) -> dict[str, Any]:
        """Bus counters, shaped like the real client's."""
        return {
            "transactions": len(self.read_calls) + len(self.writes),
            "errors": 0,
            "timeouts": 0,
            "error_rate": 0.0,
            "last_error": None,
        }


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load integrations from `custom_components/`."""
    return


@pytest.fixture
def fake_client() -> FakeModbusClient:
    """A fresh fake machine per test."""
    return FakeModbusClient()


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A config entry matching what the config flow produces."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="i-HWAK V4 (192.168.1.50)",
        unique_id="192.168.1.50:502:1",
        data={
            CONF_HOST: "192.168.1.50",
            CONF_PORT: 502,
            CONF_SLAVE: 1,
            CONF_MODEL: DEFAULT_MODEL,
        },
    )


@pytest.fixture
async def loaded_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_client: FakeModbusClient,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[MockConfigEntry]:
    """A fully set up integration talking to the fake machine.

    Unloading on teardown is not tidiness. A write schedules a delayed refresh
    about eight seconds out, and unloading is what cancels it. Leaving it pending
    would trip the lingering-timer check, which is the test suite correctly
    telling us that removing the integration must not leave a timer behind.
    """
    import custom_components.maxa_advantix as integration

    monkeypatch.setattr(integration, "ModbusTCPClient", lambda **kwargs: fake_client)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    yield config_entry

    if config_entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()
