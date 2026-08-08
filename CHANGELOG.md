# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing here changes how the integration talks to a machine. The released zip
contains `custom_components/` only, so the dashboard fix below was never
distributed through HACS: it was wrong in the repository, which is where people
copy it from.

### Fixed

- **The flow restriction check fired on healthy machines that were simply idle.**
  ΔT above the tolerated maximum only means restricted flow while water is being
  pumped. With the circulator stopped the inlet and outlet probes sit in still water
  at different heights of the circuit and drift apart on their own: a real
  installation was found at 10.5 K against a limit of 8 with the pump and fan both at
  0 %, with the sensor on and no fault present. The alert blueprint would have sent
  that, and the first false alert is what teaches somebody to ignore the next real
  one.

  The check is now gated twice: the pump must be running, and it must have been
  running long enough for the water between the two probes to have been replaced,
  three minutes by default. Stopping the pump restarts that clock, so a machine that
  cycles cannot inherit credit from its previous run. The attributes distinguish
  "no restriction" from "cannot tell yet", which an `off` state alone cannot.

  `flow_restricted` is now derived once in the coordinator instead of being
  recomputed by each entity. The ΔT sensor's attribute of the same name used the
  looser rule, so the two could contradict each other on the same dashboard.
- **The example dashboard referenced seven entities that do not exist**, including
  the three most prominent cards on it: the delta T gauge, the tank reading and the
  hot water setpoint. The suffixes had been written from the register keys, while
  entity ids come from the translated entity names, and nothing checked across the
  two. Nothing validates a Lovelace YAML either: Home Assistant renders an unknown
  entity as "Entity not found" and carries on.

### Added

- `tests/test_dashboard.py` loads the integration, reads the entity registry and
  checks every reference in the example against it, including those inside the Jinja
  template of the alarm card, which a walk of the YAML structure would miss. It
  compares against the registry rather than against a second list of names, so
  renaming an entity stays allowed and shipping an example that no longer matches it
  does not. It also refuses references to entities that are disabled by default,
  since those render as empty cards.
- `scripts/validate.sh` now runs `ruff check` and `ruff format --check`, which it had
  always claimed to. That gap is why the two below went unnoticed.

### Changed

- **The lint job could not have passed.** `ruff` reported 92 findings and wanted 15
  files reformatted, and nothing had ever run it. Nine functions gained docstrings,
  eight were reworded to imperative mood, `int(round(x))` and a hand-rolled
  `zip(xs, xs[1:])` were simplified, and two U+2212 MINUS SIGN characters that look
  exactly like hyphens and break a grep for one were replaced.
- Two rules are now off, each with its reasoning recorded in `pyproject.toml`:
  `D102`/`D105`, because fifty-eight of the findings were Home Assistant property
  overrides whose contract belongs to the base class and whose subject belongs to the
  class docstring; and `RUF012`, because entity attributes like `_attr_hvac_modes`
  are lists by the base class's own annotation, so `ClassVar` would contradict it.
  `D100`, `D101` and `D103` stay enforced.
- `ruff` is pinned to an exact version in the workflow and in `validate.sh`, and
  bumped by hand, since Dependabot does not see a version inside a `run:` line.
  Unpinned, a ruff release adding a rule turns the lint job red with no code change
  behind it.
- `THERMAL_POWER_UNIT` was an unused alias for `UnitOfPower.KILO_WATT`; removed along
  with the import that existed only to feed it. `SetpointDef.diagnostic` set
  `EntityCategory.CONFIG`, which is a different thing, and is now named
  `config_category`.
- The unused enable and command bits in `safe_write.py` stay, and now say why: both
  registers are bit fields, a bit field is only safe to write when the whole layout is
  known, and this layout came out of reverse engineering a protocol that is not
  published anywhere.

## [1.0.0] - 2026-08-08

First public release.

### Added

- Config flow over the UI: gateway address, TCP port, Modbus id and controller
  model, with a live connection probe before the entry is created. Reconfigure
  flow for changing the gateway without losing entity history, and an options
  flow for the polling interval.
- Single `DataUpdateCoordinator` per config entry, so the integration is by
  construction the only Modbus master on the bus.
- **The read plan is computed, not hand-written.** Contiguous blocks are merged from
  the declared register map with a tolerance tuned against a cost model of the bus:
  at 9600 baud a transaction costs about 30 ms of fixed overhead against 2 ms per
  register, so reading sixteen registers nobody wants is cheaper than one more round
  trip. The result is seven transactions where the hand-written table used twelve,
  roughly 350 ms of line time per poll instead of 410. The tuning is asserted in the
  tests, so changing it for the worse fails the build, and a register added to the
  map can no longer end up outside every block, which is a bug that reads as "that
  sensor is always unavailable".
- Sentinel filtering at the read layer. The manufacturer's "probe absent" values
  (32766, 32767, -32768, -32767, -32640, 65535) make an entity unavailable
  instead of being published as a measurement.
- `climate` entity for the space-conditioning side and `water_heater` entity for
  domestic hot water. Each owns one half of the packed state word and preserves
  the other, so turning heating off cannot silently disable hot water.
- Sensors for every mapped register, plus derived values: water ΔT with the
  manufacturer's limits in the attributes, thermal power (only when a real flow
  reading exists), mode switch counter, last mode change, and Modbus bus error
  rate.
- Full decoding of the three alarm words into named fault codes. Aggregate
  problem sensor and a per-alarm binary sensor for all 40 documented flags,
  created disabled so users enable only the ones they automate on.
- Validated write layer: manufacturer ranges checked before anything reaches the
  bus, and the controller's enable-bit sequence handled internally.
