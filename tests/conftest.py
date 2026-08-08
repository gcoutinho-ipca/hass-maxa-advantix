"""Shared fixtures.

The fake Modbus client that these fixtures wire in lives in `fake_client.py`,
deliberately free of Home Assistant imports so the transport and validation tests
can run without one. It answers block reads with a plausible machine, so the tests
exercise the real coordinator and the real entity classes; mocking at the
coordinator level instead would only test the mock.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

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

from .fake_client import DEFAULT_REGISTERS, FakeModbusClient  # noqa: F401


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
