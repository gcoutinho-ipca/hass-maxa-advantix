# Replacing the wall controller

The wall controller supplied with these machines does two jobs: it gives you a
user interface, and it acts as the Modbus master that schedules hot water and
switches the installation between heating and cooling. Home Assistant can do both,
better, but there is one hard constraint and one structural limitation to
understand first.

## The hard constraint: one master

RS-485 has exactly one master. The wall controller is one, and it can address a
network of up to seven machines. If you connect a Modbus-TCP gateway to the same
terminals and leave the wall controller wired, you have two masters talking over
each other.

This does not damage anything. It corrupts data, and it does so in a way that
looks like real readings, which is far worse than an obvious failure. Symptoms
seen on a real installation:

- A register returning the value that belongs to a completely different register.
- Spurious zeros that appear and vanish.
- A setpoint apparently oscillating between two values every few seconds.
- Occasional I/O module timeout alarms (E101).

Days can be lost attributing that to a failing sensor or a firmware bug. **Before
you begin, disconnect the wall controller's data lines**, or remove it. Then watch
the integration's `Bus error rate` sensor: on a healthy bus it stays near zero.

## The dry-contact inputs

Once the wall controller is gone, you still want a way to command the machine. You
have two, and using both is the robust choice.

**Modbus writes** give you everything: modes, setpoints, calls, the
anti-legionella cycle. They depend on the bus being up.

**Dry-contact inputs** give you the two or three commands that matter, they are
independent of the bus and of Home Assistant, and they fail safe. A relay module
such as a smart switch wired to these terminals keeps working when your server is
being updated.

| Input | Terminals | Parameter | Function |
| --- | --- | --- | --- |
| ID2 | X16.1 / X16.2 | `H46=3` | open selects cooling, closed selects heating |
| ID3 | X15.1 / X15.2 | `H47=2` | open forces standby, closed enables operation |
| ID9 | X20.1 / X20.2 | `H53=28` | closed selects hot water, open selects the installation |
| ID9E | 4.1 / 4.2 | `H63=19` | room thermostat, needs the optional interface module |

All are voltage-free contacts. `H76=1` sets the polarity and `H75=0` inverts it.

Two practical notes. ID2 and ID3 are usually active from the factory, and ID3
frequently arrives with a wire link fitted across it, which is what keeps the
machine enabled; replacing that link with a relay contact needs no parameter
change and no service password. ID9 typically arrives as `0`, meaning undefined,
and enabling it does require the installer password.

## The structural limitation: parameter H10

`H10` controls two things at once, and they are not separable.

| H10 | Hot water available in | Does the remote off input also disable hot water? |
| --- | --- | --- |
| 0 | hot water function disabled | |
| 1 | heating and cooling | no, display shows `SAN` |
| 2 | heating and cooling | yes, display shows `E00` |
| 3 | heating only | no |
| 4 | heating only | yes |
| 5 | cooling only | no |
| 6 | cooling only | yes |

The consequence is worth stating plainly: **with a single contact on ID3 you
cannot have a hot water schedule independent of the space-heating schedule.**
Either the remote off disables both, or it disables neither.

For independence you need one of:

- **Two contacts**, ID3 and ID9, so the mode and the enable are commanded
  separately.
- **Modbus writes**, which is what this integration does. The `water_heater` and
  `climate` entities each own their half of the state register, so the two
  schedules are genuinely independent with no extra wiring at all.

To find out which `H10` your machine has without entering the service menu, open
the ID3 contact and read the display: `E00` means 2, 4 or 6, and `SAN` means 1, 3
or 5.

## A migration that works

1. Disconnect the wall controller's data lines. Fit the Modbus-TCP gateway.
2. Set up this integration. Confirm the readings look sane and the bus error rate
   stays near zero. Leave it read-only for a day or two and watch the mode switch
   counter: with only one master, that number should be small.
3. Set the machine's own setpoints to sensible values from its own panel. They are
   the fallback for everything that follows.
4. Add the hot water hysteresis blueprint. Verify a full cycle: it starts, it
   reaches the target, it stops, it rests.
5. Add the rest of the blueprints one at a time, a day apart. Adding five
   automations at once and then trying to work out which one is fighting the
   machine is a bad afternoon.
6. Only now consider removing the wall controller physically.

Do not run two controllers at once. If you were previously scheduling this machine
with a script, a `pyscript` module or the generic `modbus` integration, stop it
before you enable the write entities here. Two controllers with different opinions
about hot water is the same failure as two masters, one level up.