- `select` for the raw machine state, `number` entities for the setpoints,
  `switch` entities for the remote calls, and buttons to start the
  anti-legionella cycle and to release control back to the machine's own panel.
- Services `set_mode`, `set_dhw_setpoint`, `start_legionella`,
  `release_control`, and a read-only `read_register` for mapping controller
  generations this release does not cover.
- **Read-only mode**, selectable at setup and changeable afterwards. Creates
  sensors and nothing else: the control platforms are never set up, and the
  coordinator refuses writes outright, so an entity left in the registry by an
  earlier install cannot reach the bus either. Intended for machines whose original
  wall controller is still in charge, and for installations that want the telemetry
  and nothing more.
- **Installation health checks**, raised as repair issues. A sustained Modbus error
  rate and more than a dozen mode changes an hour both point at the setup rather
  than at the machine, and both are conditions a user does not know to look for.
  The notifications name the likely cause, which in both cases is usually a second
  Modbus master or a second controller, and clear themselves when the condition
  goes away. The mode switch sensor now carries the per-hour rate in its
  attributes, since a total since startup cannot distinguish thrashing from
  uptime.
- Config entry diagnostics with the last full reading, decoded alarms and bus
  health counters.
- A **Modbus simulator** (`scripts/modbus_simulator.py`, standard library only) and
  a **Docker sandbox** (`sandbox/`) with a throwaway Home Assistant. Nobody should
  need to own the machine to work on the integration, or to test against a real heat
  pump to find out that a change broke the register map. The simulator carries a
  crude thermal model so the derived sensors move, raises fault codes on request, and
  reproduces three controller behaviours that are impossible to discover without
  hardware: holding and input registers mirrored, writes silently ignored without
  their enable bit, and illegal state values rejected. It refuses writes by default.
- `sandbox/install-from-github.sh` installs the published release the way HACS does,
  so a file missing from the zip or a manifest version disagreeing with the tag
  surfaces in testing rather than in someone's issue.
- Blueprints for hot water scheduling with anti-cycling, solar priority,
  electric backup heater, hot water recirculation, and a restricted-flow alert.
- Translations: English, Portuguese, Italian.

### Security and privacy

Findings from the pre-release audit, and what was done about each.

- The gateway address and the `last_error` string are **redacted** from the
  diagnostics download. There are no credentials anywhere in this integration, so
  none can leak, but a diagnostics file gets attached to public issues and an
  internal address next to a device inventory is more than anyone means to publish.
  The port, Modbus id, model, polled blocks and readings stay, since those are what
  make a report answerable.
- Reads of more than 125 registers are refused by the transport. That is the
  protocol ceiling for function 3, and exceeding it built a frame no gateway could
  answer, surfacing as an unexplained timeout instead of as the programming error
  it was.
- GitHub Actions are **pinned to commit SHAs** instead of tags. A tag or branch can
  be silently repointed by whoever owns the action, which is how several real
  supply-chain incidents in the Actions ecosystem worked. Dependabot keeps the pins
  current, and workflow permissions are now least-privilege.
- The release workflow passes the tag through the environment rather than
  interpolating it into a shell command, which closes the standard Actions script
  injection route.
- `scripts/check_privacy.py` runs in CI and fails the build on an unexpected email
  address, an address from a private range other than the documentation network, or
  a hostname from the author's own network.
- `scripts/check_yaml.py` uses `yaml.safe_load` outright, rather than a safe loader
  subclass passed to `yaml.load`. Both are equally safe; only one of them is
  obviously safe to a static analyser and to a reader deciding whether to trust
  this repository.
- [SECURITY.md](SECURITY.md) documents the threat model, the reporting route and
  what is validated where. Short version: no credentials, no cloud, no listening
  socket, no file access, nothing executed, and one outbound connection to the
  configured gateway.

`semgrep` reports no findings for `p/python`, `p/secrets`, `p/command-injection`,
`p/insecure-transport`, `p/security-audit` and `p/owasp-top-ten`, and no remaining
findings for `p/github-actions`.

### Brand icons

The icon ships in `custom_components/maxa_advantix/brand/`, at 256x256 and 512x512,
and that is the whole story. Home Assistant 2026.3 introduced the Brands Proxy API,
which serves icons bundled with a custom integration and gives them priority over the
brands CDN, with no separate repository submission needed.

There is deliberately no pull request to `home-assistant/brands`: that repository's
own template now states that submissions for new custom components are no longer
accepted. And there is no logo, because the guidance is to ship only the icon when the
logo would be the same image, and a square 512x512 logo fails the size rule regardless.

### Validation

`scripts/validate.sh` runs every check the CI runs, locally, using the same
official container images. A contributor can know a change is good before opening a
pull request, and a maintainer can reproduce a red run without pushing commits to
find out why.

At release: `hassfest` clean with no warnings, all nine HACS checks passing, 232
tests passing, and the privacy and YAML checks clean.

Two of those found real problems that the file-level checks could not:

- `hassfest` pointed out that an integration implementing `async_setup` must
  declare a config schema. Without one Home Assistant silently accepts a
  `maxa_advantix:` block in `configuration.yaml` and validates nothing, leaving the
  user waiting for an effect that never arrives.
- The HACS action revealed that brand assets are checked inside the repository first
  (`custom_components/<domain>/brand/`) and only then in the brands repository, so
  the icons now ship with the integration and the check passes without waiting on
  another project's review queue.

`tests/test_blueprints.py` validates the blueprints with Home Assistant's own
`Blueprint` class and then substitutes every input and runs the result through the
real automation schema. Parsing YAML successfully is not the same as being
importable, and the difference shows up on a user's machine rather than here.

[1.0.0]: https://github.com/gcoutinho-ipca/hass-maxa-advantix/releases/tag/v1.0.0
