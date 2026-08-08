"""Minimal Modbus-TCP client with no external dependencies.

Written by hand instead of pulling in `pymodbus`, for two reasons learned the
hard way with RTU-to-TCP gateways in front of this controller family:

1. **Holding and input registers are mirrored.** The gateway answers function 3
   and function 4 from the same memory block (measured: register 405 returns the
   same value either way). Owning the client lets us read everything with
   function 3 and stop guessing which `input_type` a register wants.

2. **Single-master discipline.** On RS-485 there is exactly one master. A
   deliberately small client, with an explicit connect/close per transaction,
   makes that serialization obvious instead of hiding it behind a connection
   pool that a large library would keep alive across calls.

A connection is opened per transaction rather than kept alive, and that is a
considered choice rather than laziness. A persistent socket would save the TCP
handshake, which on a local gateway is around 1 ms; a poll cycle is seven
transactions, so the saving is under 10 ms against roughly 350 ms of serial line
time. Paying for that with a long-lived socket, and with the reconnect and
half-open-connection handling it drags in, buys a 2% improvement in the wrong
place. If a future gateway makes connection setup expensive, this is the paragraph
to come back and disagree with.

Only what is needed is implemented: function 3 (read holding registers),
function 6 (write single register), the MBAP header and Modbus exception
handling. No fragmentation, no function 16, because this controller accepts
register-at-a-time writes.

Every method here blocks. Call them from Home Assistant's executor, never from
the event loop.
"""

from __future__ import annotations

import logging
import socket
import struct
import time
from typing import Final

from .const import MODBUS_RETRIES, MODBUS_TIMEOUT

_LOGGER = logging.getLogger(__name__)

#: Quiet time left on the wire between transactions. RS-485 gateways need a gap
#: to turn the line around; without it the first bytes of a reply get eaten and
#: show up as sporadic timeouts.
INTERFRAME_DELAY: Final = 0.05

#: Retry backoff, seconds. Short: a whole poll cycle must still fit in the
#: scan interval even if a couple of blocks need a second attempt.
RETRY_BACKOFF: Final = 0.2

#: Protocol ceiling for function 3: the reply's byte count is one byte, so 125
#: registers is the most that fits.
MAX_REGISTERS_PER_READ: Final = 125

_FUNC_READ_HOLDING: Final = 3
_FUNC_WRITE_SINGLE: Final = 6
_MODBUS_EXCEPTIONS: Final[dict[int, str]] = {
    1: "illegal function",
    2: "illegal data address",
    3: "illegal data value",
    4: "slave device failure",
    6: "slave device busy",
    10: "gateway path unavailable",
    11: "gateway target device failed to respond",
}


class ModbusError(Exception):
    """Communication failure, or a Modbus exception returned by the device."""


