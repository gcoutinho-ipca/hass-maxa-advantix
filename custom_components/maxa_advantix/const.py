"""Constants for the MAXA / Advantix integration (i-HWAK V4 and relatives)."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "maxa_advantix"

# ── configuration keys ────────────────────────────────────────────────────────
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_SLAVE: Final = "slave"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_MODEL: Final = "model"

DEFAULT_PORT: Final = 502
DEFAULT_SLAVE: Final = 1
DEFAULT_SCAN_INTERVAL: Final = 30  # seconds
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 600

# Controller generations this integration has been reported to work with. Only
# the V4 register/alarm map is verified first-hand; the others share the same
# Modbus interface per the manufacturer documentation, so they are offered but
# flagged as unverified in the docs.
DEFAULT_MODEL: Final = "i-HWAK V4"
MODELS: Final = (
    "i-HWAK V4",
    "i-HWAK V3",
    "i-HWAK V2+",
    "i-HWAK V2",
    "iHP",
    "iHPLT",
    "Other",
)

MANUFACTURER: Final = "MAXA"

# ── Modbus transport ──────────────────────────────────────────────────────────
# Socket timeout per Modbus transaction, in seconds.
MODBUS_TIMEOUT: Final = 8.0
# Retries per read: RTU-to-TCP gateways in this family return sporadic timeouts
# and a single miss must not mark the whole machine as unavailable.
MODBUS_RETRIES: Final = 3

# 16-bit sentinel values meaning "probe absent / faulty / not configured".
# These must never reach an entity as if they were a measurement: publishing
# 32766 as a flow rate is what produced a 23 546 kW thermal power reading in the
# generic-modbus setup this integration replaces.
SENTINELS: Final = frozenset({32766, 32767, -32768, -32767, -32640, 65535})

# ── machine state (register 200 read / 7200 write) ────────────────────────────
# The slugs below are part of the public API: they show up in automations,
# history and templates. They stay in English and stable; the human-readable
# text lives in translations.
STATE_STANDBY: Final = "standby"
STATE_COOLING: Final = "cooling"
STATE_HEATING: Final = "heating"
STATE_DHW: Final = "dhw"
STATE_COOLING_DHW: Final = "cooling_dhw"
STATE_HEATING_DHW: Final = "heating_dhw"

MACHINE_STATES: Final[dict[int, str]] = {
    0: STATE_STANDBY,
    1: STATE_COOLING,
    2: STATE_HEATING,
    4: STATE_DHW,
    5: STATE_COOLING_DHW,
    6: STATE_HEATING_DHW,
}
MACHINE_STATE_VALUES: Final[dict[str, int]] = {v: k for k, v in MACHINE_STATES.items()}

# ── coordinator data keys ─────────────────────────────────────────────────────
KEY_MACHINE_STATE: Final = "machine_state"
KEY_ALARM_REGISTERS: Final = "alarm_registers"
KEY_ACTIVE_ALARMS: Final = "active_alarms"
KEY_ALARM_COUNT: Final = "alarm_count"
KEY_MODE_SWITCHES: Final = "mode_switches"
KEY_COMMAND: Final = "command"
KEY_BUS: Final = "bus"
KEY_DELTA_T: Final = "delta_t"
