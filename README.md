# MAXA / Advantix heat pump for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Validate](https://github.com/gcoutinho-ipca/hass-maxa-advantix/actions/workflows/validate.yml/badge.svg)](https://github.com/gcoutinho-ipca/hass-maxa-advantix/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Local Modbus integration for **MAXA / Advantix** heat pumps with the **i-HWAK**
controller family. No cloud, no account, no outbound connection: Home Assistant
talks straight to the machine over a Modbus-TCP gateway.

You can already read these registers with Home Assistant's generic `modbus`
integration. What that cannot do is know what the numbers mean, and this is where
the difference shows up. Every row below was observed on a real installation
before this integration existed:

| What the machine reports | Generic `modbus` publishes | This integration does |
| --- | --- | --- |
| Absent flow probe answers `32766` | `32766 l/min` | Entity goes unavailable |
| A power template using that value | **23 546 kW** of thermal power | No value at all, and says why |
| 48 alarm flags in three registers | Three raw numbers | Named fault codes, `E042` and friends |
| Anti-legionella status reads `-32768` | `-32768` | Correct status bits, decoded |
| Writing `3` to the state register | Writes it; machine misbehaves | Refused: only `0,1,2,4,5,6` are legal |
| Two Modbus masters on one RS-485 bus | Silent data corruption | One coordinator, single master by design |

The value is not in reading Modbus. It is in knowing the machine.

