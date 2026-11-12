# Planetary Weather Format (PWF) 1.0

PWF is the planetary weather-file format read by Thermonaut. It plays the role that the EPW file plays for
EnergyPlus, without EPW's Earth assumptions. It is plain text, so any tool can write or read it. Thermonaut
writes one from its own environment generator:

```
python planetary/tools/export_pwf.py planetary/cases/mars_jezero/mars_jezero.idf planetary/cases/mars_jezero/placeholder.epw jezero.pwf
```

## Why not EPW?

| EPW property | Problem on the Moon or Mars | PWF |
|---|---|---|
| 8,760 (8,784) records of one hour | The lunar day lasts 708.7 h; a Mars sol 24.66 h; multi-year Mars periods | Any number of equally spaced records of any length (`timestep_s`) |
| Month/day/hour time stamps of an Earth year | Mars seasons follow the solar longitude Ls, not the calendar | Elapsed seconds from `start_utc`, plus `local_time_h` and `day_index` for schedules |
| Range checks: a dry-bulb of 99.9 °C or more is treated as missing; a pressure of 31 kPa or less is replaced by the standard value | Lunar-noon regolith reaches 120 °C; Mars pressure is 0.6–0.8 kPa; Moon 0 Pa | Physical checks only (non-negative irradiance, temperatures above the 2.7 K cosmic background) |
| Dew point, relative humidity, precipitation, snow, cloud cover, visibility | No meaning in vacuum or a dry CO2 atmosphere | Not present; `T_air_K` is `nan` in vacuum |
| Horizontal infrared from the sky, opaque/total sky cover models | Sky emission comes from dust and CO2 (Mars) or is the 2.7 K background (Moon) | `T_sky_K` and `L_down_W_m2` given directly |
| Ground temperatures by month at three depths | Regolith swings 290 K in a lunar day; the ground model must be dynamic | `T_ground_K` (surface, every record) and `T_deep_K` (below the habitat) |
| No body, gravity or atmosphere information | Convection depends on gravity, gas and pressure | Header carries `body`, `gravity_m_s2`, `atmosphere` |

## File layout

```
# PWF 1.0
# body: mars
# site_name: mars_jezero
# latitude_deg: 18.440000
# longitude_deg: 77.450000
# start_utc: 2030-01-01T00:00:00
# timestep_s: 180
# n_records: 14880
# solar_day_s: 88775.244147
# gravity_m_s2: 3.72100
# atmosphere: mars_co2
# clock: earth_utc
# sky_includes_air: false
# generator: thermonaut (planetary/tools/export_pwf.py)
# units: s,h,-,deg,deg,-,W/m2,W/m2,W/m2,K,K,K,K,-,Pa,m/s,deg,W/m2,deg,-
time_s,local_time_h,day_index,zenith_deg,sun_azimuth_deg,sun_visible,dni_W_m2,...
180,0.05,0,121.9043,107.584,0,0,0,0,205.549,161.4181,...
```

* Line 1 must be `# PWF <version>`.
* Header lines are `# key: value`. Unknown keys are ignored.
* The first line that does not start with `#` holds the column names; every following line is one record.
* Values are separated by commas; missing or not-applicable values are written `nan`.

### Header keys

| Key | Required | Meaning |
|---|---|---|
| `body` | yes | `moon` or `mars`; it must match the `Body` of `Site:PlanetaryBody` |
| `latitude_deg`, `longitude_deg` | yes | Planetocentric latitude (north +) and longitude (east +); written to the calendar EPW |
| `start_utc` | yes | ISO 8601 UTC time of the start of the first record (`YYYY-MM-DDTHH:MM:SS`) |
| `timestep_s` | yes | Record length in seconds; records must be equally spaced |
| `gravity_m_s2` | recommended | Surface gravity (1.625 Moon, 3.721 Mars); the engine takes gravity from `Site:PlanetaryBody` |
| `atmosphere` | recommended | `none` (vacuum) or `mars_co2` |
| `solar_day_s` | recommended | Length of the solar day (2,551,442.9 s Moon; 88,775.244 s Mars) |
| `clock` | recommended | What `local_time_h` means: `earth_utc` (crew time follows UTC) or `mars_lmst` (local mean solar time) |
| `sky_includes_air` | no | `false` for planetary files: the sky view is not split into sky and air |
| `site_name`, `n_records`, `generator`, `units` | no | Documentation |

