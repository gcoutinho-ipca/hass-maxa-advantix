# Troubleshooting

## Setup fails with "could not read the state register"

The integration probes register 200 before creating the entry, so this means no
Modbus reply arrived. In order of likelihood:

1. **Wrong Modbus id.** Factory default is 1. On machines wired in a network it is
   set by parameter H126.
2. **Wrong port.** Usually 502, but some gateways ship on 8899 or 4196.
3. **Gateway serial settings.** These controllers are commonly 9600 baud, 8 data
   bits, no parity, 1 stop bit. A gateway configured for 19200 will connect over
   TCP and time out on every read, which looks like a dead machine.
4. **A and B swapped** on the RS-485 pair. Harmless, and worth trying.
5. **Another master on the bus.** See below.

## Entities appear, then go unavailable at random

Look at the `Bus error rate` diagnostic sensor. On a healthy bus it sits near
zero. Anything consistently above a few percent means the transport, not the
integration.

- **Another Modbus master.** The wall controller supplied with these machines is
  itself a master. Its data lines must be disconnected. See
  [replacing-the-wall-controller.md](replacing-the-wall-controller.md).
- **Polling too fast.** A full sweep is about a dozen transactions. Below 15 s the
  bus has little idle time. Raise the interval under the integration's Configure
  button.
- **Cable and termination.** Long runs need a 120 Ω terminating resistor at each
  end of the segment, and the shield grounded at one end only.

## A sensor shows unavailable and never a value

That is usually correct behaviour. Probes that the machine does not have answer
with a sentinel value, and the integration deliberately refuses to publish those
as measurements. The most common case is the water flow sensor, which is optional
hardware and needs parameter H22=45; it is created disabled for this reason.

If you believe the probe exists, read the register directly:

```yaml
action: maxa_advantix.read_register
data:
  address: 444
response_variable: result
```

A result of 32766 or 32767 means the controller itself is reporting the probe as
unconfigured or faulty. That is a matter for the machine's own parameters, not for
Home Assistant.

## Writes appear to do nothing

Three distinct causes, easy to confuse.

**The seven second delay.** The controller reflects a write in the readable
register about seven seconds later. The integration schedules a second refresh for
this, but if you are reading registers by hand, read them again after ten seconds
before concluding anything.

**The machine refused it.** Some values are legal to write and still refused: a
dry-contact input forcing cooling will make the machine decline heating modes. The
next poll shows the state it actually took. This is the machine's decision and the
UI is reporting it honestly.

**Mode set but no call raised.** The state selects the mode; the call is what makes
the machine run. If you wrote the state register directly, through the `select`
entity or the `set_mode` service, and nothing happened, check the two call
switches. The `climate` and `water_heater` entities handle this for you, which is
why they are the recommended controls.

## The compressor starts and stops every few minutes

Short cycling. Check, in order:

1. **Water ΔT.** Above 8 K sustained means a flow restriction, and a restricted
   circuit reaches its temperature limit quickly, stops, cools, and starts again.
   See [alarms.md](alarms.md) for what to check.
2. **Mode switches.** If the counter climbs by more than a few per hour, something
   is changing the machine's mode constantly. Two controllers with different
   opinions is the usual cause: a leftover script, the generic `modbus`
   integration, or the wall controller still wired.
3. **The narrow internal differential.** The controller's own hysteresis is not
   exposed over Modbus and on many installations it is tight. The
   `dhw_hysteresis` blueprint exists to take that decision away from the
   controller. See [blueprints.md](blueprints.md).

## Everything is confusing and I want the machine back

Press **Release control**. It clears the command, state and enable registers, and
the controller returns to its own settings and its own panel. Nothing in the
machine's configuration is changed by this integration, so that is a complete
retreat.

## Filing a useful bug report

Attach a diagnostics download: **Settings, Devices and services, MAXA, three-dot
menu, Download diagnostics.** It contains the last full reading, the decoded
alarms, the blocks being polled and the bus counters. There is nothing secret in
it: host, port and Modbus id are the whole configuration, and a local IP address is
what makes the report readable.

Please also include the controller model and firmware revision from the machine's
own panel, since register and alarm maps differ between generations.

To capture the conversation itself, raise the log level:

```yaml
logger:
  default: warning
  logs:
    custom_components.maxa_advantix: debug
```
