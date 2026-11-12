# Thermonaut design (planetary mode for the EnergyPlus v26.2.0 engine)

Thermonaut is a research fork of EnergyPlus v26.2.0 (BSD-3 + DOE naming clause; it is *not* EnergyPlus and
is not endorsed by DOE, NLR/NREL or the EnergyPlus developers). It adds a **planetary mode** that lets the full
EnergyPlus zone heat balance simulate pressurized habitats on the Moon and Mars. Its verification is described in
[VERIFICATION.md](VERIFICATION.md).

The six code audits in `planetary/audit/` list every Earth-only assumption that was found (about 260 findings with
file and line). This document records the design decisions taken from them.

## Guiding rules

1. **Earth stays bit-for-bit.** Planetary mode is active only when the input has a `Site:PlanetaryBody` object
   with Body = Moon or Mars. Every change is either behind `state.dataPlanet->active` or replaces a literal by a
   variable whose Earth value is the same literal (IEEE results unchanged). Verified with Earth example files.
2. **Reuse, don't rewrite.** The planetary values are injected where EnergyPlus already reads its environment
   (weather arrays, sun direction, ground temperature, outside coefficients). The heat balance, conduction, shading,
   view factors, ideal loads and reporting are reused unchanged.
3. **Refuse what cannot be right.** Objects that need outdoor air (infiltration, ventilation, outdoor-air systems,
   air-cooled condensers, cooling towers, ...) stop the run with a clear error off-Earth instead of giving a
   plausible-looking wrong answer.

## Decisions

| Topic | Decision | Audit refs |
|---|---|---|
| Time base (Moon) | **Earth clock**: an hour stays 3600 s and a day 86400 s (UTC). Crew schedules work as on Earth. The Sun moves at 360°/708.7 h. | 01 T-open-2, 02 Q2 |
| Time base (Mars) | M1: Earth clock (hour 3600 s). M2: optional **sol clock** (hour = sol/24 = 3698.97 s) via a run-time `SecInHour`, following the 01 plan (4 setters + ~95 edits + CTF unit fix). | 01 §3.1 |
| Sun position | The engine's hour angle `15(12-(t+EoT)) + (TZM-Lon)` becomes `rate·(12-(t+EoT)) + (TZM-Lon)` with `rate = dataEnvrn->HourAngleRate` (15.0 on Earth, 360/synodic-day-in-clock-hours off-Earth). Off-Earth `TZM = Lon`, and for each day the generator fits `EoT` and declination to the Mars24 / lunar ephemeris at mid-day. All shading and sun routines downstream are reused. The shading update interval is forced to 1 day. | 02 S01–S08 |
| Weather | M1 reads a placeholder EPW (calendar and location only) and **overwrites** every per-timestep weather value in `ReadWeatherForDay` with the planetary generator (no EPW range clamps apply). M2 removes the EPW requirement. | 01 T21–T29 |
| Environment physics | Vacuum sky 2.725 K (Moon); Mars delta-Eddington dust two-stream, τ(Ls) climatology and storm option, seasonal pressure, downwelling IR, air-temperature surrogate; 1-D regolith column (Hayne 2017 Moon, thermal-inertia Mars) spun up before the run. | 02 §4 |
| Pressure | **Option B**: off-Earth, `OutBaroPress` carries the **cabin pressure** (all ~350 zone/HVAC uses become right with no edits; every outdoor-air user is blocked), and a new `AmbientBaroPress` holds the real outdoor pressure for exterior convection and outputs. `StdBaroPress`/`StdRhoAir` follow the cabin. | 03 §3, 06 H01–H05 |
| Cabin gas | M1: Earth moist-air psychrometrics at cabin pressure (26.5 % O2 changes cp and R by < 0.4 %). Gas mixture block is M2. | 03 2b |
| Outdoor air temperature | Mars: near-surface air from the generator. Moon: set to the regolith skin temperature (no physical meaning, but any residual "ground = air" assumption then gets the right temperature). The −100 °C sanity checks are skipped off-Earth. | 03 2d, 04 S05 |
| Exterior long-wave | Off-Earth `SurfAirSkyRadSplit = 1` (no air radiation) and the ground long-wave temperature is the regolith skin temperature. | 02 S20–S27, 04 S02–S04 |
| Exterior convection | Off-Earth replaced by `Planetary::exteriorConvection`: 0 in vacuum; Mars: physical mixed natural/forced correlation for CO2 at ambient pressure and body gravity. The `LowHConvLimit` floor is bypassed. | 04 C01–C05 |
| Interior convection | Off-Earth replaced by the same physical correlation for the cabin gas at cabin pressure and body gravity, with a cabin air velocity (default 0.15 m/s). | 04 C06–C09, 03 2c |
| Gravity | `Planetary::gravity(state)` (9.807 on Earth). M1 uses it in the new correlations; windows and AirflowNetwork are refused off-Earth (M2e); stack-driven objects are refused with the outdoor-air objects. | 03 2c, 05 W01–W06 |
| Conduction | CTF and CondFD unchanged on the Earth clock. CondFD node clamp −100 °C relaxed to −270 °C off-Earth. Regolith with k(T), cp(T) via existing CondFD inputs. | 04 K01–K13 |
| Ground contact | `Ground` boundary uses the planetary deep-regolith temperature. Kiva, GroundDomain, F/C-factor blocked off-Earth. | 04 G01–G05 |
| Unsupported objects | Central validator after input processing (`Planetary::ValidateInput`): fatal error for windows, outdoor-air objects and outdoor-air zone units, infiltration/ventilation, air-/evap-cooled condensers, chillers, coils and refrigeration condensers, air-source plant heat pumps, cooling towers and fluid coolers, combustion and wind generators, PVWatts, Sandia and Ulleberg PV, DElight, Kiva, GroundDomain, F/C-factor constructions, ground heat exchangers, solar collectors, EcoRoof, HAMT (also per surface), movable insulation, SimpleCombined outside convection, the CO2 balance, design days and sizing, one time step per hour and water use without scheduled mains. Backstop (M2e): a planetary run stops if any outdoor-air node exists. Every audit finding is traced to this list or to a hook in `audit/inventory/audit_inventory.csv`. | 03, 04, 05, 06 |
| Heat rejection | M3: new `HeatRejection:SpaceRadiator` plant component (FluidCooler pattern + flat-plate collector surface link). | 06 H30–H38 |
| Planetary weather files (M2) | Optional `Planetary Weather File Name` (PWF, [docs/weather_format.md](docs/weather_format.md)). Read in `Planetary::GetInput`; values are interpolated to the engine's time step (solar columns at mid-interval, state columns at interval end); the sun is still the engine's daily-fitted ephemeris. A calendar-only EPW is written to the output folder and used for the run-period dates, so the user needs no EPW. | 01 T21–T29 |
| PV (M2) | One-diode (TRNSYS) model in Decoupled mode: cell temperature from a radiative (Moon) or radiative + convective (Mars) energy balance of a thin module whose faces see sky and regolith (`Planetary::pvCellTemperatureK`). Simple PV unchanged. Sandia Decoupled and Ulleberg dynamic (fitted to Earth air) refused. | 06 H36–H39 |
| Batteries (M2) | Li-ion NMC batteries must be in a zone off-Earth (their thermal model would otherwise use the outdoor air). | 06 |
| Mars long-wave (M2c) | Sky emissivity 0.12 + 0.10 τ and dust re-emission 0.20, recalibrated so that a global dust storm lowers the sol-mean air temperature by about 4 K, as observed in 2018. | – |
| Start-up correction (M2d) | After warm-up, each CondFD node receives only the part of the inside-temperature correction that warm-up could not deliver, from an implicit solve of the construction's own node network for a unit inside step over the warm-up period. Removes the one-day transient. | – |
| Physics corrections (M2b) | From an independent review of the planetary equations: disk visibility by area; Mars beam by Beer's law (forward-scattered peak counted as diffuse); Mars pressure cycle minimum at Ls 157; cabin cp by mass fraction; deep regolith from a periodic equilibrium of the column over the preceding year. | – |

