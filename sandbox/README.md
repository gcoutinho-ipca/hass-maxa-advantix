# Sandbox

A throwaway Home Assistant with a simulated heat pump behind it. Nothing here
touches real hardware.

```bash
cd sandbox
docker compose up -d
# http://localhost:8123
```

Then add the integration from the UI. The gateway address is **`maxa-sim`** and the
port is **502**.

## Why bother

Three problems this solves, in order of how often they bite.

**You cannot test against a real heat pump.** Not safely, not repeatedly, and not
at two in the morning. A heat pump takes twenty minutes to show you the
consequence of a change, and some consequences you only want to see once.

**Faults are hard to arrange on purpose.** The most useful thing this integration
does is notice a restricted water circuit, and the only way to check that it still
notices is to have a machine with a restricted water circuit. The simulator raises
the fault on request.

**What you develop is not what a user installs.** A bind-mounted working tree hides
a file missing from the release zip, or a manifest version that disagrees with the
tag. `install-from-github.sh` fetches the published artefact instead, so those
failures surface here rather than in someone's issue.

## Writes are refused, by construction

The simulator runs with `--read-only` by default. Every write gets a Modbus
exception and a log line. This is not a promise that the integration behaves; it is
a machine that cannot be commanded, which is a different and better guarantee.

To prove nothing was written:

```bash
docker compose logs maxa-sim | grep -E 'REFUSED|wrote'
```

Silence is the expected result.

Setting up the integration with **Read-only mode** ticked gives you the same
guarantee from the other side: the control platforms are never created, and the
coordinator refuses writes even if an entity survives from an earlier install. Use
both when you only want telemetry, or when the machine's own wall controller is
still in charge.

To exercise the control side deliberately, drop the flag:

```bash
MAXA_SIM_ARGS="" docker compose up -d --force-recreate maxa-sim
```

## Simulating faults

```bash
# a restricted water circuit: wide ΔT, and the fault the machine raises for it
MAXA_SIM_ARGS="--read-only --fault E042 --flow-meter" \
  docker compose up -d --force-recreate maxa-sim
```

Within a poll cycle you should see water ΔT above the tolerated 8 K, **Flow
restricted** on, and **Active alarms** reading `E042` with the decoded description
in its attributes.

Available codes: `E006` flow switch, `E042` insufficient hot water heat exchange,
`E050` high storage temperature, `E101` I/O module offline.

`--flow-meter` pretends the optional flow meter is fitted. Without it, register 444
answers the manufacturer's "probe absent" sentinel, which is the default because it
is what most installations actually have, and because the sentinel filter is worth
exercising.

## What the simulator models

Enough to make the numbers move the way real numbers move. The tank warms at about
12 K per hour while hot water is called for and cools by standing losses when it is
not; water ΔT widens under load; the outdoor temperature drifts on a slow sine.

It also reproduces three behaviours of the real controller that are easy to get
wrong and impossible to discover without hardware:

- **Holding and input registers are mirrored.** Functions 3 and 4 answer from the
  same table, as the real RTU-to-TCP gateways do.
- **Writes need their enable bit.** A setpoint written without setting the matching
  bit in register 7201 is accepted on the wire and silently ignored, which is the
  single most common reason people conclude that Modbus writing "does not work" on
  these machines.
- **The state register refuses illegal values.** Anything outside `{0,1,2,4,5,6}`
  comes back as a Modbus exception.

## Installing the way a user does

```bash
./install-from-github.sh            # the latest release, zip asset first
./install-from-github.sh v1.0.0     # a specific tag
./install-from-github.sh main       # the branch as a tarball
```

Then comment out the `custom_components` bind mount in `docker-compose.yml`,
otherwise the working tree keeps shadowing what you installed, and restart:

```bash
docker compose restart homeassistant
```

## Housekeeping

```bash
docker compose logs -f homeassistant     # follow the integration's debug log
docker compose down                      # stop, keep the config
docker compose down -v && rm -rf ha-config/.storage   # start clean
```

`ha-config/.storage` holds the sandbox's users and config entries. It is
gitignored, along with everything else Home Assistant generates.

The Home Assistant port is published on `127.0.0.1` only, and the simulator's port
is not published at all. Neither needs to be reachable from your network, and a
Modbus port on a host interface is the one thing [SECURITY.md](../SECURITY.md) asks
people not to create.