> **Before you start:** this needs real hardware, a controller with a Modbus
> interface and ideally a Modbus-TCP gateway, see [Requirements](#requirements).
> It writes to a heating appliance and comes with **no warranty and no liability**,
> see [Disclaimer](#disclaimer).

## Supported hardware

Verified first-hand on **i-HWAK V4**. The same Modbus interface is documented for
**i-HWAK V2, V2+, V3, iHP and iHPLT**, and those are offered in the setup dialog,
but their register and alarm maps are not verified. If you own one, the
`maxa_advantix.read_register` service lets you map it safely and
[report what you find](https://github.com/gcoutinho-ipca/hass-maxa-advantix/issues).

Be aware that the alarm bitmap published for the older V2/V3 family **differs**
from the V4 one. Mixing them up sends you chasing the wrong fault, which is how
several days of this project's own diagnosis were spent.

## Requirements

This is a hardware integration. Installing it on its own does nothing at all:
there is no cloud service behind these machines and no network port on them.
Before it can read a single value you need the following.

**A machine that speaks Modbus.** The controller must expose the Modbus interface
on its RS-485 terminals. That covers the i-HWAK family and its relatives; it does
not cover older units with no serial interface at all.

**A Modbus RTU-to-TCP gateway, and this is the recommended way.** A small
"Modbus2TCP" or "RS485-to-Ethernet" converter, wired to the controller's RS-485
terminals and reachable from Home Assistant over your network. Anything that
presents standard Modbus TCP on a port works; there is nothing brand-specific
here. Typical serial settings for these controllers are 9600 baud, 8 data bits, no
parity, one stop bit, and the gateway has to be configured to match, since a
mismatch connects happily over TCP and then times out on every read.

A USB RS-485 adapter plugged into the Home Assistant machine can work too, if you
put something in front of it that presents Modbus TCP. This integration speaks
Modbus TCP only, deliberately: it keeps the transport in one small, auditable
place, and a gateway can sit next to the machine while Home Assistant runs
wherever you like.

**The bus to yourself.** The wall controller supplied with these machines is
itself a Modbus master. Two masters on one RS-485 segment do not damage anything,
but they corrupt each other's data in ways that look like real readings, so
disconnect its data lines or remove it before you begin. See
[`docs/replacing-the-wall-controller.md`](docs/replacing-the-wall-controller.md).

**A note on where to put it.** Modbus TCP has no authentication and no encryption,
which is a property of the protocol rather than a shortcoming of this integration.
Keep the gateway on your local network, never expose it to the internet, and
ideally give building services their own VLAN. See [SECURITY.md](SECURITY.md).

## Installation

### Through HACS

1. HACS, three-dot menu, **Custom repositories**.
2. Add `https://github.com/gcoutinho-ipca/hass-maxa-advantix`, category
   **Integration**.
3. Install, then restart Home Assistant.
4. **Settings, Devices and services, Add integration**, search for MAXA.

### Manually

Copy `custom_components/maxa_advantix/` into your `config/custom_components/`
directory and restart Home Assistant.

## Setup

The dialog asks for the gateway IP address, the TCP port (usually 502), the Modbus
id (1 from the factory, set by parameter H126 on machines wired in a network), the
controller model, and whether to run read-only. The connection is probed before the
entry is created, so a wrong address fails immediately instead of producing a device
full of unavailable entities.

The polling interval defaults to 30 s and can be changed under the integration's
**Configure** button. A full sweep is seven Modbus transactions and roughly 350 ms
of line time; below 15 s the bus has little idle time left and the machine's own
panel gets sluggish.

### Read-only mode

Tick it and the integration creates sensors and nothing else. No `climate`, no
`water_heater`, no switches, no buttons, and the coordinator refuses writes outright
rather than merely not offering them.

Two situations call for it. If the machine's original wall controller is still
wired, a second controller with a different opinion about hot water produces
behaviour that looks exactly like a hardware fault, so read-only lets you watch the
machine for a week before taking anything over. And if all you want is the
telemetry, this is the honest way to have it.

It can be switched later under **Configure**. That reloads the entry, so entity
history and unique ids survive.

## What you get

**Controls**

| Entity | Notes |
| --- | --- |
| `climate` | Heating and cooling. Current temperature is the outlet water, since the machine has no room probe of its own. |
| `water_heater` | Domestic hot water, with the tank temperature and the DHW setpoint. |
| `select` | The raw machine state, for setting both halves in a single write. |
| `number` | Cooling, heating, hot water and preheater setpoints, bounded by the manufacturer's ranges. |
| `switch` | The two remote calls. |
| `button` | Start the anti-legionella cycle; release control back to the machine's own panel. |

The `climate` and `water_heater` entities each own one half of the packed state
register and preserve the other. Turning the heating off cannot silently disable
hot water, which is the failure mode a naive mapping of that register produces.

**Sensors**

Water inlet and outlet, hot water tank, high and low pressure, outdoor
temperature, condenser fan, circulator pump, the three setpoints, and, disabled by
default because they are only interesting when diagnosing, suction, discharge,
evaporation and condensation temperatures plus compressor hours.

**Derived values, which is where the diagnosis lives**

- **Water ΔT**, with the manufacturer's nominal and maximum in the attributes.
  Sustained values above the maximum mean a flow restriction.
- **Flow restricted** binary sensor. This matters more than it sounds: the
  machine's own flow switch is documented as not being supervised during hot water
  production, exactly when a restricted hot water branch shows itself. On some
  installations ΔT is the only warning you get.
- **Thermal power**, computed only when a real flow reading exists.
- **Mode switches** and **last mode change**. A three-way valve needs about a
  minute to travel; a machine switching modes hundreds of times a day is one
  whose valve never finishes moving.
- **Bus error rate**, which catches a gateway that is starting to fail long before
  entities go unavailable.

**It tells you when the installation is wrong**

Two conditions raise a repair notification, in Settings, rather than a log line
nobody reads. Both are installation problems rather than machine states, which is
the distinction: you do not know to go looking for them, and the integration can
recognise them.

- **Modbus errors on the bus.** A sustained error rate means the transport, not the
  machine, and the readings may be silently wrong. The usual cause is a second
  Modbus master on the same segment.
- **Constant mode changes.** More than a dozen an hour means the three-way valve
  never finishes travelling. The usual cause is two controllers with different
  opinions: a leftover script, the generic `modbus` integration still polling, or
  the wall controller still wired.

Both clear themselves when the condition goes away.

**Alarms**

The three alarm words are decoded into named fault codes. There is one aggregate
`Alarm` sensor, an `Active alarms` sensor carrying the codes and descriptions, and
one binary sensor per documented flag. The per-flag entities are created
**disabled**: enable the two or three you actually automate on, from the device
page, and leave the rest costing nothing.

## Services

| Service | What it does |
| --- | --- |
| `maxa_advantix.set_mode` | Writes the combined machine state, validated. |
| `maxa_advantix.set_dhw_setpoint` | Writes the hot water setpoint. |
| `maxa_advantix.start_legionella` | Starts the controller's own anti-legionella cycle. |
| `maxa_advantix.release_control` | Clears command, state and enable registers. |
| `maxa_advantix.read_register` | Reads holding registers and returns the values. |

`read_register` is read-only on purpose. There is deliberately no
`write_register`: an unvalidated write to the state register is precisely what the
manufacturer warns against, and offering it would undo the point of the validation
layer.

## Blueprints

Five automation blueprints are included under
[`blueprints/automation/maxa_advantix/`](blueprints/automation/maxa_advantix).
They carry the operating logic that a driver should not: policy belongs in
automations you can see and change.

| Blueprint | What it is for |
| --- | --- |
| `dhw_hysteresis` | Hot water on a wide band of your choosing, with compressor rest and flow gating. |
| `solar_priority` | Hold hot water back on mornings when the solar forecast is good. |
| `electric_backup` | An immersion heater as last resort, behind solar and behind the pump. |
| `dhw_recirculation` | Recirculation pump with a night pause. |
| `fault_alert` | Notify on alarms, and on a sustained flow restriction. |

The hysteresis one deserves a word, because it is counter-intuitive. Set the
machine's own hot water setpoint slightly **above** the blueprint's stop value.
The machine then never reaches its own cut-off, so your wide band governs instead
of the controller's narrow internal differential, and the compressor stops short
cycling. See [`docs/blueprints.md`](docs/blueprints.md).

## Trying it without a heat pump

There is a throwaway Home Assistant and a Modbus simulator in
[`sandbox/`](sandbox):

```bash
cd sandbox && docker compose up -d      # then http://localhost:8123
```

Add the integration pointing at host `maxa-sim`, port 502. The simulator answers the
same registers with the same scales, carries a crude thermal model so the derived
sensors actually move, and can raise faults on request:

```bash
MAXA_SIM_ARGS="--read-only --fault E042 --flow-meter" \
  docker compose up -d --force-recreate maxa-sim
```

That reproduces the fault this integration was written to catch, so you can see the
water ΔT go past the tolerated maximum and **Flow restricted** turn on without
owning a machine with a blocked strainer.

It runs with writes refused by default, and it reproduces three controller
behaviours that are impossible to discover without hardware: holding and input
registers mirrored, writes silently ignored without their enable bit, and illegal
state values rejected. See [`sandbox/README.md`](sandbox/README.md).

## Example dashboard

[`examples/dashboard.yaml`](examples/dashboard.yaml) is a ready Lovelace view:
thermostat and hot water cards, the diagnostic gauges that matter, and an alarm
panel. Paste it into a new dashboard in raw configuration editor mode and adjust
the entity ids.

## Documentation

- [`docs/registers.md`](docs/registers.md): the register map, what is polled and
  why it is grouped the way it is.
- [`docs/alarms.md`](docs/alarms.md): every decoded fault code.
- [`docs/replacing-the-wall-controller.md`](docs/replacing-the-wall-controller.md):
  dry-contact inputs, the H10 coupling and its consequences.
- [`docs/troubleshooting.md`](docs/troubleshooting.md): what to check first, and
  what a diagnostics download should contain.
- [`docs/blueprints.md`](docs/blueprints.md): how the five blueprints fit
  together.

## Safety and scope

This integration writes to a heating appliance. Values are checked against the
manufacturer's documented ranges before anything reaches the bus, and the state
register only ever receives one of the six values the controller accepts. That
protects you from writing nonsense; it does not turn the machine into something it
is not. Thermal protections, compressor timers and defrost logic stay where they
belong, inside the controller.

If something looks wrong, the **Release control** button clears the command, state
and enable registers, and the machine returns to its own settings and its own
panel.

The security posture, the threat model and what is validated where are written out
in [SECURITY.md](SECURITY.md). Short version: no credentials, no cloud, no
listening socket, no file access, nothing executed, and one outbound connection to
the gateway you configured.

## Contributing

Bug reports with a diagnostics download attached are worth ten without one:
**Settings, Devices and services, MAXA, three-dot menu, Download diagnostics**.
It contains the last full reading, the decoded alarms and the bus counters, and
nothing secret.

Register maps for other controller generations are the most useful contribution
there is. Use `maxa_advantix.read_register`, and please say which controller and
which firmware revision the numbers came from.

## A note on the manufacturer's documentation

Register addresses, scales and value ranges are facts of interoperability, and
documenting them is legitimate. This repository therefore contains no manufacturer
PDFs, no verbatim tables and no copied descriptive text. Everything here is
rewritten, and cross-checked against a live machine.

This project is not affiliated with, endorsed by or supported by MAXA. Trademarks
belong to their owners.

## Disclaimer

**Use at your own risk.** This software is provided as is, without warranty of any
kind, express or implied. The author accepts **no responsibility and no liability**
for any damage, malfunction, loss, injury or cost arising from its use, including
damage to your heat pump, to your heating system or to your property, and including
consequences of a bug in this code.

It is not a product. It is not certified for anything. It is a spare-time project,
written for one installation and shared in case it is useful to yours. It writes
to a heating appliance over an industrial protocol that has no authentication, and
it is your decision whether that belongs on your machine.

If your heat pump is under warranty, connecting third-party control to it may
affect that warranty. Ask your installer before you do, not after.

## Author

gcoutinho, gcoutinho@gmail.com

## License

MIT. See [LICENSE](LICENSE). The licence's own warranty disclaimer applies in full
and is not softened by anything written elsewhere in this repository.
