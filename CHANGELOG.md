# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[1.0.0]: https://github.com/gcoutinho-ipca/hass-maxa-advantix/releases/tag/v1.0.0
