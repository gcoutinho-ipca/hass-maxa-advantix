"""Coordinator behaviour: sentinels, derived values, and single-master discipline."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.maxa_advantix.const import (
    KEY_ACTIVE_ALARMS,
    KEY_ALARM_COUNT,
    KEY_DELTA_T,
    KEY_MODE_SWITCHES,
)

from .conftest import FakeModbusClient


async def test_registers_are_read_in_blocks_not_one_by_one(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    """Twelve transactions per sweep, not one per register. The bus is the budget."""
    multi = [call for call in fake_client.read_calls if call[1] > 1]
    assert multi, "no block reads happened at all"
    assert len(fake_client.read_calls) <= 14
    assert (400, 15) in fake_client.read_calls


async def test_scaling_is_applied(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    coordinator = loaded_entry.runtime_data
    assert coordinator.data["water_inlet"] == 40.0  # raw 400, scale 0.1
    assert coordinator.data["water_outlet"] == 45.5
    assert coordinator.data["high_pressure"] == 24.5  # raw 2450, scale 0.01


async def test_sentinel_becomes_none_not_a_measurement(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The flow probe answers 32766. Publishing that is how you get 23 546 kW."""
    coordinator = loaded_entry.runtime_data
    assert coordinator.data["flow_rate"] is None


async def test_thermal_power_is_not_computed_without_a_real_flow_reading(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    coordinator = loaded_entry.runtime_data
    assert coordinator.data["thermal_power"] is None


async def test_thermal_power_is_computed_when_flow_is_real(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    fake_client.registers[444] = 20  # 20 l/min
    coordinator = loaded_entry.runtime_data
    await coordinator.async_refresh()
    # 20/60 * 4.186 * 5.5 K
    assert coordinator.data["thermal_power"] == round(20 / 60 * 4.186 * 5.5, 2)


async def test_delta_t_is_outlet_minus_inlet(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    coordinator = loaded_entry.runtime_data
    assert coordinator.data[KEY_DELTA_T] == 5.5


async def test_delta_t_is_none_when_a_probe_is_missing(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    fake_client.registers[400] = 32766  # inlet probe absent
    coordinator = loaded_entry.runtime_data
    await coordinator.async_refresh()
    assert coordinator.data[KEY_DELTA_T] is None


async def test_alarm_words_are_read_unsigned(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    """Bit 15 set means -32768 signed. Masking is not optional."""
    fake_client.registers[951] = -32768  # what a signed read gives for bit 15
    coordinator = loaded_entry.runtime_data
    await coordinator.async_refresh()
    codes = [alarm["code"] for alarm in coordinator.data[KEY_ACTIVE_ALARMS]]
    assert codes == ["E102"]
    assert coordinator.data[KEY_ALARM_COUNT] == 1


async def test_status_bits_are_decoded(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    fake_client.registers[7214] = 1 << 14  # defrost running
    fake_client.registers[7216] = 1 << 5  # anti-legionella running
    coordinator = loaded_entry.runtime_data
    await coordinator.async_refresh()
    assert coordinator.data["defrost_running"] is True
    assert coordinator.data["defrost_requested"] is False
    assert coordinator.data["legionella_running"] is True
    assert coordinator.data["legionella_failed"] is False


async def test_mode_switches_count_transitions_only(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    """The metric that exposed the original fault, so it had better be right."""
    coordinator = loaded_entry.runtime_data
    assert coordinator.data[KEY_MODE_SWITCHES] == 0

    await coordinator.async_refresh()  # same state again
    assert coordinator.data[KEY_MODE_SWITCHES] == 0

    fake_client.registers[200] = 2
    await coordinator.async_refresh()
    assert coordinator.data[KEY_MODE_SWITCHES] == 1
    assert coordinator.data["last_mode_change"] is not None

    fake_client.registers[200] = 6
    await coordinator.async_refresh()
    assert coordinator.data[KEY_MODE_SWITCHES] == 2


async def test_read_failure_marks_the_update_unsuccessful(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    coordinator = loaded_entry.runtime_data
    fake_client.fail_reads = True
    await coordinator.async_refresh()
    assert coordinator.last_update_success is False


async def test_writes_go_through_the_coordinator_lock(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    """Every write must be serialised with the poll cycle: one master, one queue."""
    coordinator = loaded_entry.runtime_data
    await coordinator.async_set_state(2)
    await hass.async_block_till_done()
    assert (7200, 2) in fake_client.writes


async def test_conditioning_change_preserves_hot_water(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    """State 6 is heating plus hot water; turning conditioning off must give 4."""
    coordinator = loaded_entry.runtime_data
    await coordinator.async_set_conditioning("off")
    await hass.async_block_till_done()
    state_writes = [value for address, value in fake_client.writes if address == 7200]
    assert state_writes[-1] == 4


async def test_hot_water_change_preserves_conditioning(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    coordinator = loaded_entry.runtime_data
    await coordinator.async_set_dhw_enabled(False)
    await hass.async_block_till_done()
    state_writes = [value for address, value in fake_client.writes if address == 7200]
    assert state_writes[-1] == 2
