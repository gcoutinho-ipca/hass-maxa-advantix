#!/usr/bin/env python3
"""A Modbus-TCP simulator that behaves like an i-HWAK controller.

Why this exists: nobody should have to own the machine to work on the integration,
and nobody should have to test against a real heat pump to find out that a change
broke the register map. It answers the same registers, with the same scales, the
same sentinel values for absent probes, and the same enable-bit behaviour, so the
integration cannot tell the difference.

It also carries a crude thermal model, which matters more than it sounds. A
simulator that returns constants makes every dashboard look correct and every
hysteresis automation untestable. This one heats the tank when hot water is called
for, lets it cool when it is not, and widens the water ΔT when it is working hard,
so the derived sensors move and the blueprints can actually be exercised.

Standard library only. No dependencies.

    python scripts/modbus_simulator.py --port 5020
    python scripts/modbus_simulator.py --port 5020 --read-only
    python scripts/modbus_simulator.py --port 5020 --fault E042 --no-flow-meter

Read-only mode returns Modbus exception 4 for every write, which is how you prove
that an integration configured for telemetry is not writing: point it here, and any
attempted write shows up in the log as a refusal instead of passing silently.
"""

from __future__ import annotations

import argparse
import logging
import math
import random
import socketserver
import struct
import threading
import time
from typing import Final

_LOGGER = logging.getLogger("maxa-sim")

# ── protocol ──────────────────────────────────────────────────────────────────
FUNC_READ_HOLDING: Final = 3
FUNC_READ_INPUT: Final = 4
FUNC_WRITE_SINGLE: Final = 6
FUNC_WRITE_MULTIPLE: Final = 16

EXC_ILLEGAL_FUNCTION: Final = 1
EXC_ILLEGAL_ADDRESS: Final = 2
EXC_ILLEGAL_VALUE: Final = 3
EXC_DEVICE_FAILURE: Final = 4

MAX_READ: Final = 125

# ── the machine ───────────────────────────────────────────────────────────────
R_STATE: Final = 200
R_ALARMS: Final = 950
R_WRITE_STATE: Final = 7200
R_ENABLE: Final = 7201
R_COMMAND: Final = 7202
R_SET_COOLING: Final = 7203
R_SET_HEATING: Final = 7204
R_SET_DHW: Final = 7205
R_DEFROST: Final = 7214
R_LEGIONELLA: Final = 7216

#: Sentinel the real controller returns for a probe that is not configured.
PROBE_ABSENT: Final = 32766

VALID_STATES: Final = frozenset({0, 1, 2, 4, 5, 6})

#: Fault code to (register, bit), for the ones worth simulating.
FAULTS: Final[dict[str, tuple[int, int]]] = {
    "E006": (950, 5),  # flow switch
    "E042": (951, 12),  # insufficient DHW heat exchange
    "E050": (951, 13),  # high DHW storage temperature
    "E101": (951, 14),  # I/O module offline
}


