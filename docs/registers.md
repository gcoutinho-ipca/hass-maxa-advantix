# Register map

Addresses here are the register numbers as printed in the manufacturer's Modbus
table for the i-HWAK V4, used directly with no off-by-one adjustment. Everything
is read with function 3 (holding registers).

One gateway behaviour worth knowing before you go hunting: RTU-to-TCP gateways in
this family answer functions 3 and 4 from the same memory block. Register 405
returns the same value either way. That is why this integration reads everything
with function 3 and never asks you which `input_type` a register wants.

## How reads are grouped

Reading one register at a time is the obvious approach and the wrong one. At
9600 baud each Modbus transaction costs roughly 15 to 40 ms of line time, so 20
individual reads cost noticeably more than the twelve block reads below, and the
bus is the scarce resource here, not CPU.

| Block | Start | Count | Contents |
| --- | --- | --- | --- |
| `state` | 200 | 1 | Machine state |
| `cooling_circuit` | 253 | 2 | Evaporation, condensation |
| `compressor` | 305 | 1 | Compressor hours |
| `water` | 400 | 15 | Inlet, outlet, tank, pressures |
| `refrigerant` | 422 | 14 | Suction, outdoor, discharge |
| `flow` | 444 | 1 | Water flow |
| `alarms` | 950 | 3 | Alarm words |
| `actuators` | 7000 | 2 | Fan, circulator |
| `command` | 7202 | 1 | Active remote calls |
| `setpoints` | 7203 | 3 | Cooling, heating, hot water |
| `defrost` | 7214 | 1 | Defrost status bits |
| `legionella` | 7216 | 1 | Anti-legionella status bits |

## Read registers

| Register | Quantity | Scale | Entity | Notes |
| --- | --- | --- | --- | --- |
| 200 | Machine state | 1 | `sensor`, `select`, and both `climate` and `water_heater` | Enum, see below |
| 253 | Evaporation temperature | 0.1 | `sensor`, disabled | Diagnostic |
| 254 | Condensation temperature | 0.1 | `sensor`, disabled | Diagnostic |
| 305 | Compressor hours | 1 | `sensor` | Total increasing |
| 400 | Water inlet | 0.1 | `sensor` | |
| 401 | Water outlet | 0.1 | `sensor`, `climate` current temperature | The working probe. The controller's high-temperature limit watches this one |
| 405 | Hot water tank | 0.1 | `sensor`, `water_heater` current temperature | |
| 406 | High pressure | 0.01 | `sensor` | bar |
| 414 | Low pressure | 0.01 | `sensor` | bar |
| 422 | Suction temperature | 0.1 | `sensor`, disabled | Diagnostic |
| 428 | Outdoor temperature | 0.1 | `sensor` | |
| 433 | Discharge temperature | 0.1 | `sensor`, disabled | Diagnostic |
| 444 | Water flow | 1 | `sensor`, disabled | l/min, optional hardware, needs parameter H22=45 |
| 950, 951, 952 | Alarm words | bitmap | See [alarms.md](alarms.md) | Read unsigned: bit 15 is in use |
| 7000 | Condenser fan | 0.1 | `sensor` | % |
| 7001 | Circulator pump | 0.1 | `sensor` | % |
| 7202 | Active remote calls | bitmap | `switch` | Read back of what was written |
| 7203 | Cooling setpoint | 0.1 | `sensor` disabled, `number`, `climate` | |
| 7204 | Heating setpoint | 0.1 | `sensor` disabled, `number`, `climate` | |
| 7205 | Hot water setpoint | 0.1 | `sensor` disabled, `number`, `water_heater` | |
| 7214 | Defrost status | bitmap | `binary_sensor` | Bit 13 requested, bit 14 running |
| 7216 | Anti-legionella status | bitmap | `binary_sensor` | Bit 5 running, bit 6 last cycle failed |

### Machine state, register 200

The register packs two independent intents into one value: what the
space-conditioning side should do, and whether hot water is allowed.

| Value | Conditioning | Hot water | Slug |
| --- | --- | --- | --- |
| 0 | off | off | `standby` |
| 1 | cooling | off | `cooling` |
| 2 | heating | off | `heating` |
| 4 | off | on | `dhw` |
| 5 | cooling | on | `cooling_dhw` |
| 6 | heating | on | `heating_dhw` |

Values 3 and 7 are refused by the controller. That packing is why `climate` and
`water_heater` cannot each simply own the register: each entity changes only its
own half and preserves the other.

The slugs are part of the public API. They appear in automations, in history and
in templates, so they stay in English and stable; the visible text comes from the
translation files.

## Write registers

| Register | Function | Range | Prerequisite |
| --- | --- | --- | --- |
| 7201 bit 0 | Enable state writing | | |
| 7201 bit 1 | Enable setpoint writing | | |
| 7201 bit 3 | Enable conditioning call | | |
| 7201 bit 4 | Enable hot water call | | |
| 7201 bit 5 | Enable anti-legionella | | |
| 7200 | Machine state | only `0,1,2,4,5,6` | 7201 bit 0 |
| 7202 bit 1 | Conditioning call | | 7201 bit 3 |
| 7202 bit 2 | Hot water call | | 7201 bit 4 |
| 7202 bit 3 | Anti-legionella cycle | hold at 1 for the whole cycle | 7201 bit 5 |
| 7203 | Cooling setpoint | 5.0 to 23.0 °C | 7201 bit 1 |
| 7204 | Heating setpoint | 25.0 to 55.0 °C | 7201 bit 1 |
| 7205 | Hot water setpoint | 25.0 to 55.0 °C | 7201 bit 1 |
| 7208 | Hot water preheater setpoint | 0.0 to 80.0 °C | 7201 bit 1 |

Three behaviours of this controller are encoded in `safe_write.py` because none of
them is guessable from the register table, and all three were established by
measurement rather than reading:

1. **Nothing is written without its enable bit.** A setpoint written without
   setting the matching bit in 7201 first is accepted on the wire and silently
   ignored by the machine. This is the single most common reason people conclude
   that "Modbus writing does not work on this pump".
2. **Order matters:** enables (7201), then state (7200), then commands (7202).
3. **State and call are different things.** The state selects the mode; the call
   is what makes the machine run. A pump set to `heating` with no conditioning
   call is correctly configured and completely idle.

There is a fourth, which only bites when you write a test: the controller reflects
a write in the readable register with a delay of about seven seconds. Reading back
immediately returns the old value, and the UI looks like it rejected your change.
The coordinator issues a second, delayed refresh for exactly this reason.

## Sentinel values

`32766`, `32767`, `-32768`, `-32767`, `-32640` and `65535` mean "probe absent,
faulty or not configured". They are filtered at the read layer and never reach an
entity: the entity goes unavailable instead, which is the honest answer.

This is not a theoretical nicety. An absent flow probe answering `32766` fed into
a thermal power template is what produced a reading of 23 546 kW on the
installation this integration was written for.

## Mapping another controller generation

Use the read-only service, which goes through the same coordinator and therefore
does not create a second master on the bus:

```yaml
action: maxa_advantix.read_register
data:
  address: 400
  count: 15
response_variable: result
```

The response contains both the signed and the unsigned view of each word. Status
and alarm registers need the unsigned one, since they use bit 15.

Findings are welcome as an issue. Please say which controller and which firmware
revision the numbers came from: the alarm bitmap of the V2/V3 family differs from
the V4 one, and knowing which map a report belongs to is half its value.
