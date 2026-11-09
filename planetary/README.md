# ExoBEM-Core

**ExoBEM-Core** is a research fork of the EnergyPlus™ v26.2.0 building energy simulation engine that adds a
**planetary mode** for pressurized habitats on the **Moon** and **Mars**. It keeps the full EnergyPlus zone heat
balance (surface heat balances, CTF / CondFD conduction, interior radiation, shading, internal gains, ideal loads,
reporting) and replaces the Earth-only parts: solar position, weather, sky, atmosphere, ground, convection and
outdoor air.

> ExoBEM-Core is **not** EnergyPlus and is not endorsed by the U.S. Department of Energy, the National Laboratory of
> the Rockies (formerly NREL), or the EnergyPlus developers. It is distributed under the EnergyPlus license
> (`LICENSE.txt`, BSD-3 with the DOE naming clause), which is why it carries a different name.

Its lightweight companion is the Python model [ExoBEM](https://github.com/TensorBuildLab/ExoBEM), which
re-implements the same heat-balance method and is used here as the reference for verification.

## What changes in planetary mode

Add one object to an input file:

```
Site:PlanetaryBody,
  Habitat,        !- Name
  Moon,           !- Body (Earth | Moon | Mars)
  EarthClock,     !- Clock (hours of 3600 s, days 00:00 UTC)
  2030,           !- Reference Year
  autocalculate,  !- Gravity {m/s2}
  70300,          !- Cabin Pressure {Pa}
  0.265,          !- Cabin Oxygen Mole Fraction
  0.15,           !- Cabin Air Velocity {m/s}
  6.0;            !- Convection Vertical Length Scale {m}
```

| Earth assumption in EnergyPlus | ExoBEM-Core planetary mode |
|---|---|
| Sun from an Earth Fourier fit, 15°/h | Mars24 ephemeris (Allison & McEwen 2000) or lunar subsolar point; the engine's hour-angle rate becomes the body's (0.51°/h Moon, 14.6°/h Mars on an Earth clock) |
| EPW weather | Internal environment generator: vacuum + 2.725 K sky (Moon); delta-Eddington dust two-stream, seasonal τ(Ls), pressure, downwelling IR and near-surface air (Mars); 1-D regolith column spun up before the run |
| Zone air at the outdoor pressure | Zone and HVAC air at the cabin pressure; the true ambient pressure is reported separately |
| TARP/DOE-2 exterior convection with a non-zero floor | Zero in vacuum; Churchill–Chu / flat-plate mixed convection in 700 Pa CO₂ at 3.72 m/s² |
| Interior TARP at 1 atm and 1 g | Same physical correlation for the cabin gas at cabin pressure and body gravity |
| Part of the sky long-wave goes to air; ground = air temperature | All sky long-wave to the sky; ground long-wave from the regolith surface temperature |
| Ground temperature by calendar month | Deep-regolith temperature from the spun-up column |
| Walls start at 23 °C | CondFD walls start from their steady profile (regolith time constants are months to years) |
| −100 °C sanity limits | Relaxed off-Earth (lunar night surfaces reach −180 °C) |
| Any object accepted | Objects that need outdoor air or Earth weather (infiltration, ventilation, OA systems, air-cooled condensers, cooling towers, PVWatts, Kiva, design days, …) stop the run with an error |

With no `Site:PlanetaryBody` object, or `Body = Earth`, every result is bit-for-bit identical to EnergyPlus v26.2.0
(verified on 14 example files; see below). Design decisions and the full list of Earth assumptions found in the
code (≈260 findings) are in [`DESIGN.md`](DESIGN.md) and [`audit/`](audit/).

## Building (Windows, MSVC 2022 Build Tools)

```
planetary\tools\build.bat configure 10
```

This configures with Ninja (`BUILD_TESTING=ON`, `LINK_WITH_PYTHON=OFF`) and builds `energyplus.exe` and
`energyplus_tests.exe` into `build\Products`. On Linux/macOS use the standard EnergyPlus CMake build.

## Running the verification cases

```
set EXOBEM_PATH=<path to a TensorBuildLab/ExoBEM checkout>
python planetary/cases/make_cases.py            # IDFs, placeholder EPWs and Python ExoBEM reference runs
build\Products\energyplus.exe -w planetary/cases/moon_equator/placeholder.epw -d out_moon planetary/cases/moon_equator/moon_equator.idf
python planetary/cases/compare.py moon_equator out_moon
python planetary/tools/earth_regression.py      # baseline v26.2.0 vs fork on Earth example files
```

In this version the weather file only supplies the calendar and the location; every weather value is replaced
by the planetary generator. Sizing periods and design days are not supported off-Earth yet.

## Status

M1 (this branch): Moon and Mars habitats with opaque envelopes, CTF or CondFD conduction, internal gains and
ideal loads. Planned: M2 sol clock for Mars, cabin gas mixture psychrometrics, gravity in every buoyancy model,
runs without a weather file, planetary design days; M3 space radiator plant component, PV in vacuum, windows.
See [`DESIGN.md`](DESIGN.md).
