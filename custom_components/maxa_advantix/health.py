"""Installation problems worth interrupting the user about.

The distinction this module rests on: a machine *state* is telemetry, and belongs in
a sensor where the user finds it when they go looking. An installation *problem* is
different, because the user does not know to go looking, and the integration is in a
position to recognise it.

Two problems qualify, and both are the ones that cost this project weeks before it
knew what it was looking at:

* **A degraded bus.** A sustained Modbus error rate means the transport, not the
  machine. Usually a second master on the same RS-485 segment; sometimes cabling or
  missing termination.
* **Mode thrashing.** A machine changing operating mode dozens of times an hour is
  a machine whose three-way valve never finishes travelling, and the usual cause is
  two controllers with different opinions. This is the metric that finally explained
  a fault that had been blamed on a valve, a sensor and a firmware bug in turn.

Both are raised as repair issues rather than as log lines, because a log line
nobody reads is the same as no diagnosis at all. Both clear themselves when the
condition goes away, so a one-off blip does not leave a permanent scar in the UI.
"""

from __future__ import annotations

from typing import Final

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

#: Error rate, in percent, above which the bus is considered unhealthy.
#:
#: Chosen well above the noise floor. Healthy gateways of this kind sit at zero and
#: return the occasional timeout under load, which lands around 1 to 2 %. Ten
#: percent is not a bad day; it is something wrong.
BUS_ERROR_THRESHOLD: Final = 10.0

#: Ignore the rate until enough transactions have happened for it to mean anything.
#: One failure out of the first three reads is 33 % and tells you nothing.
BUS_MIN_TRANSACTIONS: Final = 60

#: Mode changes per hour above which the machine is thrashing.
#:
#: A three-way valve takes about a minute to travel, so a machine that genuinely
#: needs to alternate cannot usefully do it more than a handful of times an hour.
#: The installation that prompted this counted 286 changes in 48 hours, about six an
#: hour, sustained. Twelve is comfortably clear of any legitimate pattern while
#: still catching that case as it worsens.
MODE_THRASHING_THRESHOLD: Final = 12

ISSUE_BUS_ERRORS: Final = "bus_errors"
ISSUE_MODE_THRASHING: Final = "mode_thrashing"


@callback
def async_check(
    hass: HomeAssistant,
    entry_id: str,
    *,
    error_rate: float,
    transactions: int,
    switches_per_hour: float,
) -> None:
    """Raise or clear the installation-problem issues for one entry."""
    _update(
        hass,
        entry_id,
        ISSUE_BUS_ERRORS,
        active=transactions >= BUS_MIN_TRANSACTIONS and error_rate >= BUS_ERROR_THRESHOLD,
        placeholders={
            "error_rate": f"{error_rate:.1f}",
            "threshold": f"{BUS_ERROR_THRESHOLD:.0f}",
        },
    )
    _update(
        hass,
        entry_id,
        ISSUE_MODE_THRASHING,
        active=switches_per_hour >= MODE_THRASHING_THRESHOLD,
        placeholders={
            "switches": f"{switches_per_hour:.0f}",
            "threshold": f"{MODE_THRASHING_THRESHOLD}",
        },
    )


@callback
def _update(
    hass: HomeAssistant,
    entry_id: str,
    issue: str,
    *,
    active: bool,
    placeholders: dict[str, str],
) -> None:
    """Create the issue while the condition holds, delete it once it does not."""
    issue_id = f"{issue}_{entry_id}"
    if not active:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        # Not a warning: both of these are things that make the data wrong, and
        # wrong data that looks right is worse than no data.
        severity=ir.IssueSeverity.ERROR,
        translation_key=issue,
        translation_placeholders=placeholders,
    )


@callback
def async_clear(hass: HomeAssistant, entry_id: str) -> None:
    """Drop every issue for an entry, on unload or removal."""
    for issue in (ISSUE_BUS_ERRORS, ISSUE_MODE_THRASHING):
        ir.async_delete_issue(hass, DOMAIN, f"{issue}_{entry_id}")
