# Thermonaut verification (M2e)

All runs: Windows 11, MSVC 14.44 (VS 2022 Build Tools), Release build of v26.2.0 + Thermonaut changes
(patch sets m1, m1b, m1c, m2, m2b, m2c, m2d, m2e in `planetary/tools/`).

## 1. Earth: identical to EnergyPlus v26.2.0

`planetary/tools/earth_regression.py` runs each example file with the unmodified v26.2.0 build and with
Thermonaut and compares every number of the full ESO time series (about 4.7 million values per weather file),
with Chicago O'Hare TMY3 and, from M2e, also Phoenix Sky Harbor TMY3 (`--weather`).

| Example file | Covers | Result |
|---|---|---|
| 1ZoneUncontrolled | CTF, TARP/DOE-2 convection, solar | identical |
| 1ZoneUncontrolledFourAlgorithms | CTF, CondFD, EMPD, HAMT algorithm mix | identical |
| 1ZoneUncontrolledCondFDWithVariableKat24C | CondFD with k(T) | identical |
| 1ZoneUncontrolled_FCfactor_Slab_UGWall | ground contact, F/C factor | identical |
| 1ZoneUncontrolled_win_1 | windows | identical |
| 5ZoneAirCooled | VAV, DX, sizing, design days | identical |
| 5ZoneAirCooledConvCoef | user convection coefficients | identical |
| 5ZoneWaterSystems | plant, water use | identical |
| ShopWithPVandBattery | PV, electric storage | identical |
| RefBldgSmallOfficeNew2004_Chicago | DOE reference building | identical |
| EMPD5ZoneWaterCooled_HighRHControl | moisture (EMPD), chillers | identical |
| ZoneCoupledKivaConvection | Kiva foundation | identical |
| DaylightingDeviceShelf | daylighting | identical |
| SolarCollectorFlatPlateWater | solar thermal collector | identical |
| HAMT_HourlyProfileReport | (fails in both builds with this weather file; not a fork issue) | n/a |

**14 / 14 runnable files are bit-for-bit identical** with both weather files after every patch set, including the
PV and weather-file hooks of M2, the start-up and Mars long-wave changes of M2c–M2d and the input checks of M2e.
The claim covers these files, climates and this build (MSVC 14.44, Windows 11).

## 2. Unit tests

The full EnergyPlus unit-test suite (`energyplus_tests.exe`, `BUILD_TESTING=ON`) passes on the fork:
**2379 tests from 33 test suites, 2379 passed, 0 failed** (3.0 min).

## 2a. Planetary tests (M2e)

The upstream unit tests do not exercise the planetary mode. `planetary/tests/run_planetary_tests.py` runs 23
end-to-end tests: valid habitat inputs with and without a weather file; weather files for the wrong body, with a
missing column, negative irradiance, missing ground temperature, albedo above 1, unequal spacing, short coverage or
no PWF header (rejected with the record number); refusal of infiltration, Earth-fitted PV models, a battery without
a zone, a negative horizon, SimpleCombined outside convection, one time step per hour, unscheduled water mains,
EcoRoof, windows, an air-cooled chiller, F-factor floors and the CO2 balance; and `Site:PlanetaryBody` with
Body = Earth, whose output is identical to the same file without it. **23 / 23 pass** (`tests/test_results.json`).
The weather file of the tests is written from the engine's own generator (`tools/export_pwf.py`).

`planetary/tools/rerun_cases_check.py` reruns every verification case below with the current build and checks
that its output is identical to the recorded one: all six cases are identical with M2e (the generator-mode cases
against the M2d recordings).

## 2b. Audit traceability (M2e)

Every row of the six audit reports (271 rows: 252 prioritized findings and 19 notes) was traced to the v26.2.0
source and to its disposition in Thermonaut: `audit/inventory/audit_inventory.csv` (merged by
`audit/inventory/merge_inventory.py`). 264 citations were found at the stated line, 3 had moved, 4 cite no line.
Dispositions: modified 62, refused 91, avoided by design 65, deferred 22, harmless 31. The pass found refusals that
DESIGN.md listed but the validator did not implement; M2e implements them and adds a backstop that stops a
planetary run if any outdoor-air node exists. The two open P0 rows are the one-step lag of the exterior long-wave
coefficients, which EnergyPlus also uses on Earth.

## 2c. Start-up and sensitivity (M2e)

