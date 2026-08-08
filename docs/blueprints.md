# Blueprints

The integration is a driver. It exposes what the machine can do and refuses what
the machine cannot accept, and it stops there. Operating policy, when to make hot
water, whether to wait for the sun, when an immersion heater is worth its
electricity, lives in automations you can read and change.

These five blueprints are that policy, taken from a working installation. Import
them from the repository, or copy the files into
`config/blueprints/automation/maxa_advantix/`.

Import one directly with its raw URL, for example:

```
https://raw.githubusercontent.com/gcoutinho-ipca/hass-maxa-advantix/main/blueprints/automation/maxa_advantix/dhw_hysteresis.yaml
```

## How they fit together

The three hot water blueprints coordinate through one helper you create once: an
`input_boolean` called something like `Hot water solar block`.

```
solar_priority  ──sets──>  input_boolean.hot_water_solar_block
                                    │
                        ┌───────────┴───────────┐
                        │                       │
                  dhw_hysteresis          electric_backup
                  (heat pump)             (immersion heater)
```

Keeping the decision separate from the action is deliberate. You can look at the
helper and see *why* hot water is paused, and one flag holds back both consumers
at once. Encoding the forecast test inside each consumer would work and would be
impossible to debug at seven in the morning.

The resulting cost ladder, cheapest first: free solar heat, then the heat pump,
then the immersion element. The emergency threshold in the hysteresis blueprint cuts
through all of it, because a cold cylinder at bedtime is not a saving.

## `dhw_hysteresis`, hot water with anti-cycling

The counter-intuitive part first, because it is the part that makes it work.

**Set the machine's own hot water setpoint one or two degrees above the
blueprint's "stop at" value.** For example: machine setpoint 47 °C, blueprint band
40 to 46 °C.

The machine then never reaches its own cut-off, so it never applies its own
internal differential, which is narrow and not exposed over Modbus. Your wide band
is what governs. The compressor makes one long run instead of six short ones, and
long runs are both kinder to the machine and more efficient, since every start
pays a fixed cost in oil migration and pressure equalisation.

Three brakes, in order of how often they fire:

**Compressor rest.** A new run cannot start until hot water has been off for the
configured time. Ten minutes is a sensible default. This is implemented with a
`for:` condition on the entity's own state rather than a stored timestamp, which
means it survives a Home Assistant restart.

**Flow gating.** If the flow restricted sensor is on and the outlet water is
already warm, a new run is postponed. Starting into a restricted circuit only
trips the high-temperature protection, and a machine that trips, cools, starts and
trips again is doing damage while achieving nothing. Set the warning temperature a
few degrees below the machine's own limit so you never reach the protection.

**Block conditions.** Any entity you nominate: the solar flag, a schedule, an away
toggle.

Both the rest brake and the flow gate only ever delay a *new* start. Neither
interrupts a run in progress, which is left to finish, to time out, or to be
stopped by the machine's own protections. And both give way below the emergency
threshold.

## `solar_priority`, hold hot water for the sun

During a morning window, if the day's forecast is at least the threshold you set,
raise the flag. Outside the window or below the threshold, drop it.

Set the threshold from experience rather than theory: the forecast figure that has
actually been enough to heat your tank by mid-afternoon. Start conservative and
lower it once you trust it.

The window end is a hard release. A day that promised sun and did not deliver still
ends with hot water, because after the window the normal hysteresis takes over
regardless of the forecast.

Works with any sensor reporting the day's expected production in kWh:
Forecast.Solar, Solcast, or a template sensor of your own. With solar thermal
panels rather than PV, a collector temperature sensor and a suitable threshold work
just as well. If the forecast sensor is unavailable, nothing is blocked: missing
data is not a reason for optimism about the weather.

## `electric_backup`, immersion heater as last resort

A narrow band, deliberately, and set well below the heat pump's start threshold.
For example element 35 to 39 °C against a pump band of 40 to 46 °C. The element
exists to stop the tank going cold, not to heat it to comfort temperature at
roughly four times the running cost.

It yields to the solar flag as well. On a morning with guaranteed sun the element
stays off too, and the only safety net is the heat pump's emergency threshold.
Letting the tank cool for three hours on a sunny morning is free; reheating it
electrically is not.

Two safety behaviours are deliberate. If the tank probe stops reporting, the
element is switched **off** rather than left as it was: an unsupervised resistive
load on a cylinder is the one thing worth being pessimistic about. And when the
enable toggle is off, the element is actively turned off rather than merely left
alone, because it is a large load and "probably already off" is not good enough.

## `dhw_recirculation`, instant hot water at the tap

A recirculation pump means hot water arrives immediately instead of after twenty
litres go down the drain. Left running around the clock it is also a small heater
bleeding the cylinder into the pipework, and it shows up as the heat pump starting
at three in the morning for no reason anyone can explain.

Hence the night pause, with minute precision, and an optional minimum tank
temperature: circulating a tank that is already cool just spreads the cold around.

The pause window handles wrapping around midnight correctly, so a pause from 23:00
to 06:00 behaves as you would expect.

## `fault_alert`, know before the machine gives up

Notifies on any alarm appearing, on alarms clearing, and on a sustained flow
restriction.

The delay on the flow alert is the important setting. ΔT spikes briefly at every
compressor start and every mode change, so alerting on the instantaneous value
produces noise, and noise trains you to ignore the one message that mattered.
Fifteen minutes is a good starting point.

## Writing your own

Everything the blueprints use is a normal entity or service, so nothing here is
privileged. Two things are worth knowing before you build on top of them:

**Use `climate` and `water_heater` rather than writing the state register.** They
handle the state and call pair, and each preserves the other's half of the packed
register. Writing register 7200 from an automation is how you disable hot water by
accident while turning the heating off.

**Do not run two controllers at once.** If a blueprint is managing hot water, do
not also have a script doing it. The failure looks exactly like a hardware fault:
the machine changes mode constantly, the valve never finishes travelling, and the
protections start tripping.
