# Thermonaut verification (M2d)

All runs: Windows 11, MSVC 14.44 (VS 2022 Build Tools), Release build of v26.2.0 + Thermonaut changes
(patch sets m1, m1b, m1c, m2, m2b, m2c, m2d in `planetary/tools/`).

## 1. Earth: identical to EnergyPlus v26.2.0

`planetary/tools/earth_regression.py` runs each example file with the unmodified v26.2.0 build and with
Thermonaut (Chicago O'Hare TMY3) and compares every number of the full ESO time series.

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

**14 / 14 runnable files are bit-for-bit identical** after every patch set, including the PV and weather-file
hooks of M2 and the start-up and Mars long-wave changes of M2c–M2d.

## 2. Unit tests

The full EnergyPlus unit-test suite (`energyplus_tests.exe`, `BUILD_TESTING=ON`) passes on the fork:
**2379 tests from 33 test suites, 2379 passed, 0 failed** (3.0 min).

## 3. Moon and Mars: independent references and closed-form checks

These checks do not involve ExoBEM.

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
3 m depth, consistent with ≈ 252–256 K measured near 1 m plus the geothermal gradient.

### 3.3 Exterior boundary against closed-form balances

`planetary/cases/check_boundary.py` reruns two cases with 3-minute outputs and checks the outer faces against
their defining equations:

* **Moon, vacuum** (NASA-class habitat, every outer face, 201,600 face-steps): convective heat gain exactly zero;
  outer-face balance (solar + long-wave + convection + conduction) closes to rounding; net long-wave equal to
  εσ[F_sky(T_sky⁴ − T⁴) + F_g(T_g⁴ − T⁴)] within 0.64 W/m² RMSE (mean magnitude 82 W/m²; 99 % of steps within
  0.18 W/m²). The larger residuals (13–22 of 14,400 steps per wall) occur only in the step in which sunlight
  reaches or leaves a wall and its temperature jumps by 30–37 K: EnergyPlus linearizes the long-wave term about the
  previous step's temperature.
* **Mars, convection** (top facet of the regolith-shielded module): the engine's exterior coefficient is within
  −1.8 % (RMSE 1.9 %) of an independent calculation with the same correlations but CO2 properties from the NIST
  Chemistry WebBook at 700 Pa (5,269 steps with film temperature ≥ 216.6 K, the range of the NIST data).

## 4. Moon and Mars: code-to-code check against ExoBEM

ExoBEM is an independent Python implementation of the same physics. Agreement shows that the two codes solve the
same equations; it does not validate the equations, which is the role of section 3.

### 4.1 Regolith-shielded module (cases `moon_equator`, `mars_jezero`)

Horizontal cylinder r = 3 m, L = 10 m, 16 facets, 1 m regolith over MLI (Moon) or aerogel (Mars), 70.3 kPa /
26.5 % O₂ cabin, constant internal gains 3240 W, ideal loads 18/27 °C, 3-min steps, CondFD with the regolith
k(T) and cp(T) tables. ExoBEM is run with planar layers (as in the engine). Thermonaut is run in two modes:
**generator** (its own C++ port of the environment models) and **PWF** (reading the planetary weather file
that ExoBEM wrote for its own run, with no EPW).

| Quantity | Moon equator, 2nd lunation (720 h) | Mars Jezero, days 16–31 (384 h) |
|---|---|---|
| Sensible cooling, C++ generator / C++ PWF / Python (kWh) | 2302.4 / 2302.4 / 2306.0 (−0.16 % / −0.15 %) | 719.4 / 717.8 / 728.2 (−1.21 % / −1.43 %) |
| Hourly cooling RMSE, generator / PWF (W) | 5.0 / 5.0 | 23 / 28 |
| Regolith surface temperature RMSE, generator / PWF (K) | 0.05 / 0.000 | 0.21 / 0.000 |
| Deep regolith temperature (C++ / Python) | −14.87 / −14.87 °C | −50.85 / −50.84 °C |
| Direct normal irradiance R² | 0.9999 | 0.9999 |
| Top facet outside / inside face RMSE (K) | 0.33 / 0.018 | 0.65–0.67 / 0.08–0.10 |
| Interior convection coefficient (C++ / Python, W/m²K) | 0.83 / 0.83 | 1.20 / 1.19 |

With the PWF file the environment is identical in both programs (RMSE 0), so the remaining differences are in
the heat-balance solution: CondFD versus ExoBEM's stretched finite volumes, and above all the different starting
states of the regolith cover (ExoBEM: pseudo-transient steady state; Thermonaut: steady k(T) profile with the M2d
post-warm-up correction). Before M2d the full correction was also added to the inner layers, which warm-up had
already brought to the real inside temperature; the cabin then started 2–7 K warm and the cooling load 0.4–2.4 kW
high for about a day. M2d removes that transient (first-hour cooling within 68 W and inner face within 0.4 K of
ExoBEM); the price is that the window agreement, which the old overshoot had partly offset, is now −0.16 % (Moon)
and −1.2 % to −1.4 % (Mars).

### 4.2 NASA-class lunar surface habitat (case `lunar_habitat`)

ExoBEM's example `lunar_surface_habitat.json`: 4 crew, 174 m³ vertical cylinder on legs, beta cloth / MLI
(R 19.2 m²K/W) / aluminium / panel, 56.5 kPa / 34 % O₂ cabin at 20–25 °C and RH 30–60 %, 14 kW of electric
power inside the shell (life support, electrolysis, fans, lighting, avionics with cold plates), crew sensible and
latent heat on BVAD schedules, internal mass. `planetary/cases/make_habitat_case.py` writes the IDF from
ExoBEM's model (CTF; latent heat as OtherEquipment latent fraction; cold-plate and electrolysis chemical
energy as the "lost" fraction; humidistat ideal loads). The lunar-equator environment is read from a PWF file.
Comparison over days 4–30 (648 h):