## Tracking EnergyPlus releases

Every change is applied by an idempotent patch script (`planetary/tools/apply_hooks_*.py`) that finds a short,
unique anchor in a stock source file and inserts a hook, plus the new module `PlanetaryBody.cc/.hh` and the IDD
object. To move to a new EnergyPlus release: check out the release tag, copy the planetary module and
`planetary/` folder, run the patch scripts in order (each fails loudly if its anchor has moved instead of patching
the wrong place), fix any moved anchors by hand, then rerun the Earth regression against an unmodified build of
the same release, the unit-test suite and the planetary verification cases. Because the hooks sit at a few
interfaces (weather arrays, sun direction, exterior and interior coefficients, CondFD start-up, PV cell
temperature, input validation) rather than inside the solvers, most releases should need only anchor updates;
releases that restructure those interfaces need the corresponding hook rewritten.

## Milestones

* **M1 (this branch)**: `Site:PlanetaryBody`, ephemerides, environment generator, sun-rate hook, option-B pressure,
  exterior/interior convection, LW split and ground temperature, CondFD clamp, validator, outputs. Target: the
  lunar and Mars regolith-module cases run with ideal loads; Earth example files give identical results to
  unmodified v26.2.0.
* **M2 (done; M2c–M2d added the Mars long-wave recalibration and the start-up fix)**: planetary weather files with no EPW, PV in vacuum, battery placement check, physics corrections, NASA-informed habitat case. Still open: sol clock for Mars, cabin gas mixture, gravity everywhere, planetary design days.
* **M2e**: physical range checks of planetary weather files and an exporter that writes them from the internal generator (`tools/export_pwf.py`); validator gaps closed after every audit finding was traced to the code (`audit/inventory`); planetary test suite (`tests/run_planetary_tests.py`).
* **M3**: sol clock, space radiator plant component and heat-pump lift, cabin gas psychrometrics, planetary sizing, condensing heat exchanger, windows.
