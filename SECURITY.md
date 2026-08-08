# Security

## Reporting a vulnerability

Open a [private security advisory](https://github.com/gcoutinho-ipca/hass-maxa-advantix/security/advisories/new),
or write to gcoutinho@gmail.com. Please do not open a public issue for something
exploitable.

This is a spare-time project with one maintainer, so no response-time promise
would be honest. Reports are taken seriously and credited unless you prefer
otherwise.

## What this integration does, in security terms

Worth knowing before you install anything that writes to a heating appliance.

**It holds no credentials.** There is no account, no API key, no token and no
password anywhere in the configuration. Modbus has no authentication, which is a
property of the protocol, not a choice made here. The whole configuration is an
address, a TCP port, a Modbus id and a model name.

**It talks to one host, the one you configured.** No cloud service, no telemetry,
no update check, no outbound connection of any kind. `iot_class` is
`local_polling` and that is literal.

**It has no listening socket.** Nothing here accepts an inbound connection.

**It reads and writes no files.** No cache, no state file, no log file of its own.

**It executes nothing.** No `eval`, no `exec`, no subprocess, no deserialisation of
untrusted data, no dynamic imports, no template rendering of remote input. Modbus
replies are parsed with fixed-width `struct` unpacking into integers, so a hostile
reply can produce a wrong number, never code execution.

## Threat model

The honest summary: **Modbus TCP is plaintext and unauthenticated, and anything on
your LAN that can reach the gateway can control your heat pump.** That is true of
every Modbus device and every integration that speaks to one, this one included.

What follows from that:

- **Do not expose the gateway to the internet.** No port forwarding, no
  `0.0.0.0` binding on the gateway, no "temporary" rule. Anyone who reaches port
  502 can set your machine to whatever they like.
- **Segment it if you can.** These gateways are cheap devices with old firmware
  and rarely see an update. A VLAN for building services, with only Home Assistant
  allowed through to port 502, costs an afternoon and removes the whole category.
- **Treat Home Assistant as the control point.** Once this integration is set up,
  anyone with access to your Home Assistant can change the heat pump's mode and
  setpoints. That is the intended feature; it also means the usual hygiene applies,
  which is a strong password, two-factor authentication, and no exposed instance
  without a reverse proxy you trust.
- **The physical machine keeps the last word.** Thermal protections, compressor
  timers, defrost and high-temperature limits live in the controller's firmware and
  are not reachable over Modbus. Nothing this integration can send bypasses them.
  That is why writes are validated instead of clamped: sending only values the
  manufacturer documents keeps the machine inside the envelope its own protections
  assume.

## What is validated, and why

Every write is range-checked before a byte reaches the bus:

- The state register accepts only the six values the controller documents.
  The manufacturer's own warning is that writing an unaccepted value "may lead to
  unexpected operation", so values outside that set are refused rather than
  attempted.
- Every setpoint is bounded by the documented range for that register.
- The read service accepts an address in 0 to 65535 and a count of 1 to 32.
- The transport refuses a read of more than 125 registers, which is the protocol
  ceiling for function 3.

There is deliberately **no** `write_register` service. An arbitrary unvalidated
write is precisely the thing the validation layer exists to prevent, and offering
it as a convenience would undo the point of having one.

## Automated checks

Every push and pull request runs:

- `hassfest`, Home Assistant's own integration validator
- the HACS validation action
- `ruff` for lint and format
- the test suite
- a YAML and blueprint check, including that every `!input` resolves
- a privacy scan (`scripts/check_privacy.py`) that fails the build on an
  unexpected email address, an address from a private range other than the
  documentation network, or a hostname from the author's own network

GitHub Actions are pinned to commit SHAs rather than tags, because a tag can be
silently repointed by whoever owns the action. Dependabot keeps the pins current.

Static analysis with `semgrep` (`p/python`, `p/secrets`, `p/command-injection`,
`p/insecure-transport`, `p/security-audit`, `p/owasp-top-ten`, `p/github-actions`)
reports no findings as of release 1.0.0.

## Disclaimer

This software is provided as is, with no warranty of any kind, and the author
accepts no liability for any damage, loss, malfunction or cost arising from its
use. See [LICENSE](LICENSE). You are responsible for what you connect to your
heating system.
