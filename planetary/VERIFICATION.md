# ExoBEM-Core verification (M2)

All runs: Windows 11, MSVC 14.44 (VS 2022 Build Tools), Release build of v26.2.0 + ExoBEM-Core changes
(patch sets m1, m1b, m1c, m2, m2b in `planetary/tools/`).

## 1. Earth: identical to EnergyPlus v26.2.0

`planetary/tools/earth_regression.py` runs each example file with the unmodified v26.2.0 build and with
ExoBEM-Core (Chicago O'Hare TMY3) and compares every number of the full ESO time series.

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
hooks of M2.

## 2. Unit tests

The full EnergyPlus unit-test suite (`energyplus_tests.exe`, `BUILD_TESTING=ON`) passes on the fork:
**2379 tests from 33 test suites, 2379 passed, 0 failed** (3.0 min).

## 3. Moon and Mars: agreement with the Python reference ExoBEM

### 3.1 Regolith-shielded module (cases `moon_equator`, `mars_jezero`)

Horizontal cylinder r = 3 m, L = 10 m, 16 facets, 1 m regolith over MLI (Moon) or aerogel (Mars), 70.3 kPa /
26.5 % O₂ cabin, constant internal gains 3240 W, ideal loads 18/27 °C, 3-min steps, CondFD with the regolith
k(T) and cp(T) tables. ExoBEM is run with planar layers (as in the engine). ExoBEM-Core is run in two modes:
**generator** (its own C++ port of the environment models) and **PWF** (reading the planetary weather file
that ExoBEM wrote for its own run, with no EPW).

| Quantity | Moon equator, 2nd lunation (720 h) | Mars Jezero, days 16–31 (384 h) |
|---|---|---|
| Sensible cooling, C++ generator / C++ PWF / Python (kWh) | 2305.8 / 2305.8 / 2306.0 (−0.01 %) | 748.7 / 747.2 / 753.7 (−0.66 % / −0.86 %) |
| Hourly cooling RMSE, generator / PWF (W) | 0.3 / 0.3 | 13 / 17 |
| Regolith surface temperature RMSE, generator / PWF (K) | 0.05 / 0.000 | 0.21 / 0.000 |
| Deep regolith temperature (C++ / Python) | −14.87 / −14.87 °C | −48.83 / −48.83 °C |
| Direct normal irradiance R² | 0.9999 | 0.9999 |
| Top facet outside / inside face RMSE (K) | 0.33 / 0.002 | 0.61–0.63 / 0.05–0.06 |
| Interior convection coefficient (C++ / Python, W/m²K) | 0.83 / 0.83 | 1.14 / 1.13 |

With the PWF file the environment is identical in both programs (RMSE 0), so the remaining differences are in
the heat-balance solution (CondFD versus ExoBEM's stretched finite volumes, start-up of the Martian regolith
cover).

### 3.2 NASA-class lunar surface habitat (case `lunar_habitat`)

ExoBEM's example `lunar_surface_habitat.json`: 4 crew, 174 m³ vertical cylinder on legs, beta cloth / MLI
(R 19.2 m²K/W) / aluminium / panel, 56.5 kPa / 34 % O₂ cabin at 20–25 °C and RH 30–60 %, 14 kW of electric
power inside the shell (life support, electrolysis, fans, lighting, avionics with cold plates), crew sensible and
latent heat on BVAD schedules, internal mass. `planetary/cases/make_habitat_case.py` writes the IDF from
ExoBEM's model (CTF; latent heat as OtherEquipment latent fraction; cold-plate and electrolysis chemical
energy as the "lost" fraction; humidistat ideal loads). The lunar-equator environment is read from a PWF file.
Comparison over days 4–30 (648 h):

| Quantity | ExoBEM-Core | ExoBEM | Difference |
|---|---|---|---|
| Sensible cooling (kWh) | 3723.0 | 3723.6 | −0.02 % (hourly RMSE 10 W, R² 0.9999) |
| Latent cooling (kWh) | 138.2 | 139.4 | −0.9 % |
| Outside face RMSE, south wall / roof / floor (K) | | | 0.32 / 0.09 / 0.03 |
| Inside face RMSE (K) | | | 0.10–0.12 |
| Mean relative humidity | 48 % | 60 % | ideal-loads supply-air convention (see note) |

Note: EnergyPlus's ideal loads air system dries the supply air while it cools, so the cabin settles below the
60 % humidistat limit; ExoBEM's condensing heat exchanger holds exactly 60 %. The latent energy, which over time
equals the crew's moisture production, agrees within 1 %.

## 4. PV in vacuum (case `pv_vacuum`)

The lunar case with two equivalent one-diode PV modules (horizontal and east-facing, Decoupled mode) on
detached shading surfaces. The cell temperature must satisfy the vacuum energy balance
(τα − η) G = ε σ (T⁴ − T_f⁴) + ε σ (T⁴ − T_b⁴) with the sky and regolith temperatures seen by each face.

| Module | Residual, 99th percentile | Steps with residual > 1 W/m² | Sunlit cell temperature | Night minimum |
|---|---|---|---|---|
| Horizontal | 0.014 W/m² | 65 of 9600 (58 below the engine's 30 W/m² insolation threshold) | up to 336 K | 79 K |
| East-facing | 0.070 W/m² | 22 of 9600 (efficiency iteration exits after the first pass) | up to 359 K | 79 K |

`pv_refused.idf` (Ulleberg dynamic cell model and a Li-ion battery without a zone) stops with the two
expected severe errors from the planetary input validator.

## Notes

* CondFD cannot resolve the 4 mm aluminium shell (stock check thickness < √(3αΔt)); in the regolith-module input
  its heat capacity is lumped into the interior panel and its resistance (3·10⁻⁵ m²K/W) is dropped. The NASA-class
  habitat uses CTF and keeps the aluminium.
* Regolith covers have thermal time constants of months (Mars, 1 m) to years (Moon). ExoBEM-Core starts CondFD
  walls from their steady k(T) profile and corrects it with the real inside-face temperature after warm-up; the
  deep regolith temperature comes from a periodic equilibrium of the regolith column over the preceding year.
* The engine evaluates the sun at the end of each time step (EnergyPlus convention); ExoBEM at the middle.
