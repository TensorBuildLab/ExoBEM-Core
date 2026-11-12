# Thermonaut tutorial: a lunar habitat in the EnergyPlus engine

This tutorial builds Thermonaut, writes a planetary weather file with the engine's own environment generator and
runs the NASA-informed four-crew lunar habitat on it. No EPW file is needed for the run. Everything below was run on
Windows 11 with Visual Studio 2022 Build Tools. On Linux or macOS, use the standard EnergyPlus CMake build.

## 1. Build

```bat
git clone https://github.com/TensorBuildLab/Thermonaut.git
cd Thermonaut
planetary\tools\build.bat configure 8
```

This configures with Ninja (`BUILD_TESTING=ON`, `LINK_WITH_PYTHON=OFF`) and builds `build\Products\energyplus.exe`
and `energyplus_tests.exe`. Optional checks:

```bat
build\Products\energyplus_tests.exe --gtest_brief=1
python planetary\tools\earth_regression.py
```

The second command compares Thermonaut with an unmodified EnergyPlus v26.2.0 build on 15 example files. It
needs that build; see the script header.

## 2. Make a planetary weather file

Thermonaut generates the lunar or Martian environment itself when `Site:PlanetaryBody` names no weather file; it
then takes the site (latitude, longitude) and the calendar from a placeholder EPW. The same environment can be
written to a file in the [Planetary Weather Format](docs/weather_format.md) (PWF), where it can be inspected,
edited or replaced by data from another source (Mars Climate Database, rover data):

```bat
python planetary\tools\export_pwf.py planetary\cases\lunar_habitat\lunar_habitat.idf ^
       planetary\cases\lunar_habitat\placeholder.epw planetary\cases\lunar_habitat\lunar_habitat.pwf
```

The script runs the input once in generator mode with every site variable reported at the time step and writes
one record per step (solar quantities as interval means, state quantities at the end of the interval).

## 3. The input file

`planetary/cases/lunar_habitat/lunar_habitat.idf` describes the habitat; the source of every input value is
listed in supplementary material S7 of the paper. The planetary parts of the IDF are:

```
Site:PlanetaryBody,
  lunar_habitat,         !- Name
  Moon,                  !- Body
  EarthClock,            !- Clock (hours of 3600 s, days from 00:00 UTC)
  2030,                  !- Reference Year
  autocalculate,         !- Gravity {m/s2}                       -> 1.625
  56500,                 !- Cabin Pressure {Pa}
  0.34,                  !- Cabin Oxygen Mole Fraction
  0.15,                  !- Cabin Air Velocity {m/s}
  5.25,                  !- Convection Vertical Length Scale {m}
  0.0,                   !- Horizon Elevation Angle {deg}
  autocalculate, autocalculate, autocalculate, autocalculate,   !- regolith thermal inertia, albedo, emissivity, spin-up
  3.0,                   !- Deep Regolith Depth {m}
  710, Climatology, 0.5, 0, 0, 0, 3.2, 2.0,                     !- Mars-only fields (ignored on the Moon)
  lunar_habitat.pwf;     !- Planetary Weather File Name

RunPeriod, lunar_habitat, 1, 1, 2030, 1, 30, 2030, Tuesday, No, No, No, Yes, Yes;
```

The rest is ordinary EnergyPlus input, with these mappings for a habitat:

| Habitat feature | EnergyPlus objects used |
|---|---|
| Envelope: beta cloth / MLI / aluminium / interior panel | `Material`, `Material:NoMass` (MLI as a resistance), `Construction`, CTF conduction |
| Habitat on legs; floor sees the regolith | `BuildingSurface:Detailed` floor with `Outdoors` boundary (tilt 180°) |
| Racks and stowage | `InternalMass` |
| Crew sensible and latent heat (BVAD schedules) | `OtherEquipment` with latent fraction, `Schedule:Compact` |
| Equipment heat on cold plates; chemical energy of electrolysis | `OtherEquipment` "Fraction Lost" |
| 20–25 °C, RH 30–60 % | `ZoneControl:Thermostat`, `ZoneControl:Humidistat`, `ZoneHVAC:IdealLoadsAirSystem` (humidistat) |
| PV arrays | `Generator:Photovoltaic` with `PhotovoltaicPerformance:Simple`, or the one-diode model in Decoupled mode (planetary cell temperature) |
| Batteries | `ElectricLoadCenter:Storage:*` placed in a zone |

Objects that need outdoor air or Earth weather stop the run with an error in planetary mode. These include
infiltration, ventilation, outdoor-air systems, air- and evaporatively-cooled equipment, cooling towers,
PVWatts, Kiva, design days and Earth-fitted PV temperature models. This is deliberate: such objects would
otherwise run and return plausible-looking numbers.

## 4. Run

```bat
cd planetary\cases\lunar_habitat
..\..\..\build\Products\energyplus.exe -d out lunar_habitat.idf
```

`out\eplusout.err` reports what the planetary mode did:

```
Thermonaut: planetary weather file lunar_habitat.pwf (14400 records of 180 s from 2030-01-01T00:00:00);
             calendar EPW written to out\planetary_calendar.epw
Thermonaut planetary mode: Body=Moon, gravity=1.625 m/s2, cabin pressure=56500 Pa (zone air uses cabin pressure)
Thermonaut: environment for 31 days read from the planetary weather file, deep regolith -14.9 C
EnergyPlus Completed Successfully-- 0 Warning; 0 Severe Errors
```

All the usual outputs are available: `Zone Ideal Loads Zone Sensible Cooling Rate`, `... Latent Cooling Rate`,
`Zone Air Relative Humidity`, surface temperatures and PV output. Thermonaut also adds these planetary outputs:

* `Site Planetary Ground Surface Temperature`
* `Site Planetary Deep Ground Temperature`
* `Site Planetary Ambient Pressure`
* `Site Planetary Downwelling Longwave Radiation`
* `Site Planetary Sun Distance`
* `Site Planetary Solar Longitude`
* `Site Planetary Dust Optical Depth`

## 5. Check the result

`planetary/cases/roundtrip_check.py` runs the habitat with the generator and again with the exported file: over
days 4–30 the sensible cooling is 3723.0 kWh in both (difference −0.0002 %), the latent cooling 138.2 kWh. The
ideal-loads humidistat keeps the cabin at 47–50 % relative humidity; `planetary/cases/humidity_check.py` reports the
dew point and the margin of the coldest inside surface. [VERIFICATION.md](VERIFICATION.md) (section 4) gives the
full results.

## 6. Next steps

* **Mars:** set `Body` to `Mars` and use `planetary/cases/mars_jezero/placeholder.epw` for the Jezero site, or
  export a Jezero PWF as in step 2. In this version hours are Earth hours; a sol clock is planned.
* **PV in vacuum:** see `planetary/cases/pv_vacuum/pv_vacuum.idf`.