| Quantity | Thermonaut | ExoBEM | Difference |
|---|---|---|---|
| Sensible cooling (kWh) | 3723.0 | 3723.6 | −0.02 % (hourly RMSE 10 W, R² 0.9999) |
| Latent cooling (kWh) | 138.2 | 139.4 | −0.9 % |
| Outside face RMSE, south wall / roof / floor (K) | | | 0.32 / 0.09 / 0.03 |
| Inside face RMSE (K) | | | 0.10–0.12 |
| Mean relative humidity | 48 % | 60 % | ideal-loads supply-air convention (see note) |

Note: EnergyPlus's ideal loads air system dries the supply air while it cools, so the cabin settles below the
60 % humidistat limit; ExoBEM's condensing heat exchanger holds exactly 60 %. The latent energy, which over time
equals the crew's moisture production, agrees within 1 %.

## 5. PV in vacuum (case `pv_vacuum`)

The lunar case with two equivalent one-diode PV modules (horizontal and east-facing, Decoupled mode) on
detached shading surfaces. The cell temperature must satisfy the vacuum energy balance
(τα − η) G = ε σ (T⁴ − T_f⁴) + ε σ (T⁴ − T_b⁴) with the sky and regolith temperatures seen by each face.

| Module | Residual, 99th percentile | Steps with residual > 1 W/m² | Sunlit cell temperature | Night minimum |
|---|---|---|---|---|
| Horizontal | 0.014 W/m² | 65 of 9600 (58 below the engine's 30 W/m² insolation threshold) | up to 336 K | 79 K |
| East-facing | 0.070 W/m² | 22 of 9600 (efficiency iteration exits after the first pass) | up to 359 K | 79 K |

`pv_refused.idf` (Ulleberg dynamic cell model and a Li-ion battery without a zone) stops with the two
expected severe errors from the planetary input validator. The efficiency η in the balance is iterated within each
time step (EnergyPlus's existing loop, restarted at η = 0 every step, relative tolerance 0.1 %); no value is lagged
from the previous step. Module emissivity is a constant 0.85 on both faces.

## Notes

* M2c recalibrated the Martian downwelling long-wave model in both codes (sky emissivity 0.12 + 0.10 τ, dust
  re-emission 0.20, previously 0.08 + 0.125 τ and 0.45) so that a global dust storm lowers the sol-mean air
  temperature by about 4 K, as Curiosity observed in 2018, instead of raising it by 18 K. The Mars column above is
  from the M2c runs; the colder Martian environment raises the envelope heat flow and with it the slowly decaying
  start-up residual of the regolith cover (−0.66 % → −0.88 % with the generator). Earth results remain identical.
* CondFD cannot resolve the 4 mm aluminium shell (stock check thickness < √(3αΔt)); in the regolith-module input
  its heat capacity is lumped into the interior panel and its resistance (3·10⁻⁵ m²K/W) is dropped. The NASA-class
  habitat uses CTF and keeps the aluminium.
* Regolith covers have thermal time constants of months (Mars, 1 m) to years (Moon). Thermonaut starts CondFD
  walls from their steady k(T) profile and corrects it with the real inside-face temperature after warm-up; the
  deep regolith temperature comes from a periodic equilibrium of the regolith column over the preceding year.
* The engine evaluates the sun at the end of each time step (EnergyPlus convention); ExoBEM at the middle.
