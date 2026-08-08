"""Write validation and the enable sequence.

These are the tests that stand between a user and the manufacturer's warning that
writing an unaccepted value to the state register "may lead to unexpected
operation".
"""

from __future__ import annotations

import pytest

from custom_components.maxa_advantix import safe_write
from custom_components.maxa_advantix.safe_write import (
    CMD_AMBIENT,
    CMD_DHW,
    ENABLE_AMBIENT_CALL,
    ENABLE_DHW_CALL,
    ENABLE_LEGIONELLA,
    ENABLE_SETPOINT,
    ENABLE_STATE,
    R_COMMAND,
    R_ENABLE,
    R_SET_COOLING,
    R_SET_DHW,
    R_SET_HEATING,
    R_STATE,
    InvalidValueError,
    validate_setpoint,
    validate_state,
)

from .conftest import FakeModbusClient


@pytest.mark.parametrize("state", [0, 1, 2, 4, 5, 6])
def test_legal_states_pass(state):
    validate_state(state)


@pytest.mark.parametrize("state", [3, 7, -1, 8, 100])
def test_illegal_states_are_refused(state):
    with pytest.raises(InvalidValueError, match="not allowed in register 7200"):
        validate_state(state)


def test_nothing_reaches_the_bus_when_the_state_is_refused():
    """Validation happens before the first write, not between writes."""
    client = FakeModbusClient()
    with pytest.raises(InvalidValueError):
        safe_write.apply_state(client, 3)
    assert client.writes == []


@pytest.mark.parametrize(
    ("register", "raw"),
    [
        (R_SET_COOLING, 50),  # 5.0 °C, low bound
        (R_SET_COOLING, 230),  # 23.0 °C, high bound
        (R_SET_HEATING, 250),
        (R_SET_HEATING, 550),
        (R_SET_DHW, 470),
    ],
)
def test_setpoints_within_range_pass(register, raw):
    validate_setpoint(register, raw)


@pytest.mark.parametrize(
    ("register", "raw"),
    [
        (R_SET_COOLING, 49),  # just below
        (R_SET_COOLING, 231),  # just above
        (R_SET_HEATING, 249),
        (R_SET_DHW, 551),
    ],
)
def test_setpoints_outside_range_are_refused(register, raw):
    with pytest.raises(InvalidValueError, match="outside"):
        validate_setpoint(register, raw)


def test_unknown_setpoint_register_is_refused():
    with pytest.raises(InvalidValueError, match="not a known setpoint"):
        validate_setpoint(1234, 300)


def test_error_message_uses_degrees_not_raw_units():
    """The message is user-facing, so it must speak in °C."""
    with pytest.raises(InvalidValueError, match=r"56\.0 °C is outside 25\.0-55\.0 °C"):
        validate_setpoint(R_SET_HEATING, 560)


def test_state_write_enables_first():
    """Order matters: a write without its enable bit is silently ignored."""
    client = FakeModbusClient()
    safe_write.apply_state(client, 6)
    assert client.writes == [(R_ENABLE, ENABLE_STATE | ENABLE_SETPOINT), (R_STATE, 6)]


def test_setpoint_write_enables_first():
    client = FakeModbusClient()
    safe_write.apply_setpoint(client, R_SET_DHW, 470)
    assert client.writes == [
        (R_ENABLE, ENABLE_STATE | ENABLE_SETPOINT),
        (R_SET_DHW, 470),
    ]


def test_calls_carry_their_own_enable_bits():
    client = FakeModbusClient()
    safe_write.apply_calls(client, ambient=True, dhw=False)
    enable, command = client.writes
    assert enable[0] == R_ENABLE
    assert enable[1] & ENABLE_AMBIENT_CALL
    assert not enable[1] & ENABLE_DHW_CALL
    assert command == (R_COMMAND, CMD_AMBIENT)


def test_both_calls_are_written_together():
    """They share one register, so writing one alone would clear the other."""
    client = FakeModbusClient()
    safe_write.apply_calls(client, ambient=True, dhw=True)
    assert client.writes[-1] == (R_COMMAND, CMD_AMBIENT | CMD_DHW)


def test_clearing_calls_writes_zero_rather_than_skipping():
    client = FakeModbusClient()
    safe_write.apply_calls(client, ambient=False, dhw=False)
    assert client.writes[-1] == (R_COMMAND, 0)


def test_state_and_calls_follow_the_documented_order():
    client = FakeModbusClient()
    safe_write.apply_state_and_calls(client, 6, ambient=True, dhw=True)
    assert [address for address, _ in client.writes] == [R_ENABLE, R_STATE, R_COMMAND]


def test_legionella_sets_its_enable_bit():
    client = FakeModbusClient()
    safe_write.start_legionella(client)
    enable, command = client.writes
    assert enable[1] & ENABLE_LEGIONELLA
    assert command[1] == 0b1000  # CMD_LEGIONELLA


def test_release_clears_command_state_enable_in_that_order():
    """Command first: clearing the enable bits first would strand the command."""
    client = FakeModbusClient()
    safe_write.release(client)
    assert client.writes == [(R_COMMAND, 0), (R_STATE, 0), (R_ENABLE, 0)]


def test_release_keeps_going_after_a_failure():
    """The escape hatch must not stop halfway because one register refused."""
    client = FakeModbusClient()
    original = client.write_register
    calls: list[int] = []

    def flaky(address: int, value: int) -> None:
        calls.append(address)
        if address == R_STATE:
            raise OSError("simulated")
        original(address, value)

    client.write_register = flaky  # type: ignore[method-assign]
    with pytest.raises(InvalidValueError, match="could not fully release"):
        safe_write.release(client)
    assert calls == [R_COMMAND, R_STATE, R_ENABLE]
