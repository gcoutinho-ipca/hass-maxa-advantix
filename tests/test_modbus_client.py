"""Frame building and parsing, against a socket that never leaves the process."""

from __future__ import annotations

import struct

import pytest

from custom_components.maxa_advantix.modbus_client import ModbusError, ModbusTCPClient


class FakeSocket:
    """Replays a canned reply and records what was sent."""

    def __init__(self, reply: bytes, *, raise_on_recv: type[Exception] | None = None) -> None:
        self._reply = reply
        self._raise = raise_on_recv
        self.sent = b""
        self.closed = False

    def settimeout(self, _timeout: float) -> None:
        return

    def sendall(self, payload: bytes) -> None:
        self.sent += payload

    def recv(self, length: int) -> bytes:
        if self._raise is not None:
            raise self._raise("simulated")
        chunk, self._reply = self._reply[:length], self._reply[length:]
        return chunk

    def close(self) -> None:
        self.closed = True


def _mbap(payload: bytes, transaction: int = 1, unit: int = 1) -> bytes:
    """Wrap a PDU in the MBAP header a gateway would send back."""
    return struct.pack(">HHHB", transaction, 0, len(payload) + 1, unit) + payload


@pytest.fixture
def patch_socket(monkeypatch: pytest.MonkeyPatch):
    """Install a fake socket factory and hand back the sockets it created."""
    created: list[FakeSocket] = []

    def install(reply: bytes, **kwargs) -> list[FakeSocket]:
        def create_connection(_address, timeout=None):  # noqa: ARG001
            sock = FakeSocket(reply, **kwargs)
            created.append(sock)
            return sock

        monkeypatch.setattr(
            "custom_components.maxa_advantix.modbus_client.socket.create_connection",
            create_connection,
        )
        # Retries sleep; tests should not.
        monkeypatch.setattr(
            "custom_components.maxa_advantix.modbus_client.time.sleep", lambda _s: None
        )
        return created

    return install


def test_read_holding_returns_the_value(patch_socket):
    patch_socket(_mbap(bytes([3, 2]) + struct.pack(">H", 455)))
    client = ModbusTCPClient("192.168.1.50", 502, 1)
    assert client.read_holding(401, 1) == [455]


def test_request_bytes_are_exactly_what_the_gateway_expects(patch_socket):
    sockets = patch_socket(_mbap(bytes([3, 2]) + struct.pack(">H", 100)))
    client = ModbusTCPClient("192.168.1.50", 502, 7)
    client.read_holding(400, 1)

    sent = sockets[0].sent
    transaction, protocol, length, unit = struct.unpack(">HHHB", sent[:7])
    function, address, count = struct.unpack(">BHH", sent[7:])
    assert protocol == 0
    assert length == 6  # unit + function + address + count
    assert unit == 7  # the slave id, not hard-coded
    assert (function, address, count) == (3, 400, 1)
    assert transaction >= 1


def test_negative_temperatures_survive_the_round_trip(patch_socket):
    """Registers are signed: a frozen outdoor probe must not read as 65 486."""
    raw = struct.pack(">h", -50)  # -5.0 °C at scale 0.1
    patch_socket(_mbap(bytes([3, 2]) + raw))
    client = ModbusTCPClient("192.168.1.50", 502, 1)
    assert client.read_holding(428, 1) == [-50]


def test_block_read_returns_every_register(patch_socket):
    values = [400, 455, 0, 0, 421]
    payload = bytes([3, len(values) * 2]) + b"".join(struct.pack(">H", v) for v in values)
    patch_socket(_mbap(payload))
    client = ModbusTCPClient("192.168.1.50", 502, 1)
    assert client.read_holding(400, 5) == values


def test_modbus_exception_is_raised_with_its_name(patch_socket):
    patch_socket(_mbap(bytes([0x83, 2])))  # function 3 with exception bit, code 2
    client = ModbusTCPClient("192.168.1.50", 502, 1)
    with pytest.raises(ModbusError, match="illegal data address"):
        client.read_holding(9999, 1)


def test_reads_are_retried_before_giving_up(patch_socket):
    sockets = patch_socket(b"", raise_on_recv=TimeoutError)
    client = ModbusTCPClient("192.168.1.50", 502, 1)
    with pytest.raises(ModbusError, match="failed after 3 attempts"):
        client.read_holding(400, 1)
    assert len(sockets) == 3
    assert client.timeouts == 3


def test_a_closed_connection_mid_reply_is_an_error_not_a_short_read(patch_socket):
    patch_socket(bytes([0, 1, 0, 0]))  # truncated MBAP
    client = ModbusTCPClient("192.168.1.50", 502, 1)
    with pytest.raises(ModbusError):
        client.read_holding(400, 1)


def test_write_register_masks_to_sixteen_bits(patch_socket):
    sockets = patch_socket(_mbap(bytes([6]) + struct.pack(">HH", 7200, 6)))
    client = ModbusTCPClient("192.168.1.50", 502, 1)
    client.write_register(7200, 6)
    function, address, value = struct.unpack(">BHH", sockets[0].sent[7:])
    assert (function, address, value) == (6, 7200, 6)


def test_sockets_are_always_closed(patch_socket):
    sockets = patch_socket(_mbap(bytes([3, 2]) + struct.pack(">H", 1)))
    client = ModbusTCPClient("192.168.1.50", 502, 1)
    client.read_holding(400, 1)
    assert all(sock.closed for sock in sockets)


def test_error_rate_reflects_failures(patch_socket):
    patch_socket(b"", raise_on_recv=TimeoutError)
    client = ModbusTCPClient("192.168.1.50", 502, 1)
    with pytest.raises(ModbusError):
        client.read_holding(400, 1)
    stats = client.stats()
    assert stats["transactions"] == 3
    assert stats["errors"] == 3
    assert stats["error_rate"] == 100.0


@pytest.mark.parametrize("count", [0, -1, 126, 1000])
def test_count_outside_the_protocol_limits_is_refused(count):
    """Function 3 carries at most 125 registers; asking for more is a bug, not a read."""
    client = ModbusTCPClient("192.168.1.50", 502, 1)
    with pytest.raises(ValueError, match="count must be between 1 and 125"):
        client.read_holding(400, count)
