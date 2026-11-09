# ExoBEM-Core verification (M1)

All runs: Windows 11, MSVC 14.44 (VS 2022 Build Tools), Release build of v26.2.0 + ExoBEM-Core changes.

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

**14 / 14 runnable files are bit-for-bit identical.**

## 2. Moon and Mars: agreement with the Python reference ExoBEM

Same habitat in both programs (ExoBEM case study module: horizontal cylinder r = 3 m, L = 10 m, 16 facets,
1 m regolith cover over MLI (Moon) or aerogel (Mars), 70.3 kPa / 26.5 % O₂ cabin, constant internal gains
3240 W, ideal loads 18/27 °C, 3-min time step). ExoBEM-Core uses CondFD with the Hayne et al. (2017) k(T) and cp(T)
tables; Python ExoBEM uses its own implicit finite-volume solver with a stretched grid. The environments are
generated independently by the C++ port and by the Python code.

| Quantity | Moon equator, 2nd lunation (720 h) | Mars Jezero, days 16–31 (384 h) |
|---|---|---|
| Sensible cooling, C++ / Python | 2305.8 / 2306.0 kWh (−0.01 %) | 737.5 / 742.9 kWh (−0.7 %) |
| Hourly cooling RMSE | 0.3 W | 14 W |
| Regolith surface temperature RMSE | 0.05 K (range −178.8 … 114.4 °C) | 0.21 K |
| Direct solar R² | 0.9998 | 0.9999 |
| Top facet outside face RMSE | 0.33 K | 0.64 K |
| Top facet inside face RMSE | 0.002 K | 0.05 K |
| Interior convection coefficient | 0.83 / 0.83 W/m²K | 1.18 / 1.15 W/m²K |

Plots: `cases/*/comparison.png`; numbers: `cases/*/comparison.json`.

### Notes

* CondFD cannot resolve the 4 mm aluminium shell (stock check thickness < √(3αΔt)); in the ExoBEM-Core input its
  heat capacity is lumped into the interior panel and its resistance (3·10⁻⁵ m²K/W) is dropped.
* Regolith covers have thermal time constants of months (Mars, 1 m) to years (Moon). ExoBEM-Core therefore starts
  CondFD walls from their steady profile (with k(T)) between the mean outer-face temperature and the zone, and
  corrects the profile with the real inside-face temperature at the end of warm-up. Without this, the Mars
  cooling load was 32 % too high after 31 days.
* The C++ engine evaluates the sun at the end of each time step (EnergyPlus convention); the Python reference at
  the middle. At a 3-min step the difference is negligible.

## 3. Unit tests

The full EnergyPlus unit-test suite (`energyplus_tests.exe`, built with `BUILD_TESTING=ON`) passes on the fork:
**2379 tests from 33 test suites, 2379 passed, 0 failed** (3.1 min).
