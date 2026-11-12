<p align="center"><img src="logo/thermonaut_logo.png" alt="Thermonaut" width="560"></p>

# Thermonaut

**Thermonaut** is a research fork of the EnergyPlus™ v26.2.0 building energy simulation engine that adds a
**planetary mode** for sealed, pressurized habitats on the **Moon** and **Mars**. It keeps the full EnergyPlus
zone heat balance: surface heat balances, CTF / CondFD conduction, interior radiation, shading, internal gains,
ideal loads, PV and storage, and reporting. It replaces the Earth-only parts: solar position, weather, sky,
atmosphere, ground, convection, PV cell temperature and outdoor air.

> Thermonaut is **not** EnergyPlus and is not endorsed by the U.S. Department of Energy, the National Laboratory of
> the Rockies (formerly NREL), or the EnergyPlus developers. It is distributed under the EnergyPlus license
> (`LICENSE.txt`, BSD-3 with the DOE naming clause), which is why it carries a different name.

Thermonaut runs on its own: it generates the lunar and Martian environment internally or reads a planetary weather
file. The separate Python tool [ExoBEM](https://github.com/TensorBuildLab/ExoBEM) implements the same physics
independently; here it serves as a code-to-code reference and as a convenient writer of planetary weather files.
The engine is also checked against independent references: JPL Horizons (sun position), Diviner (lunar regolith
temperatures), closed-form exterior balances and NIST CO2 properties ([VERIFICATION.md](VERIFICATION.md)).

**Start here:** [TUTORIAL.md](TUTORIAL.md) builds the engine and runs a NASA-informed four-crew lunar habitat.

## What changes in planetary mode

Add one object to an input file. A planetary weather file (PWF) is optional; with one, no EPW is needed:

```
Site:PlanetaryBody,
  Habitat,        !- Name
  Moon,           !- Body (Earth | Moon | Mars)
  EarthClock,     !- Clock (hours of 3600 s, days 00:00 UTC)
  2030,           !- Reference Year
  autocalculate,  !- Gravity {m/s2}
  56500,          !- Cabin Pressure {Pa}
  0.34,           !- Cabin Oxygen Mole Fraction
  0.15,           !- Cabin Air Velocity {m/s}
  5.25,           !- Convection Vertical Length Scale {m}
  0.0,            !- Horizon Elevation Angle {deg}
  autocalculate, autocalculate, autocalculate, autocalculate, 3.0,   !- regolith parameters, deep depth
  710, Climatology, 0.5, 0, 0, 0, 3.2, 2.0,                          !- Mars atmosphere, dust, wind
  habitat.pwf;    !- Planetary Weather File Name (optional)
```

| Earth assumption in EnergyPlus | Thermonaut planetary mode |
|---|---|
| Sun from an Earth Fourier fit, 15°/h | Mars24 ephemeris (Allison & McEwen 2000) or lunar subsolar point; the engine's hour-angle rate becomes the body's (0.51°/h Moon, 14.6°/h Mars on an Earth clock) |
| EPW weather (8,760 Earth hours, Earth range checks) | A [planetary weather file](https://github.com/TensorBuildLab/ExoBEM/blob/main/docs/weather_format.md) read and interpolated to the time step, or an internal generator: vacuum + 2.725 K sky (Moon); delta-Eddington dust two-stream with Beer-law beam, seasonal τ(Ls), pressure, downwelling IR and near-surface air (Mars); regolith column in periodic equilibrium |
| Zone air at the outdoor pressure | Zone and HVAC air at the cabin pressure; the true ambient pressure is reported separately |
| TARP/DOE-2 exterior convection with a non-zero floor | Zero in vacuum; Churchill–Chu / flat-plate mixed convection in 700 Pa CO₂ at 3.72 m/s² |
| Interior TARP at 1 atm and 1 g | Same physical correlation for the cabin gas at cabin pressure and body gravity |
| Part of the sky long-wave goes to air; ground = air temperature | All sky long-wave to the sky; ground long-wave from the regolith surface temperature |
| Ground temperature by calendar month | Deep-regolith temperature from the equilibrated column |
| Walls start at 23 °C | CondFD walls start from their steady k(T) profile, corrected after warm-up |
| PV cell temperature from NOCT (Earth air) | One-diode PV in Decoupled mode: radiative (Moon) or radiative + convective (Mars) cell energy balance |
| −100 °C sanity limits | Relaxed off-Earth (lunar night surfaces reach −180 °C) |
| Any object accepted | Objects that need outdoor air or Earth weather stop the run with an error. These include infiltration, ventilation, OA systems, air-cooled condensers, cooling towers, PVWatts, Kiva, design days, Earth-fitted PV temperature models and batteries outside a zone |

With no `Site:PlanetaryBody` object, or `Body = Earth`, every result is bit-for-bit identical to EnergyPlus v26.2.0
(verified on 14 example files and the 2,379 unit tests; see [VERIFICATION.md](VERIFICATION.md)). Design decisions
and the 252 Earth assumptions found in the code are in [`DESIGN.md`](DESIGN.md) and [`audit/`](audit/).

## Building (Windows, MSVC 2022 Build Tools)

```
planetary\tools\build.bat configure 10
```

This configures with Ninja (`BUILD_TESTING=ON`, `LINK_WITH_PYTHON=OFF`) and builds `energyplus.exe` and
`energyplus_tests.exe` into `build\Products`. On Linux/macOS use the standard EnergyPlus CMake build. The
planetary changes are applied to v26.2.0 by the idempotent patch scripts in `planetary/tools/apply_hooks_*.py`.

## Verification cases

```
set EXOBEM_PATH=<path to a TensorBuildLab/ExoBEM checkout>
python planetary/cases/make_cases.py            # regolith-module cases + Python references + PWF files
build\Products\energyplus.exe -d out_moon planetary/cases/moon_equator/moon_equator_pwf.idf
python planetary/cases/compare.py moon_equator out_moon
python planetary/cases/make_habitat_case.py     # NASA-informed lunar habitat (IDF from the ExoBEM model) + reference
python planetary/tools/earth_regression.py      # baseline v26.2.0 vs fork on Earth example files
```

## Status

M2e (this branch, tag `thermonaut-m2e`): Moon and Mars habitats with opaque envelopes, CTF or CondFD conduction, internal gains, ideal
loads with humidity control, PV in vacuum, batteries; planetary weather files with no EPW and physical range checks; an input validator (with an outdoor-air backstop) that refuses every object the audit found cannot be right off-Earth, including windows; 23 planetary tests (`tests/run_planetary_tests.py`). Planned: sol clock for
Mars, cabin gas-mixture psychrometrics, gravity in every buoyancy model, planetary design days, a space-radiator
plant component and windows. See [`DESIGN.md`](DESIGN.md).