class ModbusTCPClient:
    """Blocking Modbus-TCP client. Always call from the executor."""

    def __init__(self, host: str, port: int, slave: int) -> None:
        self._host = host
        self._port = port
        self._slave = slave
        self._transaction = 0
        self._last_tx = 0.0
        # bus health counters, since startup
        self.transactions = 0
        self.errors = 0
        self.timeouts = 0
        self.last_error: str | None = None

    def stats(self) -> dict[str, int | float | str | None]:
        """Snapshot of bus health, for the diagnostic sensor.

        The error *rate* is what matters: a gateway that is starting to fail
        shows up as a slowly rising percentage long before entities go
        unavailable.
        """
        rate = round(100 * self.errors / self.transactions, 1) if self.transactions else 0.0
        return {
            "transactions": self.transactions,
            "errors": self.errors,
            "timeouts": self.timeouts,
            "error_rate": rate,
            "last_error": self.last_error,
        }

    def _next_transaction_id(self) -> int:
        self._transaction = (self._transaction + 1) % 0xFFFF or 1
        return self._transaction

    def _respect_interframe_gap(self) -> None:
        elapsed = time.monotonic() - self._last_tx
        if 0 <= elapsed < INTERFRAME_DELAY:
            time.sleep(INTERFRAME_DELAY - elapsed)

    def _transact(self, pdu: bytes) -> bytes:
        """Send one PDU, return the data bytes of the reply (MBAP stripped)."""
        self._respect_interframe_gap()
        self.transactions += 1
        mbap = struct.pack(">HHHB", self._next_transaction_id(), 0, len(pdu) + 1, self._slave)
        try:
            sock = socket.create_connection((self._host, self._port), timeout=MODBUS_TIMEOUT)
        except OSError as err:
            self.errors += 1
            if isinstance(err, TimeoutError):
                self.timeouts += 1
            self.last_error = f"connect: {err}"
            raise ModbusError(f"connecting to {self._host}:{self._port}: {err}") from err
        try:
            sock.settimeout(MODBUS_TIMEOUT)
            sock.sendall(mbap + pdu)
            header = _recv_exactly(sock, 8)
            function = header[7]
            if function & 0x80:  # exception bit
                code = _recv_exactly(sock, 1)[0]
                name = _MODBUS_EXCEPTIONS.get(code, "unknown")
                raise ModbusError(f"Modbus exception {code} ({name})")
            if function == _FUNC_READ_HOLDING:
                length = _recv_exactly(sock, 1)[0]
                return _recv_exactly(sock, length)
            if function == _FUNC_WRITE_SINGLE:
                return _recv_exactly(sock, 4)  # echo of address + value
            raise ModbusError(f"unexpected function in reply: {function}")
        except TimeoutError as err:
            self.errors += 1
            self.timeouts += 1
            self.last_error = f"timeout: {err}"
            raise ModbusError(f"timeout waiting for reply: {err}") from err
        except ModbusError as err:
            self.errors += 1
            self.last_error = str(err)
            raise
        except OSError as err:
            self.errors += 1
            self.last_error = f"socket: {err}"
            raise ModbusError(f"socket error: {err}") from err
        finally:
            self._last_tx = time.monotonic()
            sock.close()

    def read_holding(self, address: int, count: int = 1) -> list[int]:
        """Read `count` holding registers from `address` as signed 16-bit ints.

        Retries up to `MODBUS_RETRIES` times: these gateways return occasional
        timeouts, and one miss must not mark the machine offline.

        Values come back signed because most process registers are temperatures
        that can legitimately go below zero. Callers that need a bitmask (the
        alarm words use bit 15) must mask with `& 0xFFFF`.
        """
        # Modbus function 3 carries at most 125 registers in one reply, because the
        # byte count field is a single byte. Asking for more builds a frame the
        # gateway cannot answer, and the failure surfaces as an unexplained timeout
        # rather than as the programming error it is.
        if not 1 <= count <= MAX_REGISTERS_PER_READ:
            raise ValueError(f"count must be between 1 and {MAX_REGISTERS_PER_READ}, got {count}")
        last: Exception | None = None
        for attempt in range(MODBUS_RETRIES):
            try:
                data = self._transact(struct.pack(">BHH", _FUNC_READ_HOLDING, address, count))
                words = len(data) // 2
                raw = struct.unpack(f">{words}H", data[: words * 2])
                return [v - 65536 if v > 32767 else v for v in raw]
            except ModbusError as err:
                last = err
                if attempt + 1 < MODBUS_RETRIES:
                    time.sleep(RETRY_BACKOFF)
        raise ModbusError(
            f"read of {count} register(s) at {address} failed "
            f"after {MODBUS_RETRIES} attempts: {last}"
        )

    def write_register(self, address: int, value: int) -> None:
        """Write a single register (function 6).

        No range checking happens here on purpose: that is `safe_write`'s job,
        and keeping the transport dumb means the validation cannot be bypassed
        by accident from somewhere else in the integration.
        """
        self._transact(struct.pack(">BHH", _FUNC_WRITE_SINGLE, address, value & 0xFFFF))


def _recv_exactly(sock: socket.socket, length: int) -> bytes:
    """Read exactly `length` bytes, or raise if the peer closes early."""
    chunks: list[bytes] = []
    remaining = length
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ModbusError("connection closed mid-reply")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
