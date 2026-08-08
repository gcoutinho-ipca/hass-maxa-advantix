# Alarm codes

Three 16-bit registers carry 48 alarm flags. This is the V4 map. The bitmap
published for the older V2/V3 family assigns different codes to several of these
bit positions, so applying this table to a V2 controller will send you after the
wrong fault.

Each flag gets a binary sensor, created **disabled**. Enable the ones you
automate on from the device page; a disabled entity costs no state and no recorder
rows. The aggregate `Alarm` sensor and the `Active alarms` sensor are enabled and
cover the general case.

## Register 950

| Bit | Code | Meaning |
| --- | --- | --- |
| 0 | E001 | High pressure |
| 1 | E002 | Low pressure |
| 2 | E003 | Compressor overload |
| 3 | E004 | Fan overload |
| 4 | E005 | Antifreeze |
| 5 | E006 | Flow switch, no water flow |
| 6 | E007 | Low hot water preheater temperature |
| 7 | E008 | Lubrication failure |
| 8 | E009 | High discharge temperature, compressor 1 |
| 9 | E010 | High solar collector temperature |
| 12 | E013 | Compressor 2 overload |
| 13 | E014 | Fan 2 overload |
| 15 | E016 | Pump overload |

## Register 951

| Bit | Code | Meaning |
| --- | --- | --- |
| 1 | E018 | High temperature |
| 2 | E019 | High discharge temperature, compressor 2 |
| 3 | E020 | Pressure transducers swapped |
| 6 | E023 | Compressor 3 overload |
| 7 | E024 | Fan 3 overload |
| 9 | E026 | Pump 2 overload |
| 11 | E041 | Inconsistent temperature readings |
| 12 | E042 | Insufficient hot water heat exchange |
| 13 | E050 | High hot water storage temperature |
| 14 | E101 | I/O module 1 offline |
| 15 | E102 | I/O module 2 offline |

## Register 952, probe faults

| Bit | Code | Meaning |
| --- | --- | --- |
| 0 | E611 | Probe 1 fault |
| 1 | E621 | Probe 2 fault |
| 2 | E631 | Probe 3 fault |
| 3 | E641 | Probe 4 fault |
| 4 | E651 | Probe 5 fault |
| 5 | E661 | Probe 6 fault |
| 6 | E671 | Probe 7 fault |
| 7 | E681 | Probe 8 fault |
| 8 | E691 | Probe 9 fault |
| 9 | E701 | Probe 10 fault |
| 10 | E711 | Probe 11 fault |
| 11 | E612 | Probe 1 fault, I/O module 1 |
| 12 | E622 | Probe 2 fault, I/O module 1 |
| 13 | E632 | Probe 3 fault, I/O module 1 |
| 14 | E642 | Probe 4 fault, I/O module 1 |
| 15 | E652 | Probe 5 fault, I/O module 1 |

Bit positions not listed are reserved. They are still counted by the `count`
attribute of the `Active alarms` sensor, so a count higher than the number of named
codes means an undocumented flag is set, which is itself useful information for a
bug report.

## Reading these codes as symptoms

Two of them are worth more than the one-line description suggests, because they
are the ones most often misread as machine failures.

### E042, insufficient hot water heat exchange

This is usually **a protection working, not a fault**. On the installation this
integration was written for, all thirty occurrences over 48 hours had the outlet
water sitting at 57.6 to 58.3 °C against a limit of 58 °C. The compressor stops
and restarts only once the water has fallen four degrees below the limit. The
alarm is the machine telling you it declined to cook itself.

What it points at is a flow restriction on the hot water branch: too little water
moving through the plate exchanger, so the water that is there gets too hot. The
symptom to check is water ΔT. Nominal is around 5 K and 8 K is the tolerated
maximum; a sustained ΔT of 15 K or more means roughly a third of the flow the
machine needs.

Order of suspicion, cheapest first:

1. **The strainer on the water inlet.** The manuals require a metallic Y-strainer
   with a mesh of 1 mm or finer, and warn that a clogged one causes exactly this
   chain of events. It is the single most likely cause and the easiest to check.
2. **Air trapped in the hot water branch.** Bleed it.
3. **Scale in the plate exchanger**, on hard water and older installations.
4. **The three-way diverter valve.** Worth checking that it actually completes its
   travel, but do not start here. In the case this documentation comes from, the
   valve was suspected first and turned out to be working correctly; the
   restriction was downstream of it.

### E006, flow switch

Counter-intuitively, the absence of this alarm is not evidence of adequate flow.
The manuals state that flow switch supervision is suspended during hot water
production, which is precisely when a restricted hot water branch shows itself. A
machine can have a serious flow problem, trip E042 thirty times, and never once
raise E006.

That is why this integration derives its own `Flow restricted` sensor from ΔT. On
some installations it is the only warning you will get.

### E101 and E102, I/O module offline

If these appear after you install this integration and were not there before, the
cause is more likely to be the bus than the module. A second Modbus master on the
same RS-485 segment produces timeouts that the controller reports as a missing
module. Check that the wall controller's data lines really are disconnected, and
watch the `Bus error rate` sensor.