class HeatPump:
    """State plus a first-order thermal model, stepped once a second.

    The model is not trying to be a simulation of a refrigeration cycle. It is
    trying to make the numbers move the way a real machine's numbers move, so that
    ΔT, the mode switch counter and the hysteresis blueprints all see something
    plausible.
    """

    def __init__(self, *, flow_meter: bool = False, faults: tuple[str, ...] = ()) -> None:
        self._lock = threading.Lock()
        self.flow_meter = flow_meter
        self.faults = faults

        # User-visible state. It starts working rather than idle, so that a fresh
        # sandbox shows a machine doing something: an idle simulator makes every
        # derived sensor read zero and hides exactly the bugs worth finding.
        self.state = 6  # heating + hot water
        self.enable = 0b11  # state and setpoint writing enabled
        self.command = 0b0110  # both calls raised

        # setpoints, in raw units (°C x 10)
        self.setpoints = {R_SET_COOLING: 70, R_SET_HEATING: 450, R_SET_DHW: 470}

        # process values, in °C
        self.tank = 42.0
        self.outlet = 45.5
        self.inlet = 40.0
        self.outdoor = 18.0
        self.compressor_hours = 1042.0
        self.compressor_running = False
        self.started_at = time.monotonic()

        self.writes: list[tuple[int, int]] = []

    # ── model ─────────────────────────────────────────────────────────────────
    @property
    def dhw_selected(self) -> bool:
        return self.state in (4, 5, 6)

    @property
    def conditioning_selected(self) -> bool:
        return self.state in (1, 2, 5, 6)

    @property
    def dhw_call(self) -> bool:
        return bool(self.command & (1 << 2))

    @property
    def ambient_call(self) -> bool:
        return bool(self.command & (1 << 1))

    def step(self, seconds: float) -> None:
        """Advance the model. Called once a second by the background thread."""
        with self._lock:
            target_tank = self.setpoints[R_SET_DHW] / 10
            making_hot_water = self.dhw_selected and self.dhw_call and self.tank < target_tank
            conditioning = self.conditioning_selected and self.ambient_call

            self.compressor_running = making_hot_water or conditioning
            if self.compressor_running:
                self.compressor_hours += seconds / 3600

            if making_hot_water:
                # Roughly 12 K per hour, which is what a small machine manages
                # against a 200 litre cylinder.
                self.tank += 12.0 * seconds / 3600
            else:
                # Standing losses, plus a nudge for hot water being drawn.
                self.tank -= 1.2 * seconds / 3600
            self.tank = max(15.0, min(self.tank, 70.0))

            # Water circuit. ΔT widens with load; the "flow restricted" fault
            # widens it far enough to trip the integration's own detection, which
            # is what makes that detection testable.
            base_delta = 5.0 if self.compressor_running else 0.5
            if "E042" in self.faults or "E006" in self.faults:
                base_delta = 16.0
            wobble = 0.4 * math.sin(time.monotonic() / 20) + random.uniform(-0.1, 0.1)

            if making_hot_water:
                self.outlet = min(self.tank + 8.0 + base_delta, 57.5)
            elif conditioning:
                self.outlet = self.setpoints[R_SET_HEATING] / 10 + wobble
            else:
                self.outlet = self.inlet + base_delta
            self.inlet = self.outlet - base_delta - wobble

            self.outdoor = 18.0 + 6.0 * math.sin(time.monotonic() / 600)

    # ── register file ─────────────────────────────────────────────────────────
    def _flow_rate(self) -> int:
        if not self.flow_meter:
            return PROBE_ABSENT
        return 20 if self.compressor_running else 0

    def _alarm_words(self) -> list[int]:
        words = [0, 0, 0]
        for code in self.faults:
            if code in FAULTS:
                register, bit = FAULTS[code]
                words[register - R_ALARMS] |= 1 << bit
        return words

    def read(self, address: int) -> int:
        """Value of one register, as an unsigned 16-bit word."""
        with self._lock:
            alarms = self._alarm_words()
            table: dict[int, float | int] = {
                R_STATE: self.state,
                253: 12.0 * 10,  # evaporation
                254: 45.0 * 10,  # condensation
                305: int(self.compressor_hours),
                400: self.inlet * 10,
                401: self.outlet * 10,
                405: self.tank * 10,
                406: 24.5 * 100,  # high pressure
                414: 7.8 * 100,  # low pressure
                422: 9.5 * 10,  # suction
                428: self.outdoor * 10,
                433: (72.0 if self.compressor_running else 30.0) * 10,
                444: self._flow_rate(),
                950: alarms[0],
                951: alarms[1],
                952: alarms[2],
                7000: (85.0 if self.compressor_running else 0.0) * 10,
                7001: (100.0 if self.compressor_running else 0.0) * 10,
                R_ENABLE: self.enable,
                R_COMMAND: self.command,
                R_SET_COOLING: self.setpoints[R_SET_COOLING],
                R_SET_HEATING: self.setpoints[R_SET_HEATING],
                R_SET_DHW: self.setpoints[R_SET_DHW],
                R_DEFROST: 0,
                R_LEGIONELLA: 0,
            }
            # The real gateway answers unmapped addresses with zero rather than an
            # exception, and code that assumes otherwise breaks against it.
            value = int(round(table.get(address, 0)))
            return value & 0xFFFF

    def write(self, address: int, value: int) -> int | None:
        """Apply a write. Returns a Modbus exception code, or None on success."""
        with self._lock:
            self.writes.append((address, value))

            if address == R_ENABLE:
                self.enable = value
                return None
            if address == R_WRITE_STATE:
                if not self.enable & 1:
                    _LOGGER.warning(
                        "state write to %d ignored: enable bit 0 is not set "
                        "(this is what the real controller does)",
                        address,
                    )
                    return None
                if value not in VALID_STATES:
                    _LOGGER.warning("refusing illegal state %d", value)
                    return EXC_ILLEGAL_VALUE
                self.state = value
                return None
            if address == R_COMMAND:
                self.command = value
                return None
            if address in self.setpoints:
                if not self.enable & 2:
                    _LOGGER.warning(
                        "setpoint write to %d ignored: enable bit 1 is not set", address
                    )
                    return None
                self.setpoints[address] = value
                return None

            _LOGGER.info("write to unmapped register %d accepted and ignored", address)
            return None


