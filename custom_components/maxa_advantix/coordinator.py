"""The single door to the bus.

One `DataUpdateCoordinator` per config entry gives **single-master discipline by
construction**: every entity shares this object and none of them opens a socket
of its own. That is not code tidiness, it is the central lesson of the
investigation this integration grew out of: two masters on the same RS-485
segment corrupted telemetry for weeks, producing plausible-looking readings that
were pure interference.

Reads happen in contiguous blocks (one Modbus transaction per block, not per
register), sentinel values are filtered at the source, and the derived values
that turned out to matter in the field (water ΔT, thermal power, mode switch
count) are computed once here instead of in every user's templates.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import health, safe_write, states
from .alarms import count as count_alarms
from .alarms import decode as decode_alarms
from .const import (
    DOMAIN,
    KEY_ACTIVE_ALARMS,
    KEY_ALARM_COUNT,
    KEY_ALARM_REGISTERS,
    KEY_BUS,
    KEY_COMMAND,
    KEY_DELTA_T,
    KEY_MACHINE_STATE,
    KEY_MODE_SWITCHES,
    KEY_SWITCHES_PER_HOUR,
    SENTINELS,
)
from .modbus_client import ModbusError, ModbusTCPClient
from .registers import (
    ALARM_FIRST_REGISTER,
    COMMAND_REGISTER,
    DEFROST_BIT_REQUESTED,
    DEFROST_BIT_RUNNING,
    DEFROST_REGISTER,
    LEGIONELLA_BIT_FAILED,
    LEGIONELLA_BIT_RUNNING,
    LEGIONELLA_REGISTER,
    READ_BLOCKS,
    READ_REGISTERS,
    WATER_HEAT_CAPACITY,
)
from .safe_write import CMD_AMBIENT, CMD_DHW

_LOGGER = logging.getLogger(__name__)

# The controller reflects a write in the readable register with a measured delay
# of about seven seconds. An immediate refresh reads the old value and the UI
# appears to reject the change; this delayed second refresh confirms it.
WRITE_REFLECT_DELAY = 8.0


class MaxaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the whole machine once per scan interval and owns all writes."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: ModbusTCPClient,
        scan_interval: int,
        read_only: bool = False,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.entry = entry
        self.client = client
        self.read_only = read_only
        # Platforms actually set up, remembered so unload matches setup even after
        # the read-only option has already changed. Filled in by `async_setup_entry`.
        self.platforms: list[str] = []
        # Mode switch counter since startup. This is the metric that exposed the
        # original fault (286 switches in 48 h). Kept in memory only; long-term
        # statistics are Home Assistant's job, not ours.
        self._last_state: int | None = None
        self._mode_switches = 0
        self._last_mode_change: datetime | None = None
        # Timestamps of recent mode changes, for the per-hour rate. A deque rather
        # than a counter because the rate is what distinguishes a machine that
        # alternates normally from one that is thrashing, and a total cannot.
        self._switch_times: deque[datetime] = deque(maxlen=512)
        # Serialises writes against each other and against the read cycle.
        self._lock = asyncio.Lock()
        # Handle for the delayed post-write refresh, so it can be cancelled. A
        # timer that outlives the config entry is a leak, and it fires against a
        # coordinator nobody is listening to any more.
        self._pending_refresh: CALLBACK_TYPE | None = None

    # ── write side ────────────────────────────────────────────────────────────
    async def _write(self, func, *args: Any) -> None:
        """Run a `safe_write` operation in the executor, under lock, then refresh.

        Every write goes through here: one queue, one master, no interleaving
        with the poll cycle. It is also the single place where read-only mode is
        enforced, which is what makes that mode trustworthy: the write platforms
        are not created at all, and even an entity left behind by an earlier
        install cannot get past this point.
        """
        if self.read_only:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="read_only"
            )
        async with self._lock:
            await self.hass.async_add_executor_job(func, self.client, *args)
        # Immediate refresh (state and calls appear quickly) plus a delayed one
        # (setpoints take ~7 s to show up in the readable register).
        await self.async_request_refresh()
        self._cancel_pending_refresh()
        self._pending_refresh = async_call_later(
            self.hass, WRITE_REFLECT_DELAY, self._delayed_refresh
        )

    @callback
    def _cancel_pending_refresh(self) -> None:
        """Drop any delayed refresh still waiting to fire."""
        if self._pending_refresh is not None:
            self._pending_refresh()
            self._pending_refresh = None

    @callback
    def _delayed_refresh(self, _now: Any = None) -> None:
        self._pending_refresh = None
        self.hass.async_create_task(self.async_request_refresh())

    async def async_shutdown(self) -> None:
        """Cancel the delayed refresh and drop any repair issue we raised."""
        self._cancel_pending_refresh()
        health.async_clear(self.hass, self.entry.entry_id)
        await super().async_shutdown()

    async def async_set_state(self, state: int) -> None:
        """Write the raw machine state, leaving calls untouched."""
        await self._write(safe_write.apply_state, state)

    async def async_set_calls(self, ambient: bool, dhw: bool) -> None:
        """Write both remote calls at once (they share register 7202)."""
        await self._write(safe_write.apply_calls, ambient, dhw)

    async def async_set_conditioning(self, mode: states.Conditioning) -> None:
        """Change the space-conditioning half of the state, preserving DHW.

        Also raises or drops the ambient call to match: selecting `heat` with no
        call would leave a correctly configured machine sitting idle.
        """
        state = states.with_conditioning(self.current_state, mode)
        _, dhw = states.decompose(state)
        await self._write(
            safe_write.apply_state_and_calls, state, mode != "off", dhw and self.dhw_call
        )

    async def async_set_dhw_enabled(self, enabled: bool) -> None:
        """Change the DHW half of the state, preserving space conditioning."""
        state = states.with_dhw(self.current_state, enabled)
        conditioning, _ = states.decompose(state)
        await self._write(
            safe_write.apply_state_and_calls,
            state,
            conditioning != "off" and self.ambient_call,
            enabled,
        )

    async def async_set_setpoint(self, address: int, raw: int) -> None:
        """Write one setpoint, validated against the manufacturer's range."""
        await self._write(safe_write.apply_setpoint, address, raw)

    async def async_start_legionella(self) -> None:
        """Start the anti-legionella cycle."""
        await self._write(safe_write.start_legionella)

    async def async_release(self) -> None:
        """Clear command, state and enable registers; hand control back."""
        await self._write(safe_write.release)

    # ── convenience views over the last reading ───────────────────────────────
    @property
    def current_state(self) -> int | None:
        """Raw value of register 200, or None if it has not been read."""
        if not self.data:
            return None
        return self.data.get(KEY_MACHINE_STATE)

    @property
    def ambient_call(self) -> bool:
        return bool((self.data or {}).get(KEY_COMMAND, 0) & CMD_AMBIENT)

    @property
    def dhw_call(self) -> bool:
        return bool((self.data or {}).get(KEY_COMMAND, 0) & CMD_DHW)

    # ── read side ─────────────────────────────────────────────────────────────
    async def _async_update_data(self) -> dict[str, Any]:
        try:
            async with self._lock:
                data = await self.hass.async_add_executor_job(self._read_all)
        except ModbusError as err:
            raise UpdateFailed(str(err)) from err

        # Installation problems are checked here rather than in an entity, because
        # they are about the setup and not about the machine, and because the user
        # needs to be told rather than to go looking.
        bus = data[KEY_BUS]
        health.async_check(
            self.hass,
            self.entry.entry_id,
            error_rate=float(bus.get("error_rate", 0.0)),
            transactions=int(bus.get("transactions", 0)),
            switches_per_hour=data[KEY_SWITCHES_PER_HOUR],
        )
        return data

    def _read_all(self) -> dict[str, Any]:
        """Blocking. Runs in the executor. Reads every block and builds the dict."""
        raw: dict[int, int] = {}
        for block in READ_BLOCKS:
            for offset, value in enumerate(self.client.read_holding(block.start, block.count)):
                raw[block.start + offset] = value

        data: dict[str, Any] = {}

        # 1. declared registers, scaled, with sentinels filtered out
        for register in READ_REGISTERS:
            value = raw.get(register.address)
            if value is None or (register.sentinel and value in SENTINELS):
                # An absent probe is not a measurement of zero. None makes the
                # entity unavailable, which is the honest answer.
                data[register.key] = None
                continue
            data[register.key] = (
                round(value * register.scale, 2) if register.scale != 1.0 else value
            )

        # 2. alarm words: masked to unsigned because bit 15 is in use
        words = [raw.get(ALARM_FIRST_REGISTER + i, 0) & 0xFFFF for i in range(3)]
        data[KEY_ALARM_REGISTERS] = words
        data[KEY_ACTIVE_ALARMS] = decode_alarms(words)
        data[KEY_ALARM_COUNT] = count_alarms(words)

        # 3. status bitmaps: defrost and anti-legionella
        defrost = raw.get(DEFROST_REGISTER, 0) & 0xFFFF
        data["defrost_requested"] = bool(defrost & (1 << DEFROST_BIT_REQUESTED))
        data["defrost_running"] = bool(defrost & (1 << DEFROST_BIT_RUNNING))
        legionella = raw.get(LEGIONELLA_REGISTER, 0) & 0xFFFF
        data["legionella_running"] = bool(legionella & (1 << LEGIONELLA_BIT_RUNNING))
        data["legionella_failed"] = bool(legionella & (1 << LEGIONELLA_BIT_FAILED))

        # 4. active remote calls (7202 read back)
        data[KEY_COMMAND] = raw.get(COMMAND_REGISTER, 0) & 0xFFFF

        # 5. derived: water ΔT, only when both probes answered
        inlet, outlet = data.get("water_inlet"), data.get("water_outlet")
        data[KEY_DELTA_T] = (
            round(outlet - inlet, 1) if inlet is not None and outlet is not None else None
        )

        # 6. derived: thermal power. Requires a real flow reading. Computing it
        # from a sentinel is exactly how the old setup reported 23 546 kW.
        flow = data.get("flow_rate")
        delta_t = data[KEY_DELTA_T]
        data["thermal_power"] = (
            round(flow / 60 * WATER_HEAT_CAPACITY * delta_t, 2)
            if flow is not None and flow > 0 and delta_t is not None
            else None
        )

        # 7. mode switches: transitions of register 200, as a total and a rate
        state = data.get(KEY_MACHINE_STATE)
        if state is not None:
            if self._last_state is not None and state != self._last_state:
                now = dt_util.utcnow()
                self._mode_switches += 1
                self._last_mode_change = now
                self._switch_times.append(now)
            self._last_state = state
        data[KEY_MODE_SWITCHES] = self._mode_switches
        data["last_mode_change"] = self._last_mode_change
        data[KEY_SWITCHES_PER_HOUR] = self._switches_per_hour()

        # 8. bus health counters
        data[KEY_BUS] = self.client.stats()
        return data

    def _switches_per_hour(self) -> int:
        """Mode changes in the last hour, with older ones discarded."""
        cutoff = dt_util.utcnow() - timedelta(hours=1)
        while self._switch_times and self._switch_times[0] < cutoff:
            self._switch_times.popleft()
        return len(self._switch_times)
