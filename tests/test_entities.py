"""Entity behaviour, exercised through the real platforms against a fake machine."""

from __future__ import annotations

from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.components.water_heater import STATE_HEAT_PUMP
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.maxa_advantix.const import DOMAIN

from .conftest import FakeModbusClient


async def test_entry_loads_and_unloads(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    assert loaded_entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert loaded_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_fails_cleanly_when_the_machine_does_not_answer(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_client: FakeModbusClient,
    monkeypatch,
) -> None:
    """Better a retry than a device full of unavailable entities."""
    import custom_components.maxa_advantix as integration

    fake_client.fail_reads = True
    monkeypatch.setattr(integration, "ModbusTCPClient", lambda **kwargs: fake_client)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_every_platform_is_set_up(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    domains = {
        entry.domain
        for entry in er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
    }
    assert domains == {
        Platform.SENSOR,
        Platform.BINARY_SENSOR,
        Platform.CLIMATE,
        Platform.WATER_HEATER,
        Platform.SELECT,
        Platform.NUMBER,
        Platform.SWITCH,
        Platform.BUTTON,
    }


async def test_all_entities_share_one_device(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
    devices = {entry.device_id for entry in entries}
    assert len(devices) == 1


async def test_per_alarm_entities_are_created_disabled(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Forty flags exist without costing forty states."""
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
    alarm_entries = [entry for entry in entries if "_alarm_e" in entry.unique_id]
    assert len(alarm_entries) == 40
    assert all(entry.disabled_by is not None for entry in alarm_entries)


async def test_absent_probe_reports_unavailable_not_a_number(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The flow sensor is disabled by default, so enable it and check the state."""
    registry = er.async_get(hass)
    unique_id = f"{loaded_entry.entry_id}_flow_rate"
    entity_id = registry.async_get_entity_id(Platform.SENSOR, DOMAIN, unique_id)
    assert entity_id is not None
    registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE


def _entity_id(hass: HomeAssistant, entry: MockConfigEntry, platform: str, key: str) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id is not None, f"{platform} entity for {key} was not created"
    return entity_id


async def test_climate_reflects_the_machine(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    entity_id = _entity_id(hass, loaded_entry, Platform.CLIMATE, "climate")
    state = hass.states.get(entity_id)
    assert state.state == HVACMode.HEAT  # register 200 = 6
    assert state.attributes["current_temperature"] == 45.5  # outlet water
    assert state.attributes["temperature"] == 45.0  # heating setpoint
    assert state.attributes["hvac_action"] == HVACAction.HEATING


async def test_climate_action_is_idle_without_a_call(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    """Mode set, no call raised: configured and doing nothing."""
    fake_client.registers[7202] = 0
    await loaded_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    entity_id = _entity_id(hass, loaded_entry, Platform.CLIMATE, "climate")
    assert hass.states.get(entity_id).attributes["hvac_action"] == HVACAction.IDLE


async def test_climate_action_reports_defrosting(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    fake_client.registers[7214] = 1 << 14
    await loaded_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    entity_id = _entity_id(hass, loaded_entry, Platform.CLIMATE, "climate")
    assert hass.states.get(entity_id).attributes["hvac_action"] == HVACAction.DEFROSTING


async def test_climate_target_range_follows_the_mode(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    entity_id = _entity_id(hass, loaded_entry, Platform.CLIMATE, "climate")
    heating = hass.states.get(entity_id).attributes
    assert (heating["min_temp"], heating["max_temp"]) == (25.0, 55.0)

    await hass.services.async_call(
        Platform.CLIMATE,
        "set_hvac_mode",
        {"entity_id": entity_id, "hvac_mode": HVACMode.COOL},
        blocking=True,
    )
    await hass.async_block_till_done()
    cooling = hass.states.get(entity_id).attributes
    assert (cooling["min_temp"], cooling["max_temp"]) == (5.0, 23.0)


async def test_turning_climate_off_keeps_hot_water(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    """The interaction that a naive state mapping gets wrong."""
    climate_id = _entity_id(hass, loaded_entry, Platform.CLIMATE, "climate")
    water_id = _entity_id(hass, loaded_entry, Platform.WATER_HEATER, "water_heater")
    assert hass.states.get(water_id).state == STATE_HEAT_PUMP

    await hass.services.async_call(
        Platform.CLIMATE,
        "set_hvac_mode",
        {"entity_id": climate_id, "hvac_mode": HVACMode.OFF},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert fake_client.registers[200] == 4  # hot water only
    assert hass.states.get(water_id).state == STATE_HEAT_PUMP


async def test_turning_hot_water_off_keeps_heating(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    climate_id = _entity_id(hass, loaded_entry, Platform.CLIMATE, "climate")
    water_id = _entity_id(hass, loaded_entry, Platform.WATER_HEATER, "water_heater")

    await hass.services.async_call(
        Platform.WATER_HEATER,
        "set_operation_mode",
        {"entity_id": water_id, "operation_mode": STATE_OFF},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert fake_client.registers[200] == 2  # heating only
    assert hass.states.get(climate_id).state == HVACMode.HEAT


async def test_water_heater_setpoint_is_written_in_raw_units(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    water_id = _entity_id(hass, loaded_entry, Platform.WATER_HEATER, "water_heater")
    await hass.services.async_call(
        Platform.WATER_HEATER,
        "set_temperature",
        {"entity_id": water_id, "temperature": 48.5},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert (7205, 485) in fake_client.writes


async def test_setpoint_outside_the_range_is_refused(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    """The number entity's bounds stop the UI; validation stops everything else."""
    coordinator = loaded_entry.runtime_data
    from custom_components.maxa_advantix.safe_write import InvalidValueError

    before = list(fake_client.writes)
    try:
        await coordinator.async_set_setpoint(7205, 600)  # 60 °C, above the 55 limit
    except InvalidValueError:
        pass
    else:
        raise AssertionError("an out-of-range setpoint was accepted")
    assert fake_client.writes == before


async def test_select_offers_exactly_the_legal_states(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    entity_id = _entity_id(hass, loaded_entry, Platform.SELECT, "state_select")
    options = hass.states.get(entity_id).attributes["options"]
    assert options == [
        "standby",
        "cooling",
        "heating",
        "dhw",
        "cooling_dhw",
        "heating_dhw",
    ]
    assert hass.states.get(entity_id).state == "heating_dhw"


async def test_call_switches_do_not_clear_each_other(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    """Both calls live in one register, which is the trap this guards against."""
    ambient_id = _entity_id(hass, loaded_entry, Platform.SWITCH, "ambient_call")
    dhw_id = _entity_id(hass, loaded_entry, Platform.SWITCH, "dhw_call")
    assert hass.states.get(ambient_id).state == "on"
    assert hass.states.get(dhw_id).state == "on"

    await hass.services.async_call(
        Platform.SWITCH, "turn_off", {"entity_id": ambient_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert fake_client.registers[7202] == 0b0100  # DHW call still raised
    assert hass.states.get(dhw_id).state == "on"


async def test_release_button_clears_control(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    entity_id = _entity_id(hass, loaded_entry, Platform.BUTTON, "release_control")
    await hass.services.async_call(
        Platform.BUTTON, "press", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert (7202, 0) in fake_client.writes
    assert (7201, 0) in fake_client.writes


async def test_delta_t_sensor_carries_the_manufacturer_limits(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    entity_id = _entity_id(hass, loaded_entry, Platform.SENSOR, "delta_t")
    state = hass.states.get(entity_id)
    assert float(state.state) == 5.5
    assert state.attributes["tolerated_maximum"] == 8.0
    assert state.attributes["flow_restricted"] is False


async def test_flow_restricted_turns_on_above_the_limit(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    fake_client.registers[401] = 570  # outlet 57.0 against inlet 40.0: ΔT 17 K
    await loaded_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    entity_id = _entity_id(hass, loaded_entry, Platform.BINARY_SENSOR, "flow_restricted")
    assert hass.states.get(entity_id).state == "on"


async def test_active_alarms_sensor_lists_codes(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    fake_client.registers[951] = 1 << 12  # E042
    await loaded_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    entity_id = _entity_id(hass, loaded_entry, Platform.SENSOR, "active_alarms")
    state = hass.states.get(entity_id)
    assert state.state == "E042"
    assert state.attributes["count"] == 1
    assert any("E042" in line for line in state.attributes["alarms"])


async def test_services_are_registered(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    for service in (
        "set_mode",
        "set_dhw_setpoint",
        "start_legionella",
        "release_control",
        "read_register",
    ):
        assert hass.services.has_service(DOMAIN, service), service


async def test_set_mode_service_writes_the_state(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    await hass.services.async_call(
        DOMAIN, "set_mode", {"mode": "cooling_dhw"}, blocking=True
    )
    await hass.async_block_till_done()
    assert (7200, 5) in fake_client.writes


async def test_read_register_service_returns_both_views(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake_client: FakeModbusClient
) -> None:
    """Status registers need the unsigned view, so both are returned."""
    fake_client.registers[951] = -32768
    response = await hass.services.async_call(
        DOMAIN,
        "read_register",
        {"address": 951, "count": 1},
        blocking=True,
        return_response=True,
    )
    assert response["values"] == [-32768]
    assert response["unsigned"] == [32768]


async def test_diagnostics_redact_the_gateway_address(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, hass_client
) -> None:
    """A diagnostics download ends up attached to a public issue."""
    from pytest_homeassistant_custom_component.components.diagnostics import (
        get_diagnostics_for_config_entry,
    )

    data = await get_diagnostics_for_config_entry(hass, hass_client, loaded_entry)
    assert data["config"]["host"] != "192.168.1.50"
    assert "192.168.1.50" not in str(data)
    # What makes a report answerable stays.
    assert data["config"]["port"] == 502
    assert data["config"]["slave"] == 1
    assert data["last_update_success"] is True
    assert data["reading"]["water_outlet"] == 45.5
    assert "blocks_polled" in data