### Columns

Solar quantities are evaluated at the **middle** of each record's interval; state quantities at its **end**.

| Column | Unit | Required | Meaning |
|---|---|---|---|
| `time_s` | s | yes | End of the interval, seconds since `start_utc` |
| `local_time_h` | h | no | Clock hour (see `clock`) |
| `day_index` | – | no | Integer day (Earth day or sol) |
| `zenith_deg` | deg | yes | Solar zenith angle (documentation: the engine computes the sun position itself) |
| `sun_azimuth_deg` | deg | no | Solar azimuth, clockwise from north (documentation) |
| `sun_visible` | – | no | Fraction of the solar disk above the local horizon |
| `dni_W_m2` | W/m² | yes | Direct (beam) normal irradiance, already multiplied by `sun_visible` |
| `dhi_W_m2` | W/m² | yes | Diffuse horizontal irradiance (0 on the Moon) |
| `ghi_W_m2` | W/m² | no | Global horizontal irradiance |
| `T_air_K` | K | yes | Near-surface air temperature (`nan` in vacuum) |
| `T_sky_K` | K | yes | Effective sky temperature for long-wave exchange (2.725 K on the Moon) |
| `T_ground_K` | K | yes | Ground (regolith) surface temperature |
| `T_deep_K` | K | yes | Ground temperature at the bottom of ground-contact constructions |
| `ground_albedo` | – | yes | Ground solar reflectance |
| `pressure_Pa` | Pa | yes | Ambient (outdoor) pressure; 0 in vacuum |
| `wind_m_s` | m/s | yes | Wind speed (0 in vacuum) |
| `wind_dir_deg` | deg | no | Wind direction, clockwise from north |
| `L_down_W_m2` | W/m² | no | Downwelling long-wave radiation; if absent, σ·T_sky⁴ is used |
| `Ls_deg` | deg | no | Areocentric solar longitude (Mars season) |
| `dust_tau` | – | no | Column dust optical depth (Mars) |

## Checks applied when Thermonaut reads a file

The run stops with an error message, naming the record where it applies, if:

* the first line is not `# PWF ...`, or the file is for another body than `Site:PlanetaryBody`;
* a required column is missing, a record has the wrong number of values, or `start_utc` cannot be parsed;
* `timestep_s` is not positive, or the records are not equally spaced by `timestep_s`;
* the file does not cover the run period;
* `dni_W_m2` or `dhi_W_m2` lies outside 0–2000 W/m²; `T_sky_K`, `T_ground_K` or `T_deep_K` lies outside
  2.7–1000 K or is `nan`; `T_air_K` lies outside 2.7–1000 K (`nan` is allowed: vacuum); `ground_albedo` lies
  outside 0–1; `pressure_Pa` lies outside 0–200 kPa; `wind_m_s` lies outside 0–100 m/s.

There are deliberately **no Earth range checks**: a lunar-noon surface at 390 K or a Martian night at 160 K is
valid data.

## Using a PWF file

In the IDF:

```
Site:PlanetaryBody,
  Habitat, Mars, EarthClock, 2030, autocalculate, 70300, 0.265, 0.15, 6.0, 0.0,
  autocalculate, autocalculate, autocalculate, autocalculate, 3.0, 710, Climatology, 0.5, 0, 0, 0, 3.2, 2.0,
  jezero.pwf;                       !- Planetary Weather File Name
```

No EPW is then needed (`energyplus -d out habitat.idf`). Thermonaut writes a calendar-only EPW to the output
folder for its run-period machinery, keeps computing the sun from its own ephemeris, and interpolates every
other value from the PWF file to its time step (solar columns at mid-interval, state columns at interval end).

## Producing PWF files from other sources

Any tool can write PWF. Mars Climate Database (MCD) output or rover data can be converted by filling the required
columns; quantities a source lacks (e.g. `T_deep_K`) can be taken from a file that `export_pwf.py` writes for the
same site.