`planetary/cases/robustness.py` (results in `cases/robustness.json`). Against a long spin-up ending on the same
date (each run sets its own reference year, so both see the same environment), the corrected start of the Mars
module differs from a 25-month spin-up by −0.88 % over the final 16 days, and a two-lunation lunar run differs from
a 36-month spin-up by +1.07 % over the final lunation: a regolith cover keeps about 1 % of start-up memory, so
design studies should spin up for a year or more. The 31-day Mars result changes by −0.25 % for a minimum warm-up of
1 day, by +0.01 % / −0.02 % for CondFD discretization constants 10 / 90 and by +0.002 % for a 2-minute step, and by
+0.83 % for a 20-day warm-up. (A step longer than 3 minutes is not possible: EnergyPlus runs CondFD with at least
20 steps per hour.) One-at-a-time input sensitivity of the cooling energy: lunar habitat MLI R ±25 % gives
−3.4 / +2.2 %, beta-cloth optics up to ±0.7 %, regolith properties and a 5° horizon below 0.35 %; Mars module dust
optical depth 0.3 / 1.5 gives +2.9 / −2.6 %, regolith thermal inertia and albedo about ±0.5 %, wind below 0.1 %.
`cases/mars_convection_scope.py`: Ra 8e2–8e4, Re 2.0e4–2.8e4, Pr 0.77, Knudsen number below 2e-5 (continuum).

## 3. Moon and Mars: independent references and closed-form checks

### 3.1 Sun position against JPL Horizons

`planetary/cases/compare_horizons.py` compares the engine's hourly solar altitude with NASA JPL Horizons
(Sun, apparent azimuth/elevation from a topocentric site, airless; tables in `planetary/cases/horizons/`).

| Site, period | Altitude RMSE, all hours | RMSE / bias, sunlit hours | Sunlit hours, engine / Horizons |
|---|---|---|---|
| Moon, Mare Tranquillitatis (0.674° N, 23.473° E), 59 days | 0.11° | 0.12° / −0.08° | 710 / 712 |
| Mars, Jezero (18.44° N, 77.45° E), 31 days | 0.40° | 0.36° / −0.26° | 338 / 337 |

The Mars bias is the EnergyPlus convention of evaluating the sun at the end of each 3-minute step (the Sun moves
14.6°/h on an Earth clock at Mars).

### 3.2 Lunar regolith against Diviner

The engine's own environment generator at the lunar equator (second lunation): regolith surface 388 K at noon and
94 K before dawn (Diviner equatorial ≈ 385–390 K and ≈ 95 K; Vasavada et al. 2012, Hayne et al. 2017); 258 K at
3 m depth; at 1 m, the depth of the reference, the engine gives 253 K against ≈ 252–256 K (0.5 m 252 K, 2 m 256 K).

### 3.3 Exterior boundary against closed-form balances

`planetary/cases/check_boundary.py` reruns two cases with 3-minute outputs and checks the outer faces against
their defining equations:

* **Moon, vacuum** (NASA-informed habitat, every outer face, 201,600 face-steps): convective heat gain exactly zero;
  outer-face balance (solar + long-wave + convection + conduction) closes to rounding; net long-wave equal to
  εσ[F_sky(T_sky⁴ − T⁴) + F_g(T_g⁴ − T⁴)] within 0.65 W/m² RMSE (mean magnitude 82 W/m²; 99 % of steps within
  0.18 W/m²). The larger residuals (13–22 of 14,400 steps per wall) occur only in the step in which sunlight
  reaches or leaves a wall and its temperature jumps by 30–37 K: EnergyPlus linearizes the long-wave term about the
  previous step's temperature.
* **Mars, convection** (top facet of the regolith-shielded module): the engine's exterior coefficient is within
  −1.8 % (RMSE 1.9 %) of an independent calculation with the same correlations but CO2 properties from the NIST
  Chemistry WebBook at 700 Pa (5,265 steps with film temperature ≥ 216.6 K, the range of the NIST data).

### 3.4 Martian sky long-wave against MEDA and the 2018 dust storm

`planetary/cases/mars_sky_check.py` runs the Jezero case over 2029–2030 (more than one Martian year) with the
nominal dust climatology and with a global storm (optical depth 6 between Ls 190 and 270). Clear-season (Ls 30–150)
mean downwelling long-wave: **30.1 W/m²** (MEDA/TIRS ≈ 30 W/m², Martínez et al. 2023). Sol-mean air temperature over
the ten sols nearest Ls 230, storm minus nominal: **−4.5 K** (Curiosity in 2018: about −4 K; Viúdez-Moreiras et
al. 2019, Guzewich et al. 2019). These are the targets to which the three long-wave parameters were fitted (M2c),
so the check confirms that the engine reproduces the fit over a full year rather than validating it.

## 4. Verification cases and the weather-file round trip

`planetary/cases/roundtrip_check.py` runs each case with the engine's own environment generator, writes the
generated environment to a planetary weather file (`tools/export_pwf.py`) and runs the case again reading that
file. Both runs see the same environment, so their difference measures the reader (interpolation to the time
step, interval-mean solar values) and nothing else. The exported files are the weather files of the cases.

### 4.1 Regolith-shielded module (cases `moon_equator`, `mars_jezero`)

