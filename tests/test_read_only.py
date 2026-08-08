"""Read-only mode.

The mode exists for two situations where writing is the wrong answer: a machine
still commanded by its original wall controller, where a second controller with a
different opinion looks exactly like a hardware fault, and any installation that
wants the telemetry and nothing else.

It is enforced in two places on purpose. The control platforms are never set up,
so the entities do not exist; and the coordinator refuses writes outright, so an
entity left behind in the registry by an earlier install cannot reach the bus
either. Both are tested here, because a guard that is only tested at the level it
is easiest to test is a guard you do not know you have.
"""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.maxa_advantix.const import (
    CONF_HOST,
    CONF_MODEL,
    CONF_PORT,
    CONF_READ_ONLY,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE,
    DEFAULT_MODEL,
    DOMAIN,
)

from .fake_client import FakeModbusClient

WRITE_PLATFORMS = {
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.WATER_HEATER,
}
READ_PLATFORMS = {Platform.BINARY_SENSOR, Platform.SENSOR}


@pytest.fixture
def read_only_entry() -> MockConfigEntry:
    """A config entry set up for telemetry only."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="i-HWAK V4 (192.168.1.50)",
        unique_id="192.168.1.50:502:1",
        data={
            CONF_HOST: "192.168.1.50",
            CONF_PORT: 502,
            CONF_SLAVE: 1,
            CONF_MODEL: DEFAULT_MODEL,
            CONF_READ_ONLY: True,
        },
    )


@pytest.fixture
async def loaded_read_only(
    hass: HomeAssistant,
    read_only_entry: MockConfigEntry,
    fake_client: FakeModbusClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """A loaded entry in read-only mode."""
    import custom_components.maxa_advantix as integration

    monkeypatch.setattr(integration, "ModbusTCPClient", lambda **kwargs: fake_client)
    read_only_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(read_only_entry.entry_id)
    await hass.async_block_till_done()

    yield read_only_entry

    if read_only_entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(read_only_entry.entry_id)
        await hass.async_block_till_done()


async def test_it_loads(hass: HomeAssistant, loaded_read_only: MockConfigEntry) -> None:
    assert loaded_read_only.state is ConfigEntryState.LOADED
    assert loaded_read_only.runtime_data.read_only is True


async def test_sensors_still_work(
    hass: HomeAssistant, loaded_read_only: MockConfigEntry
) -> None:
    """Telemetry is the whole point of the mode, so it had better be complete."""
    coordinator = loaded_read_only.runtime_data
    assert coordinator.data["water_outlet"] == 45.5
    assert coordinator.data["delta_t"] == 5.5
    assert coordinator.data["machine_state"] == 6


async def test_no_control_entities_exist(
    hass: HomeAssistant, loaded_read_only: MockConfigEntry
) -> None:
    """Not created, rather than created and refusing."""
    registry = er.async_get(hass)
    domains = {
        entry.domain
        for entry in er.async_entries_for_config_entry(registry, loaded_read_only.entry_id)
    }
    assert domains == READ_PLATFORMS
    assert not domains & WRITE_PLATFORMS


async def test_nothing_is_ever_written_to_the_bus(
    hass: HomeAssistant, loaded_read_only: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    """The property that matters: setting up in this mode touches no write register."""
    assert fake_client.writes == []
    assert fake_client.read_calls, "it should still be polling"


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("async_set_state", (2,)),
        ("async_set_calls", (True, False)),
        ("async_set_conditioning", ("heat",)),
        ("async_set_dhw_enabled", (True,)),
        ("async_set_setpoint", (7205, 470)),
        ("async_start_legionella", ()),
        ("async_release", ()),
    ],
)
async def test_every_write_path_is_refused(
    hass: HomeAssistant,
    loaded_read_only: MockConfigEntry,
    fake_client: FakeModbusClient,
    method: str,
    args: tuple,
) -> None:
    """Enumerated rather than sampled: a new write method must be added here too."""
    coordinator = loaded_read_only.runtime_data
    with pytest.raises(ServiceValidationError):
        await getattr(coordinator, method)(*args)
    assert fake_client.writes == []


async def test_write_services_are_refused(
    hass: HomeAssistant, loaded_read_only: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    """Services are registered globally, so they must respect the entry's mode."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "set_mode", {"mode": "cooling"}, blocking=True
        )
    assert fake_client.writes == []


async def test_the_read_service_still_works(
    hass: HomeAssistant, loaded_read_only: MockConfigEntry
) -> None:
    """Reading is not writing: the mapping service stays available."""
    response = await hass.services.async_call(
        DOMAIN,
        "read_register",
        {"address": 401, "count": 1},
        blocking=True,
        return_response=True,
    )
    assert response["values"] == [455]


async def test_turning_read_only_off_brings_the_controls_back(
    hass: HomeAssistant, loaded_read_only: MockConfigEntry
) -> None:
    """The option is a reload, not a reinstall: history and unique ids survive."""
    result = await hass.config_entries.options.async_init(loaded_read_only.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 30, CONF_READ_ONLY: False}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()

    assert loaded_read_only.runtime_data.read_only is False
    registry = er.async_get(hass)
    domains = {
        entry.domain
        for entry in er.async_entries_for_config_entry(registry, loaded_read_only.entry_id)
    }
    assert WRITE_PLATFORMS <= domains


async def test_turning_read_only_on_removes_the_controls(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Starting from a normal entry, the switch must go the other way too."""
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 30, CONF_READ_ONLY: True}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()

    assert loaded_entry.runtime_data.read_only is True
    assert loaded_entry.state is ConfigEntryState.LOADED
    # The entities remain in the registry, disabled by their platform being absent,
    # which is why the coordinator guard exists as well.
    with pytest.raises(ServiceValidationError):
        await loaded_entry.runtime_data.async_set_state(0)
