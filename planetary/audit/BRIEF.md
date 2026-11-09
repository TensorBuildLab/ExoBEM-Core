# ExoBEM-Core audit brief (shared by all audit agents)

## Project
ExoBEM-Core is a research fork of EnergyPlus v26.2.0 (BSD-3 + DOE naming clause; never call the product
"EnergyPlus"/"E+"). The goal is a build of the full C++ engine that can simulate pressurized habitats on the
Moon and Mars, keeping Earth behaviour bit-for-bit unchanged when no planetary input is given.

- Fork source (branch `planetary`): C:\Users\liangzhang1\Documents\Claude\exo-fork  (src/EnergyPlus, third_party, idd/Energy+.idd.in)
- Reference physics already implemented and verified in Python (read for equations/values, do not edit):
  C:\Users\liangzhang1\Documents\Claude\EnergyPlus-for-extraterrestrial-space\exobem  (ephemeris/, environment/, convection.py,
  simulation.py, thermal_control.py, gas.py, docs/research/parameter_dossier.md)

## Planned architecture (so you can judge what must change)
1. New input object `Site:PlanetaryBody` (Earth | Moon | Mars | Custom): gravity, solar day length (s), year length,
   solar constant at 1 AU and heliocentric distance model, atmosphere type (none | thin CO2 | Earth), surface
   pressure model, sky model, regolith model, ephemeris (Mars24, lunar subsolar point).
2. **Planetary hour**: keep EnergyPlus's 24 "hours" per day and 1..60 timesteps per hour, but make one hour =
   solar-day/24 seconds (Mars 3699 s; Moon 106 300 s). Everything that indexes hours/timesteps stays; everything that
   converts time to SECONDS (rates, energy, thermal mass, CTF timestep, controllers, plant) must use the variable
   hour length. So the key audit question for any `SecInHour`, `3600`, `86400`, `24.0`, `HoursInDay`, `TimeStepZoneSec`
   use is: is it an *index/structure* use (fine) or a *physical seconds* use (must follow the planetary hour)?
3. Cabin vs outdoors: zone air must use a habitat pressure / gas mixture (e.g. 70.3 kPa, 26.5% O2) that is NOT the
   outdoor barometric pressure (0 Pa on the Moon, ~600-900 Pa CO2 on Mars).
4. Environment: weather comes from a planetary environment generator (or a planetary weather file) instead of EPW;
   vacuum => no exterior convection, sky at 2.7 K, no rain/snow/humidity; Mars => CO2 gas properties, dust optical depth,
   downwelling IR, low-density wind convection.
5. Gravity-dependent physics (natural convection, stack effect, window gaps, AFN) must use the body's gravity.
6. New heat rejection object (radiator to space / regolith) later; existing equipment rejecting heat to outdoor air
   must be flagged as unusable in vacuum.

## Your output
Write ONE markdown file (path given in your task) with:
1. A short summary (5-10 lines) of the area and the overall difficulty.
2. A table, one row per finding: `ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth |
   Proposed change | Priority`. Priority: **P0** = must change for a first Moon/Mars run of a single-zone habitat with
   ideal loads (opaque envelope, constructions, internal gains, schedules); **P1** = needed for windows, HVAC, plant,
   PV, or realistic outputs; **P2** = nice to have / rarely used module (flag as "unsupported off-Earth" instead).
   Group repeated patterns (e.g. "47 uses of X in files A,B,C") into one row with representative line numbers, but
   give exact counts.
3. A "Recommended implementation" section: concrete code-level plan (which globals/structs to add, which functions to
   branch on planet, where to hook), and what to leave alone.
4. Open questions / risks.

Rules: read-only on the source (do not edit any file except your output). Use grep (ripgrep) generously; cite
real line numbers from v26.2.0. Be precise and skeptical: distinguish physics from bookkeeping. Keep the file under
~600 lines. Write plain, direct English.
