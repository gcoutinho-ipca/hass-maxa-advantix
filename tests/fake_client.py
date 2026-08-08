"""A fake Modbus client, standing in for a real machine.

Lives in its own module, with no Home Assistant imports, for two reasons. It lets
the transport-level and validation-level tests run without a Home Assistant
install, and it keeps the definition of "what the machine answers" in one place
that both those tests and the full integration tests share.

The register values describe a plausible machine: heating plus hot water, warm,
no alarms, and no flow meter fitted, which is the configuration that produced the
sentinel-filtering requirement in the first place.
"""

from __future__ import annotations

from typing import Any

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
        self.closed = False

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

    def close(self) -> None:
        """Release the (nonexistent) socket."""
        self.closed = True
