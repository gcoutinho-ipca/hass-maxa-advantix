"""Validated writes: manufacturer ranges plus the controller's enable sequence.

The manufacturer's own warning about the state register is blunt: writing a value
it does not accept "may lead to unexpected operation". So **every** write is
checked against the documented range before a single byte reaches the bus, and
the check lives here rather than in the entities, so services, automations and
the UI all go through the same gate.

Two behaviours of this controller are encoded here because they are not
guessable from the register table alone, and both were established by
measurement:

* Nothing can be written without first setting the matching **enable bit** in
  register 7201. A setpoint written without its enable bit is accepted on the
  wire and silently ignored by the machine.
* Order matters: enables (7201) → state (7200) → commands (7202). A command sent
  before its enable does nothing at all.

The distinction between *state* and *call* is the other thing worth
internalising: the state (7200) selects the operating mode, the call (7202) is
what actually makes the machine run. Setting a mode without a call gives you a
heat pump that is idle and looks correctly configured.
"""

from __future__ import annotations

from typing import Final

from homeassistant.exceptions import HomeAssistantError

from .modbus_client import ModbusTCPClient

# ── write registers ───────────────────────────────────────────────────────────
R_STATE: Final = 7200
R_ENABLE: Final = 7201
R_COMMAND: Final = 7202
R_SET_COOLING: Final = 7203
R_SET_HEATING: Final = 7204
R_SET_DHW: Final = 7205
R_SET_DHW_HEATER: Final = 7208

# Values register 7200 accepts. 3 and 7 are refused by the controller; 2/4/6 may
# also be refused when a dry-contact input forces cooling, which is the
# machine's decision and not an error on our side.
VALID_STATES: Final = frozenset({0, 1, 2, 4, 5, 6})

# Setpoint ranges in raw units (°C x 10), from the V4 documentation.
SETPOINT_RANGES: Final[dict[int, tuple[int, int, str]]] = {
    R_SET_COOLING: (50, 230, "cooling setpoint"),  # 5.0-23.0 °C
    R_SET_HEATING: (250, 550, "heating setpoint"),  # 25.0-55.0 °C
    R_SET_DHW: (250, 550, "DHW setpoint"),  # 25.0-55.0 °C
    R_SET_DHW_HEATER: (0, 800, "DHW preheater setpoint"),  # 0.0-80.0 °C
}

# Enable bits, register 7201.
ENABLE_STATE: Final = 1 << 0
ENABLE_SETPOINT: Final = 1 << 1
ENABLE_SECOND_SETPOINT: Final = 1 << 2
ENABLE_AMBIENT_CALL: Final = 1 << 3
ENABLE_DHW_CALL: Final = 1 << 4
ENABLE_LEGIONELLA: Final = 1 << 5

# Command bits, register 7202.
CMD_SECOND_SETPOINT: Final = 1 << 0
CMD_AMBIENT: Final = 1 << 1
CMD_DHW: Final = 1 << 2
CMD_LEGIONELLA: Final = 1 << 3
CMD_FORCED_PURGE: Final = 1 << 5
CMD_INHIBIT_DHW: Final = 1 << 6

#: Baseline enable mask. State and setpoint writing stay enabled so the UI is
#: usable at all times; call bits are added only when a call is requested.
_BASE_ENABLE: Final = ENABLE_STATE | ENABLE_SETPOINT


class InvalidValueError(HomeAssistantError):
    """Value outside the manufacturer's range, refused before touching the bus.

    Deriving from HomeAssistantError means the user sees the message in the UI
    instead of a traceback in the log.
    """


def validate_state(state: int) -> None:
    """Reject anything register 7200 does not accept."""
    if state not in VALID_STATES:
        raise InvalidValueError(
            f"state {state} is not allowed in register 7200 "
            f"(only {sorted(VALID_STATES)})"
        )


def validate_setpoint(address: int, raw: int) -> None:
    """Reject a setpoint outside its documented range."""
    if address not in SETPOINT_RANGES:
        raise InvalidValueError(f"register {address} is not a known setpoint")
    low, high, name = SETPOINT_RANGES[address]
    if not low <= raw <= high:
        raise InvalidValueError(
            f"{name}: {raw / 10:.1f} °C is outside {low / 10:.1f}-{high / 10:.1f} °C"
        )


def enable_mask(*, ambient: bool = False, dhw: bool = False, legionella: bool = False) -> int:
    """Build the 7201 mask for the operations about to be performed."""
    mask = _BASE_ENABLE
    if ambient:
        mask |= ENABLE_AMBIENT_CALL
    if dhw:
        mask |= ENABLE_DHW_CALL
    if legionella:
        mask |= ENABLE_LEGIONELLA
    return mask


def command_mask(*, ambient: bool = False, dhw: bool = False, legionella: bool = False) -> int:
    """Build the 7202 command word."""
    mask = 0
    if ambient:
        mask |= CMD_AMBIENT
    if dhw:
        mask |= CMD_DHW
    if legionella:
        mask |= CMD_LEGIONELLA
    return mask


# ── composed operations (run in the executor, via the coordinator) ────────────
def apply_state(client: ModbusTCPClient, state: int) -> None:
    """Enable state writing and write register 7200. Validated first."""
    validate_state(state)
    client.write_register(R_ENABLE, _BASE_ENABLE)
    client.write_register(R_STATE, state)


def apply_calls(client: ModbusTCPClient, ambient: bool, dhw: bool) -> None:
    """Turn the space-conditioning and DHW calls on or off.

    Both are written together because they share register 7202: writing one
    alone would clear the other.
    """
    client.write_register(R_ENABLE, enable_mask(ambient=ambient, dhw=dhw))
    client.write_register(R_COMMAND, command_mask(ambient=ambient, dhw=dhw))


def apply_state_and_calls(
    client: ModbusTCPClient, state: int, ambient: bool, dhw: bool
) -> None:
    """Set mode and calls in one pass, in the order the controller expects."""
    validate_state(state)
    client.write_register(R_ENABLE, enable_mask(ambient=ambient, dhw=dhw))
    client.write_register(R_STATE, state)
    client.write_register(R_COMMAND, command_mask(ambient=ambient, dhw=dhw))


def apply_setpoint(client: ModbusTCPClient, address: int, raw: int) -> None:
    """Enable setpoint writing and write one setpoint. Validated first.

    Field note: these registers accept the write and read back the new value,
    but on some configurations the setpoint the thermoregulation actually uses
    lives in the controller's own PRG→Set menu. Writing here is correct and
    safe; whether the machine treats it as active is the machine's call.
    """
    validate_setpoint(address, raw)
    client.write_register(R_ENABLE, _BASE_ENABLE)
    client.write_register(address, raw)


def start_legionella(client: ModbusTCPClient) -> None:
    """Start the anti-legionella cycle.

    The command bit must stay at 1 for the whole cycle, so it is left set; the
    controller clears its own status bits in 7216 when the cycle ends.
    """
    client.write_register(R_ENABLE, enable_mask(legionella=True))
    client.write_register(R_COMMAND, command_mask(legionella=True))


def release(client: ModbusTCPClient) -> None:
    """Hand control back: clear 7202, 7200 and 7201, in that order.

    Best effort by design. This is the escape hatch used when something looks
    wrong, so a failure on one register must not stop the other two from being
    cleared.
    """
    problems: list[str] = []
    for address in (R_COMMAND, R_STATE, R_ENABLE):
        try:
            client.write_register(address, 0)
        except Exception as err:  # noqa: BLE001 - releasing is best effort
            problems.append(f"{address}: {err}")
    if problems:
        raise InvalidValueError("could not fully release control: " + "; ".join(problems))