Horizontal cylinder r = 3 m, L = 10 m, 16 facets, 1 m regolith over MLI (Moon) or aerogel (Mars), 70.3 kPa /
26.5 % O₂ cabin, constant internal gains 3240 W, ideal loads 18/27 °C, 3-min steps, CondFD with the regolith
k(T) and cp(T) tables.

| Quantity | Moon equator, 2nd lunation (720 h) | Mars Jezero, days 16–31 (384 h) |
|---|---|---|
| Sensible cooling, generator / weather file (kWh) | 2302.43 / 2302.43 (+0.0000 %) | 719.41 / 717.77 (−0.23 %) |
| Hourly cooling RMSE (W) | 0.0004 | 4.3 |
| Regolith surface temperature RMSE (K) | 0.0001 | 0.0001 |
| Top facet outer / inner face RMSE (K) | 0.00001 / 0.000001 | 0.011 / 0.015 |

On Mars the file stores solar quantities as interval means, which smooths the rapid sunrise and sunset by half
a step; on the Moon the sun moves 0.5° per hour and the two runs agree to rounding.

### 4.2 NASA-informed lunar surface habitat (case `lunar_habitat`)

4 crew, 174 m³ vertical cylinder on legs, beta cloth / MLI (R 19.2 m²K/W) / aluminium / panel, 56.5 kPa / 34 % O₂
cabin at 20–25 °C and RH 30–60 %, 14 kW of electric power inside the shell (life support, electrolysis, fans,
lighting, avionics with cold plates), crew sensible and latent heat on BVAD schedules, internal mass (CTF; latent
heat as OtherEquipment latent fraction; cold-plate and electrolysis chemical energy as the "lost" fraction;
humidistat ideal loads). Lunar equator, 30 days from 1 January 2030; results over days 4–30 (648 h):

| Quantity | Value |
|---|---|
| Sensible / latent cooling (kWh) | 3723.0 / 138.2 |
| Mean / peak sensible load (kW) | 5.75 / 7.46 |
| Outer face, south wall / floor (°C) | −151 to 60 / −147 to 120 |
| Weather-file run: sensible / latent cooling difference | −0.0002 % / −0.000002 % |
| Cabin relative humidity | 47–50 % |
| Coldest inside surface minus dew point, minimum (K) | 12.1 (8.5 if the cabin were held at its 60 % limit) |

EnergyPlus's ideal loads air system dries the supply air while it cools, so the cabin settles below the 60 %
humidistat limit; a condensing heat exchanger controlled to the limit would hold 60 %, and the dew-point margin of
the coldest inside surface would be 3.6 K smaller (`cases/humidity_check.py`). The latent energy, which over time
equals the crew's moisture production, is not affected.

## 5. PV in vacuum (case `pv_vacuum`)

The lunar case with two equivalent one-diode PV modules (horizontal and east-facing, Decoupled mode) on
detached shading surfaces. The cell temperature must satisfy the vacuum energy balance
(τα − η) G = ε σ (T⁴ − T_f⁴) + ε σ (T⁴ − T_b⁴) with the sky and regolith temperatures seen by each face.

| Module | Residual, 99th percentile | Steps with residual > 1 W/m² | Sunlit cell temperature | Night minimum |
|---|---|---|---|---|
| Horizontal | 0.014 W/m² | 65 of 9600 (58 below the engine's 30 W/m² insolation threshold) | up to 336 K | 79 K |
| East-facing | 0.070 W/m² | 21 of 9600 (efficiency iteration exits after the first pass) | up to 359 K | 79 K |

`pv_refused.idf` (Ulleberg dynamic cell model and a Li-ion battery without a zone) stops with the two
expected severe errors from the planetary input validator. The efficiency η in the balance is iterated within each
time step (EnergyPlus's existing loop, restarted at η = 0 every step, relative tolerance 0.1 %); no value is lagged
from the previous step. Module emissivity is a constant 0.85 on both faces.

## Notes

* M2c recalibrated the Martian downwelling long-wave model (sky emissivity 0.12 + 0.10 τ, dust re-emission 0.20,
  previously 0.08 + 0.125 τ and 0.45) so that a global dust storm lowers the sol-mean air temperature by about 4 K,
  as Curiosity observed in 2018, instead of raising it by 18 K (section 3.4). Earth results remain identical.
* CondFD cannot resolve the 4 mm aluminium shell (stock check thickness < √(3αΔt)); in the regolith-module input
  its heat capacity is lumped into the interior panel and its resistance (3·10⁻⁵ m²K/W) is dropped. The NASA-informed
  habitat uses CTF and keeps the aluminium.
* Regolith covers have thermal time constants of months (Mars, 1 m) to years (Moon). Thermonaut starts CondFD
  walls from their steady k(T) profile and corrects only the part that warm-up could not reach (M2d); the deep
  regolith temperature comes from a periodic equilibrium of the regolith column over the preceding year.
* The engine evaluates the sun at the end of each time step (EnergyPlus convention).