class ModbusHandler(socketserver.BaseRequestHandler):
    """One connection. The gateway serialises the bus, so concurrency is fine here."""

    def handle(self) -> None:
        peer = f"{self.client_address[0]}:{self.client_address[1]}"
        _LOGGER.debug("connection from %s", peer)
        try:
            while True:
                header = self._recv_exactly(7)
                if header is None:
                    return
                transaction, _protocol, length, unit = struct.unpack(">HHHB", header)
                body = self._recv_exactly(length - 1)
                if body is None:
                    return
                reply = self._dispatch(unit, body)
                if reply is not None:
                    self.request.sendall(
                        struct.pack(">HHHB", transaction, 0, len(reply) + 1, unit) + reply
                    )
        except (OSError, struct.error) as err:
            _LOGGER.debug("connection %s ended: %s", peer, err)

    def _recv_exactly(self, length: int) -> bytes | None:
        chunks = []
        remaining = length
        while remaining > 0:
            chunk = self.request.recv(remaining)
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _dispatch(self, unit: int, body: bytes) -> bytes | None:
        server: SimulatorServer = self.server  # type: ignore[assignment]
        pump = server.pump
        function = body[0]

        if unit not in (server.slave, 0, 255):
            _LOGGER.debug("ignoring request for slave %d", unit)
            return None

        # Holding and input registers are mirrored, exactly as the real RTU-to-TCP
        # gateways in this family do. Integrations that guess the wrong input_type
        # still work, which is why nobody notices.
        if function in (FUNC_READ_HOLDING, FUNC_READ_INPUT):
            address, count = struct.unpack(">HH", body[1:5])
            if not 1 <= count <= MAX_READ:
                return self._exception(function, EXC_ILLEGAL_VALUE)
            values = b"".join(
                struct.pack(">H", pump.read(address + offset)) for offset in range(count)
            )
            return bytes([function, len(values)]) + values

        if function == FUNC_WRITE_SINGLE:
            address, value = struct.unpack(">HH", body[1:5])
            if server.read_only:
                _LOGGER.warning(
                    "REFUSED write of %d to register %d: simulator is read-only",
                    value,
                    address,
                )
                server.refused_writes.append((address, value))
                return self._exception(function, EXC_DEVICE_FAILURE)
            error = pump.write(address, value)
            if error is not None:
                return self._exception(function, error)
            _LOGGER.info("wrote %d to register %d", value, address)
            return bytes([function]) + struct.pack(">HH", address, value)

        if function == FUNC_WRITE_MULTIPLE:
            address, count = struct.unpack(">HH", body[1:5])
            if server.read_only:
                _LOGGER.warning("REFUSED multi-write at %d: simulator is read-only", address)
                server.refused_writes.append((address, -1))
                return self._exception(function, EXC_DEVICE_FAILURE)
            payload = body[6:]
            for offset in range(count):
                (value,) = struct.unpack(">H", payload[offset * 2 : offset * 2 + 2])
                pump.write(address + offset, value)
            return bytes([function]) + struct.pack(">HH", address, count)

        _LOGGER.warning("unsupported function %d", function)
        return self._exception(function, EXC_ILLEGAL_FUNCTION)

    @staticmethod
    def _exception(function: int, code: int) -> bytes:
        return bytes([function | 0x80, code])


class SimulatorServer(socketserver.ThreadingTCPServer):
    """Threaded so several clients can poll at once, like a real gateway."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, pump: HeatPump, slave: int, read_only: bool) -> None:
        super().__init__(address, ModbusHandler)
        self.pump = pump
        self.slave = slave
        self.read_only = read_only
        self.refused_writes: list[tuple[int, int]] = []


def _model_thread(pump: HeatPump, stop: threading.Event) -> None:
    last = time.monotonic()
    while not stop.wait(1.0):
        now = time.monotonic()
        pump.step(now - last)
        last = now


def main() -> int:
    """Run the simulator until interrupted."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Binds everything by default because the usual home is a container, where
    # binding the loopback would make it unreachable from Home Assistant. The
    # compose file does not publish the port to the host.
    parser.add_argument(
        "--host",
        default="0.0.0.0",  # noqa: S104
        help="address to bind (default all interfaces)",
    )
    parser.add_argument("--port", type=int, default=5020, help="TCP port (default 5020)")
    parser.add_argument("--slave", type=int, default=1, help="Modbus id (default 1)")
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="refuse every write with a Modbus exception, and log the attempt",
    )
    parser.add_argument(
        "--flow-meter",
        action="store_true",
        help="pretend the optional flow meter is fitted (otherwise it reads 32766)",
    )
    parser.add_argument(
        "--fault",
        action="append",
        default=[],
        choices=sorted(FAULTS),
        help="raise a fault code; repeatable",
    )
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )

    pump = HeatPump(flow_meter=args.flow_meter, faults=tuple(args.fault))
    stop = threading.Event()
    threading.Thread(target=_model_thread, args=(pump, stop), daemon=True).start()

    server = SimulatorServer((args.host, args.port), pump, args.slave, args.read_only)
    mode = "READ-ONLY (writes refused)" if args.read_only else "read/write"
    _LOGGER.info(
        "i-HWAK simulator on %s:%d, slave %d, %s%s%s",
        args.host,
        args.port,
        args.slave,
        mode,
        ", flow meter fitted" if args.flow_meter else ", no flow meter",
        f", faults {','.join(args.fault)}" if args.fault else "",
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _LOGGER.info("stopping")
    finally:
        stop.set()
        server.shutdown()
        if server.refused_writes:
            _LOGGER.info("refused %d write attempt(s)", len(server.refused_writes))
        elif args.read_only:
            _LOGGER.info("no write was ever attempted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
