# Audit 03 - Psychrometrics, air/gas properties, barometric pressure, gravity, outdoor air, airflow

Scope: `Psychrometrics.hh/.cc`, `PsychCacheData.hh`, `DataEnvironment.hh/.cc`, the pressure/humidity parts of
`WeatherManager.cc`, every `OutBaroPress` / `StdBaroPress` / `StdRhoAir` user, every gravity constant in
`src/EnergyPlus` and the compiled `third_party` code, the simple airflow objects (`ZoneInfiltration:*`,
`ZoneVentilation:*`, ...), AirflowNetwork pressure/gravity, and the zone air heat/moisture/contaminant balance in
`ZoneTempPredictorCorrector.cc` (ZTPC). All line numbers are from the `planetary` branch (v26.2.0).
Counts come from grep over `*.cc *.hh *.cpp *.hpp` in `src/EnergyPlus` (subdirectories included).

## 1. Summary

- The engine has **one pressure for all air**: `state.dataEnvrn->OutBaroPress` (the weather file value). It is used
  509 times in 75 files for zone air, HVAC air and outdoor air alike. About 350 of those uses are inside the
  pressure shell (zone air ~166, HVAC air side ~184), about 133 are really outdoor, and 26 are weather/rating
  bookkeeping. On the Moon (0 Pa) the zone air capacitance and moisture capacitance become 0, which gives NaN
  humidity. `PsyWFnTdpPb` **hangs forever** at PB = 0. On Mars (~700 Pa) the cabin air would have 0.7 % of its
  real thermal mass. **A separate zone/cabin pressure is the single most important P0 change in this area.**
- The psychrometric constants (cp_da 1004.84, R_da 287.0, M_w/M_da 0.62198) describe Earth air. For a
  70.3 kPa / 26.5 % O2 cabin they are within 0.4 % of the right values (cp ≈ 1004, R ≈ 286.0, eps ≈ 0.6197), so
  **pressure is P0 and gas composition is P1**. Composition matters for other cabins (pure O2: −9 %) and for CO2
  outdoors (R 192, cp ~760). It can be added as a gas-parameter block, with the Earth branch keeping the literal code.
- The water-only functions (Psat, Tsat, hfg, rho_v, the caches keyed on pressure) do not depend on the gas and
  can stay as they are.
- Gravity: `Constant::Gravity = 9.807` is used at only 10 sites. Another **38 hard-coded literals** (9.8, 9.80,
  9.806, 9.807, 9.81, 9.80665, and two latitude-dependent Earth formulas) appear in 18 files, plus
  Windows-CalcEngine (`GRAVITYCONSTANT`, 4 uses) and ssc PVWatts (2). All of them must follow the body's gravity,
  with the Earth literal kept for bit-identity.
- Outdoors: every simple infiltration/ventilation object, the earth tube, cool tower, thermal chimney, hybrid
  ventilation, AFN external nodes and outdoor-air intakes is physically meaningless in vacuum or 700 Pa CO2. Some
  of them produce NaN (outdoor-density basis with rho = 0). They must give a **severe error off-Earth**. Cabin
  leakage then needs its own small model (P1). Weather-side checks (EPW pressure 31-120 kPa, outdoor T > −100 °C,
  rain/snow, lapse rate, Earth wind profile) must be branched.
- Difficulty: **medium-high in volume, low in physics**. Most of the work is a mechanical, reviewed substitution of
  ~350 `OutBaroPress` uses, plus ~50 gravity sites and input checks. Earth stays bit-identical if every new
  quantity is either a getter that returns the old variable on Earth, or an `if (earth) {old literal code}` branch.

## 2. Findings

### 2a. Psychrometrics (gas-dependent constants, low-pressure failure modes, caches)

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| PSY-01 | Psychrometrics.hh:538, 571, 582 | `PsyRhoAirFnPbTdbW` (state, constexpr, `_fast`) | R_da = 287.0 J/kg-K; 1.6077687 = M_da/M_w; W floor 1e-5. 242+3 call sites, 59 files | Cabin 26.5 % O2: R = 286.0 (−0.35 %); pure O2: 259.8; CO2: 192. Pressure argument is the real problem (see PRS-*) | Gas block `PsyDryGas{R, invEps}`. Earth branch keeps the literal expression. Keep the **constexpr** overload Earth-only (AFN uses it for 101325 Pa / 20 °C crack reference conditions) | P1 |
| PSY-02 | Psychrometrics.hh:663, 674 (`PsyHFnTdbW`), 707/732 (`PsyCpAirFnW`), 759 (`PsyTdbFnHW`), 984 (`PsyWFnTdbH`), 1674 (`PsyDeltaHSen*`) | moist-air enthalpy/cp | cp_da = 1.00484e3; h_g0 = 2.50094e6; cp_v = 1.85895e3. Calls: PsyHFnTdbW 475/65 files, PsyCpAirFnW 395/88, PsyTdbFnHW 121/32, PsyWFnTdbH 141/25, DeltaHSen 27/10 | Only cp_da depends on the gas. 26.5 % O2 mass-weighted (N2 1040, O2 918) gives ≈1004 (−0.05 %); pure O2 918 (−8.6 %) | `cpDry` in gas block, Earth literal branch. Use the mass-weighted cp in verification | P1 |
| PSY-03 | Psychrometrics.hh:810, 820, 1252, 1306, 1319, 1372, 1447, 1549; .cc:486 (9 occurrences) | eps = M_w/M_da | 0.62198. Also `0.622`/`0.621945` literals: EcoRoofManager.cc:280, 317, 361, 366, 378; MoistureBalanceEMPDManager.cc:702-703; IndoorGreen.cc:537 | Cabin 0.6197; O2 0.563; CO2 0.409. W stays "kg water / kg dry gas", which is consistent once eps is set | `eps` in gas block (same branch). The 8 module literals only matter in modules that are unsupported off-Earth (EcoRoof) or are indoor P1 (EMPD, IndoorGreen) | P1 |
| PSY-04 | Psychrometrics.cc:491, 493; .hh:1448 | wet-bulb equations in `PsyTwbFnTdbWPb_raw`, `PsyWFnTdbTwbPb` | ASHRAE psychrometric eq.: 2501, 2.326, **1.006** (cp_da kJ), 1.86, 4.186; ice: 2830, 0.24, 2.1; hh:1448 uses an implicit cp_da = 1.0 and 2.381, 1.805. Lewis number = 1 | Fine for N2/O2 cabin. Wrong cp for O2/CO2 gases | Replace 1.006 / 1.0 by `cpDry/1000` in the non-Earth branch only | P2 |
| PSY-05 | Psychrometrics.hh:937 | `PsyVFnTdbWPb` | 1.59473e2 (= R_da/1.8, Rankine form), 1.6078. 3 calls | small | non-Earth branch: `R*(1+invEps*w)*(T+273.15)/PB` | P2 |
| PSY-06 | Psychrometrics.cc:970-1012, 1022 | `PsyTsatFnHPb_raw` | 9 polynomial pieces fitted to sea-level air; refined by secant iteration only if \|PB−1.0133e5\|/1.0133e5 > 1 % | At 70.3 kPa the iteration (≤30 × `PsyWFnTdbTwbPb`) always runs: correct but slower. The 2^20 cache (hash of H, Pb) hides most of the cost. 143 calls / 21 files | Nothing for correctness. Check runtime | P2 |
| PSY-07 | Psychrometrics.cc:632-770 (`PsyPsatFnTemp`), 1255-1437 (`PsyTsatFnPb`, 1651-point spline); .hh:591-643 (hfg 2500940 + 1858.95 T − 4180 T), 1129-1220, 1609-1650 (`CPCW`/`CPHW` 4180, `RhoH2O`) | water-only properties | pure water; Psat floor 0.001405 Pa below −100 °C; Tsat range 0.0017-1.555e6 Pa | none (gas-independent) | **Leave alone** | - |
| PSY-08 | Psychrometrics.hh:1306-1325 | `PsyWFnTdpPb` validity loop | `while (PDEW1 >= PB) {DeltaT++; PDEW1 = Psat(TDP-DeltaT)}` | PB = 0 (Moon): Psat never drops below its 0.0014 Pa floor, so the loop **never ends (hang)**. 51 calls / 22 files, e.g. ConvectionCoefficients.cc:2114, 2269, 4273, 4757; ZTPC:3545. At PB = 700 Pa it returns W at a dew point near 2 °C (nonsense) | Never pass outdoor pressure for zone/HVAC air (PRS-05..07). Also add a guard `if (PB <= Psat_floor) return 0.0` in the non-Earth branch | P0 |
| PSY-09 | Psychrometrics.hh:1252, 1372; .cc:459-466 | `PsyRhFnTdbWPb`, `PsyWFnTdbRhPb`, `PsyTwbFnTdbWPb_raw` at low PB | `max(PB-PDEW, 1000.0)` clamp; tBoil = PsyTsatFnPb(Patm) | PB < Psat gives RH < 0 or > 1; the 1000 Pa clamp makes W meaningless at 700 Pa; Patm = 0 gives the Tsat "Pressure out of range" warning and Twb does not converge (warnings every timestep from WeatherManager:2126-2138) | Same as PSY-08: never call these with vacuum or Mars pressure. Off-Earth outdoor psychrometrics are skipped (OUT-03) | P0 |
| PSY-10 | PsychCacheData.hh (Twb 2^20 keyed Tdb,W,Pb; Psat 2^20 keyed T; Tsat 2^20 keyed Pb, 24 bits; Tsat_HPb 2^20 keyed H,Pb, 28 bits); Psychrometrics.cc:108-131 `InitializePsychRoutines`; .hh:1703-1706 `last_Patm/last_tBoil` | memo caches | results assume a fixed gas | Twb and Tsat_HPb values depend on cp/eps. Mixing cabin and outdoor gases through the same functions would poison the caches. Pressure-keyed entries for 70 kPa and 101 kPa can coexist | Use psychrometrics **only for cabin gas**. Set the gas block before the first psych call (input stage), or call `InitializePsychRoutines` after setting it. Outdoor CO2 gets its own small gas module (no psych) | P1 |
| PSY-11 | DXCoils.cc:17787-18186 (10 × `1005`), HVACVariableRefrigerantFlow.cc:10814-13288 (6), MundtSimMgr.cc:101, HWBaseboardRadiator.cc:965, EcoRoofManager.cc:121, 124 (Rair 286, Cpa 1005.6), PhotovoltaicThermalCollectors.cc:1467, 1545 (101.3/(0.287 T)), WindowEquivalentLayer.cc:5952-6139 (5 × PAtmSeaLevel/(287.097 T)), ExtendedHeatIndex.cc:124 (287.04), DataConvergParams.hh:82 (`HVACCpApprox` 1004.844) | module-local air constants | Earth air, often at 101325 Pa | Small cp/R errors; PVT and WindowEquivalentLayer use sea-level density | DX/VRF: P1 with the HVAC audit. Others: flag unsupported or leave. Leave `HVACCpApprox` (tolerance only) | P2 |

### 2b. Barometric pressure, standard pressure/density, zone vs outdoor

Exact counts. Token `OutBaroPress`: 565 occurrences in 81 files. Of these, `state.dataEnvrn->OutBaroPress` (incl.
`m_state.`) has **509 occurrences in 75 files**. The rest: 12 `holdOutBaroPress`, 7+7 EMS `Today/TomorrowOutBaroPress`,
4 `OutBaroPressAt`, wvars fields. `StdBaroPress`: 166 / 39 files. `StdRhoAir`: 355 / 65 files.
`StdPressureSeaLevel`: 56 / 11 files. Literal `101325`: 36 / 19 files.

Per-file count of `dataEnvrn->OutBaroPress` (heuristic split: Z = zone air, H = HVAC/node air, O = outdoor,
W = weather/rating; the split comes from a context classifier and was then hand-corrected, ±10):
DXCoils 60 (O 31, Z/H 23, W 6) · HeatBalanceSurfaceManager 42 (O 25 exterior moisture, Z 17) · PackagedThermalStorageCoil 33 ·
EvaporativeCoolers 31 · HeatRecovery 29 · WaterCoils 23 · ZoneTempPredictorCorrector 21 (Z 19, O 2) · VariableSpeedCoils 20 ·
ZoneEquipmentManager 16 (Z 12, O 4) · RefrigeratedCase 15 · ConvectionCoefficients 10 (Z 9, O 1) · HVACManager 10 (Z 8, O 2) ·
HVACVariableRefrigerantFlow 10 · Humidifiers 9 · AirflowNetwork/Solver 9 · UnitarySystem 8 · PurchasedAirManager 7 ·
SystemAvailabilityManager 7 · WeatherManager 7 · MoistureBalanceEMPD 6 · RoomAirModelAirflowNetwork 6 · UFADManager 6 ·
UserDefinedComponents 6 · WaterThermalTanks 6 · EarthTube 5 · IndoorGreen 5 · ThermalComfort 5 · TranspiredCollector 5 ·
DataZoneEquipment 4 · HeatBalanceHAMT 4 · NodeInputManager 4 · OutAirNodeManager 4 · PhotovoltaicThermalCollectors 4 ·
VentilatedSlab 4 · ZoneContaminantPredictorCorrector 4 · Coils/CoilCoolingDX 4 · CoolTower 3 · DisplacementVentMgr 3 ·
ThermalChimney 3 · AirflowNetwork/Elements 3 · 2 each: ExhaustAirSystemManager, HeatBalanceAirManager, HeatingCoils,
HybridEvapCoolingModel, LowTempRadiantSystem, MixedAir, MundtSimMgr, PondGroundHeatExchanger, SetPointManager,
WaterToAirHeatPumpSimple, WaterUse, WindowManagerExteriorThermal, ZonePlenum · 1 each (21 files): ChilledCeilingPanelSimple,
ChillerIndirectAbsorption, CondenserLoopTowers, DataEnvironment, EvaporativeFluidCoolers, FluidCoolers, HVACControllers,
HVACUnitaryBypassVAV, MicroturbineElectricGenerator, OutdoorAirUnit, PlantLoopHeatPumpEIR, RoomAirModelManager,
RoomAirModelUserTempPattern, SizingManager, SplitterComponent, SwimmingPool, SystemReports, WindowComplexManager,
WindowManager, ZoneDehumidifier, CoilCoolingDXAshrae205Performance, CoilCoolingDXCurveFitOperatingMode.
**Totals: zone air ≈166, HVAC air inside the hull ≈184, outdoor ≈133, weather/rating ≈26.**

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| PRS-01 | DataEnvironment.hh:128; WeatherManager.cc:2113 | `OutBaroPress` (only steady assignment); temporary overrides listed in PRS-09 | one pressure for zone, HVAC and outdoors | Moon 0 Pa / Mars ~700 Pa reaches the zone air heat balance | Add a cabin pressure (see §3.1). Leave `OutBaroPress` = true outdoor pressure | P0 |
| PRS-02 | ZTPC:3210, 3966 (`AirPowerCap = V·mult·rho(OutBaroPress)·cp/Δt`), 4569 + 4598 (moisture `C = rho·V·mult/Δt`), 4625 (`WZSat`), 4188, 4263 (RH), 3545-3626 (humidistat RH/dew-point setpoints), 3741, 3783, 3804 (latent load), 4927 (inverse model), 5686 (component loads); ZTPC:4662 uses `StdBaroPress` for zone dew point | zone air heat & moisture balance | rho at outdoor P | Moon: AirPowerCap = 0 and C = 0. Moisture third-order `(B + C·…)/(11/6·C + A)` with A = 0 gives inf/NaN, and ZTPC:4606 `W1 + B / C` gives inf. NaN then spreads through cp into ZT. Analytical air-temp branch ZTPC:4014, 4130 divides by AirPowerCap. Mars: cabin air thermal mass ×0.007, saturation/RH wrong | All 19 zone uses → `zoneBaroPress()`; 4662 → same. Keep the 2 outdoor uses (4869, 5116) on OutBaroPress | **P0** |
| PRS-03 | HeatBalanceSurfaceManager.cc:6046, 6084 (heat index / resilience RH, dew point), 8286, 8289 (interior EMPD/HAMT mass-transfer coefficient), 8914-8956 (CondFD/HAMT interior); HeatBalanceAirManager.cc:4737, 4761; ConvectionCoefficients.cc:2114, 2269, 2700, 4271-4273, 4757 (interior: zone vol. flow, ceiling diffuser, ISO15099 window, adaptive classification, user curves); ZoneEquipmentManager.cc:2536, 2544, 5256, 5766, 5769, 6259, 6531, 6610-6635, 6767, 6770 (zone-side density for mixing/sizing); HVACManager.cc:2291, 2482, 2606, 2635, 2657, 2691, 2727, 2815 (zone air reports); ZoneContaminantPredictorCorrector.cc:1728, 1837, 2332; ThermalComfort.cc:576, 579, 845, 922 (`PInAtmospheres = OutBaroPress/101325`), 1503; PurchasedAirManager.cc:2234, 2289, 2291, 2539, 2593, 2879, 2880; DataZoneEquipment.cc:2219, 2234, 2250, 2269 (node `.Press`); ZonePlenum.cc:746, 847; WindowManager.cc:2561; WindowManagerExteriorThermal.cc:813 (Tarcog indoor environment); MoistureBalanceEMPDManager.cc:570 (diffusivity ∝ 1/P), 702-703; HeatBalanceHAMTManager (4); SystemReports (1); RoomAir models: UFAD 6, DisplacementVent 3, Mundt 2, RoomAirModelAirflowNetwork 6, UserTempPattern 1, RoomAirModelManager 1; IndoorGreen 5; WaterUse 2; SwimmingPool 1 | other zone-side air | rho, RH, Tdp at outdoor P | Same failures as PRS-02 (NaN, and the PSY-08 hang via ConvectionCoefficients:2114 when the adaptive algorithm is used) | → `zoneBaroPress()`. P0 subset for a single-zone ideal-loads run: HBSM, HeatBalanceAirManager, ConvectionCoefficients, ZoneEquipmentManager zone side, HVACManager, ZCPC, ThermalComfort, PurchasedAir, DataZoneEquipment, WindowManager(+ExteriorThermal:813), EMPD/HAMT (~95 uses). RoomAir/IndoorGreen/WaterUse/SwimmingPool: P1 | P0 / P1 |
| PRS-04 | DXCoils (evaporator side), WaterCoils 23, PackagedThermalStorageCoil (evap, 2527-3795), HeatRecovery 29, EvaporativeCoolers (primary), VariableSpeedCoils, Humidifiers 1088-1218, UnitarySystem, MixedAir 4138, 4152, NodeInputManager 1092-1121, SetPointManager 2391, 2415, SplitterComponent 345, RefrigeratedCase (case/zone), UserDefinedComponents, ExhaustAirSystemManager, HybridEvap, LowTempRadiant, ChilledCeiling, ZoneDehumidifier, WaterToAirHPSimple, HeatingCoils, HVACControllers, … | HVAC air inside the hull (~184) | outdoor P | Same as zone | → `zoneBaroPress()` file by file, reviewed together with the HVAC audit | P1 |
| PRS-05 | ZTPC:4869, 5116; ZoneEquipmentManager.cc:5773, 6774, 6922; HVACManager.cc:2301, 2496; ZCPC:2072 | infiltration/ventilation outdoor-side density | outdoor P | Moon rho = 0, so `VolumeFlowRate = MCpI/AirDensity/CpAir` = 0/0 = **NaN** (ZEM:6799, 6814, 6830) | Keep OutBaroPress. Objects are errored off-Earth (OUT-06/07) | P0 (via error) |
| PRS-06 | HeatBalanceSurfaceManager.cc:7392-7994 (23 uses: exterior CondFD/HAMT mass-transfer coefficient `HMassConvExtFD = h/(rho(OutBaroPress)·cp)`), 10085-10086 (exterior vented cavity) | exterior moisture | outdoor P | Moon: rho = 0 gives **division by zero** (inf) for every CondFD/HAMT exterior surface | Off-Earth: skip exterior moisture transfer (HMassConvExtFD = 0) for CondFD/HAMT; vented cavity unsupported | P0 (if CondFD/HAMT used) |
| PRS-07 | DXCoils `OutdoorPressure =` (29 lines: 9399-17467), HVACVariableRefrigerantFlow 451-14731 (8), UnitarySystem 14561-14580, VariableSpeedCoils 5318, 6508, PackagedTESCoil 2509, CoilCoolingDX* (3), CondenserLoopTowers 1742 + 14 `StdBaroPress`, EvaporativeFluidCoolers 1321, FluidCoolers 904, EvaporativeCoolers 1118-1120 (secondary), PlantLoopHeatPumpEIR 1020, MicroturbineElectricGenerator 1296, OutAirNodeManager 604-622, OutdoorAirUnit 1244, VentilatedSlab 1642, EarthTube 884, 1084, 1146, CoolTower 577-586, TranspiredCollector 1112-1775, PondGroundHeatExchanger 598, AFN Solver 7308, 9444, 9691, ConvectionCoefficients 6367 (ClearRoof), SizingManager 357, EcoRoofManager 268 (`StdBaroPress`) | outdoor air for condensers, towers, intakes, exterior convection | outdoor P, Earth air | Moon: no air at all. Mars: CO2 at 700 Pa through air-psychrometrics with R = 287 | Keep OutBaroPress. Modules flagged unusable in vacuum and unsupported on Mars (heat-rejection audit). ClearRoof/exterior convection use the outdoor gas model (convection audit) | P1 |
| PRS-08 | WeatherManager.cc:2126-2138, 2243-2244 | `SetCurrentWeather` outdoor psychrometrics | derive OutHumRat, OutWetBulb, OutDewPoint, OutAirDensity from RH and OutBaroPress | Moon: PsyTsatFnPb(0) warnings and Twb not converged every timestep. Mars: W from RH at 700 Pa is meaningless | Branch: off-Earth OutHumRat = 0, OutRelHum = 0, OutWetBulb = OutDryBulb, OutDewPoint = OutDryBulb (no meaning), OutEnthalpy = cp·T, OutAirDensity = P/(R_gas·T) (Mars) or 0 (Moon) | **P0** |
| PRS-09 | CoilCoolingDX.cc:852-873; DXCoils.cc:7038-7090, 7211-7262; VariableSpeedCoils.cc:3491-3546, 3577-3631; WaterCoils.cc:1755-1815 (6 save/restore pairs) | rating-point overrides `OutBaroPress = StdPressureSeaLevel` | coil is rated at sea level by temporarily overwriting the global | After the coil code moves to `zoneBaroPress()`, the override no longer reaches it off-Earth | Wrap in an RAII `ScopedRatingPressure` that sets both OutBaroPress and the cabin override to 101325. Earth unchanged | P1 |
| PRS-10 | WeatherManager.cc:2896-2903; 1751 | EPW pressure missing/out-of-range | `AtmPress <= 31000 or > 120000` is counted and **replaced by `wvarsMissing.OutBaroPress` (= StdBaroPress)** | A Mars weather file (600-900 Pa) is silently replaced by ~101 kPa; a Moon file (0) too | Off-Earth: planet-specific range (Moon: must be 0; Mars: 100-2000 Pa); missing value = `OutStdBaroPress` | **P0** |
| PRS-11 | WeatherManager.cc:3554-3569; Energy+.idd.in:1189-1194 | `SizingPeriod:DesignDay` Barometric Pressure | IDD min 31000 / max 120000; values >10 % from StdBaroPress are replaced by StdBaroPress | Mars/Moon design days rejected or overwritten | Relax the IDD min to 0. Compare against `OutStdBaroPress` | P0 |
| PRS-12 | WeatherManager.cc:4476-4478, 709; Energy+.idd.in:1030-1034 | `StdBaroPress = 101325·(1−2.25577e-5·z)^5.2559`; `StdRhoAir = rho(StdBaroPress, 20 °C, 0)`; `rhoAirSTP` (101325, 20 °C; only used at HVACFourPipeBeam.cc:719); `Site:Location` Elevation −300 … <8900 m | Earth standard atmosphere | StdRhoAir (355 uses: sizing, volumetric→mass for fans, ideal loads `PurchasedAirManager.cc:1200, 1205`, AFN) would be Earth density at site elevation. Mars/Moon site elevations (−4…+6 km vs datum) can fall outside the IDD limits | Off-Earth: `StdBaroPress` := nominal cabin pressure, `StdRhoAir` := cabin gas at 20 °C dry (these mean "standard indoor/HVAC air"). New `OutStdBaroPress` := planet surface-pressure model (Mars e.g. 610·exp(−z/11100) Pa, Moon 0) for PRS-10/11. Relax elevation limits off-Earth. Keep `rhoAirSTP` (Earth rating reference) | **P0** |
| PRS-13 | `StdBaroPress` outdoor-meaning users: WeatherManager 1751, 3556-3568; CondenserLoopTowers 2536-4197 (14); EvaporativeFluidCoolers (6); FluidCoolers (4); EcoRoofManager:268; AFN Solver:355-361, 13784, 13788 (node density = StdBaroPress + PZ for both zone and external nodes) | | | If StdBaroPress becomes the cabin value, these see cabin pressure | Towers/coolers/EcoRoof are unsupported off-Earth anyway. AFN: interior nodes use cabin P, external nodes are forbidden | P2 |
| PRS-14 | literal `101325` (36 in 19 files): AFN Elements.cpp:552, 640, 3592, 4009, Properties.cpp:68-69, Elements.hpp:656, 677 (crack reference conditions); AFN Solver.cpp:352, 13482, 13503 (`PB = 101325` initial absolute pressure); WindowManager.cc:6479, WindowEquivalentLayer.cc:8088 (nominal U-factor rating, dry air); ThermalComfort.cc:922; CondenserLoopTowers (4); SteamCoils (3); SteamBaseboardRadiator; EMPD; HeatRecovery; Microturbine | | | | **Leave** the reference/rating ones. Change the AFN Solver 13503 initial PB to the cabin pressure (P2). ThermalComfort:922 numerator → cabin | P2 |
| PRS-15 | DataEnvironment.cc:191-233 `OutBaroPressAt` (StdGravity 9.80665, M 0.028964, R 8.31432, lapse −0.0065); only user WindTurbine.cc:956 | barometric formula with height | Earth troposphere | Wrong off-Earth | WindTurbine unsupported off-Earth; leave | P2 |

### 2c. Gravity

Physics key: **NC** = natural-convection Grashof/Rayleigh; **STK** = stack/buoyancy-driven flow (∝ √(g·Δρ)); **HYD** =
hydrostatic pressure (ρ·g·Δz); **MECH** = weight/load.

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| GRV-01 | DataGlobalConstants.hh:589 `Constant::Gravity` | 10 uses: AirflowNetwork/Solver.cpp:7405 (duct NC); ConvectionCoefficients.cc:6458 (`CalcASTMC1340ConvCoeff`, attic NC); TarcogShading.cc:799, 1107 (STK shading-gap flow); ThermalEN673Calc.cc:415, 484 (gap NC); ThermalISO15099Calc.cc:2551 (glazing film NC), 2704 (gap NC); WindowEquivalentLayer.cc:5796 (gap NC), 8094 (indoor film NC) | 9.807 | NC: Gr ∝ g, h_turb ∝ g^1/3 (Moon ×0.55, Mars ×0.72 at the same ρ). STK flows ∝ √g | `state.dataEnvrn->gravity` (body g, = 9.807 on Earth). Use it at these 10 sites. `constexpr` users need a non-constexpr local | P1 (windows/attic), P0 for ASTMC1340 only if used |
| GRV-02 | ConvectionCoefficients.cc:2337 (`CalcTrombeWallIntConvCoeff`), 2680 (`CalcISO15099WindowIntConvCoeff`, uses OutBaroPress 2700), 4027 (`DynamicIntConvSurfaceClassification` zone GrH 4265), 5729 (`CalcFohannoPolidoriVerticalWall`), 6353 (`CalcClearRoof`, exterior, GrLn 6369) | interior/exterior NC | 9.81 (comment at 5729 notes the mismatch with 9.807) | as GRV-01. The fixed ν = 15.89e-6 / k = 0.0263 (300 K, 1 atm) also hide pressure: ν ∝ 1/P | `g = earth ? 9.81 : body.g`; ν/k from cabin gas at cabin P (convection audit) | P0 (interior convection of a habitat), P1 window |
| GRV-03 | ConvectionCoefficients.cc (all dimensional NC correlations: ASHRAE simple 1.31·ΔT^1/3, TARP/Walton, Alamdari-Hammond 5018-5133, Khalifa 5134-5241, Awbi-Hatton, Beausoleil-Morrison, Karadag, MoWiTT natural 6025) | implicit g and ρ | calibrated at g0, 101 kPa air | h_turb ∝ (g·ρ²·cp·k²/μ)^1/3 ≈ (g/g0)^1/3·(P/P0)^2/3: Moon cabin 70.3 kPa ×0.43, Mars cabin ×0.57 | Scale factor (g/g0)^1/3·(P/P0)^2/3 (convection audit owns this) | P0 (cross-ref) |
| GRV-04 | ZoneEquipmentManager.cc:5619 `StdGravity 9.80665` → 6648, 6652 (`ZoneRefrigerationDoorMixing`, STK); 6044 `9.81` (`ZoneVentilation:WindandStackOpenArea`, STK) | simple airflow | 9.80665 / 9.81 | door mixing inside cabin: valid physics with body g; WindAndStack: object errored off-Earth | 5619 → body g; 6044 left (object disabled) | P2 |
| GRV-05 | AirflowNetwork/Elements.cpp:1884 (`GDRHO = 9.8·Δρ`, two-way flow in large openings, STK); 3215, 3216, 3225, 3226 (9.81, horizontal opening buoyancy, Cooper); 4062 (`G = 9.780373·(1+0.0052891 sin²φ − 0.0000059 sin²2φ)`, latitude formula, HYD profile via `lclimb` 4157-4229); Solver.cpp:13801, 13804 (9.80, stack pressure between linked nodes, HYD) | AFN | 4 different Earth values | Inter-module hatches in a cabin: buoyancy ×g_body/g0 | Each → `earth ? literal : body.g` (keep literals for bit-identity) | P2 |
| GRV-06 | ThermalChimney.cc:886, 921 | stack draft | 9.8 | object vents to outdoors: disabled | leave (error off-Earth) | P2 |
| GRV-07 | WindowManager.cc:3788, 3977 (airflow-window gap STK, 9.81), 4534 (gap NC, 9.807), 6480 (nominal rating film, 9.81) | windows | | gap NC and airflow windows | 3788/3977/4534 → body g; **leave 6480** (NFRC nominal rating stays Earth) | P1 |
| GRV-08 | WindowEquivalentLayer.cc:5960, 6018, 6047, 6122, 6147 | shade/drape gap Ra | 9.81 with ρ at `PAtmSeaLevel` | | body g + cabin P | P1 |
| GRV-09 | RefrigeratedCase.cc:14819 (latitude formula, as GRV-05) → 14896, 14915 | walk-in door infiltration (Gosney-Olama, STK) | 9.780373(…) | inside cabin: valid with body g | body g | P2 |
| GRV-10 | EcoRoofManager.cc:122 (Richardson no. 386); PondGroundHeatExchanger.cc:722→766 (water NC); PhotovoltaicThermalCollectors.cc:1369→1472, 1566 (BIPVT gap NC); SolarCollectors.cc:1939→1993, 2039→2060 (ICS gap and water NC, 9.806); TranspiredCollector.cc:1727 (baffle-gap buoyancy, 9.807); WeatherManager.cc:242 (`UpdateUnderwaterBoundaries`, water NC 9.81) | exterior/outdoor modules | 9.81/9.806/9.807 | modules unsupported off-Earth except PVT/ICS (PV/solar audit) | body g where kept | P2 |
| GRV-11 | HVACVariableRefrigerantFlow.cc:14992, 15152 | refrigerant pipe height head (HYD) | 9.80665 | head ∝ g | body g | P2 |
| GRV-12 | DataEnvironment.cc:213 | `OutBaroPressAt` StdGravity | 9.80665 | see PRS-15 | leave | P2 |
| GRV-13 | third_party/Windows-CalcEngine/src/Common/src/Constants.hpp:11 `GRAVITYCONSTANT 9.807` → Tarcog/IGUGapLayer.cpp:84 (gap NC), IGUVentilatedGapLayer.cpp:107 (STK), IndoorEnvironment.cpp:131 (indoor film NC), DeflectionFromCurves.cpp:131 (glass self-weight, MECH) | WCE | static const | All four need body g (deflection: lunar g reduces sag) | Change to `ConstantsData::gravity()` reading a settable static (default 9.807) | P1 |
| GRV-14 | third_party/ssc/shared/lib_pvwatts.cpp:147, 199 (`grashf = 9.8/tave·…`, module NC; also `denair = 0.003484·101325/tave`, 1 atm air, 143) | PVWatts cell temperature (compiled via cmod_pvwattsv5) | 9.8, 1 atm | module NC wrong; in vacuum no convection at all | PV audit: use the vacuum/Mars cell-temperature model rather than patching ssc | P1 (PV) |
| GRV-15 | not compiled: ssc lib_physics.h:41, lib_cec6par, lib_geothermal, lib_wind_obos, tcs/* (CMake-commented); cmod_windpower_eqns.cpp:79 compiled but unused off-Earth; kiva/src: **no gravity or air-pressure literal**; eigen/boost/glfw hits are false positives | | | none | leave | - |

Gravity summary: 10 `Constant::Gravity` uses + 38 literal sites in 18 src files + 5 WCE (1 def, 4 uses) + 2 ssc =
**55 sites**. Only GRV-02/03 (interior convection) are needed for a first opaque single-zone run.

### 2d. Outdoor air, simple airflow, zone balances

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| OUT-01 | DataEnvironment.cc:71-115, 117-155 (`OutDry/WetBulbTempAt`, fatal < −100 °C); DataHeatBalance.cc:145-173, 311-322; DataSurfaces.cc:594-632 (`SetSurfaceOutBulbTempAt`, `Check*OutBulbTempAt` fatal if < −100 °C); WeatherManager.cc:7273 (`WeatherFileTempModCoeff = 0.0065·EarthRadius·1.5/(EarthRadius+1.5)`); DataEnvironment.hh:79-80 (EarthRadius 6356000, lapse 0.0065); HeatBalanceManager.cc:1277-1324 (`Site:HeightVariation`, default gradient 0.0065 at 1316) | local outdoor temperature at height | Earth troposphere lapse 6.5 K/km, Earth radius | Moon: no air temperature; a generator value such as night regolith ~−170 °C triggers a **fatal** (`SetOutBulbTempAt_error`). Mars: lapse/geopotential correction is wrong but tiny | Off-Earth: force `SiteTempGradient = 0` (pass-through, makes the coefficient unused), and lower the −100 °C checks to −273.15 (all 4 sites). Also EPW dry-bulb range [−90, 70] at WeatherManager:2876 (count only) and design-day checks 6149-6275 → planet range | **P0** |
| OUT-02 | DataEnvironment.cc:157-185, 249-276; DataHeatBalance.cc:175-198, 324-330; DataSurfaces.cc:634-660; WeatherManager.cc:7240-7272 (`WeatherFileWindModCoeff = (270/10)^0.14 = 1.5863`); HeatBalanceManager.cc:570-599 (terrain exponent 0.10-0.33, BL 210-460 m) | wind profile | Earth power law, Earth boundary layer | Moon: WindSpeed = 0, harmless. Mars: Earth terrain coefficients scale the met wind (×1.59·(z/370)^0.22) | Off-Earth default `SiteWindExp = 0` (wind used as given by the generator at surface height), unless the user gives `Site:HeightVariation`. Mars log-law profile lives in the environment generator | P1 |
| OUT-03 | `dataEnvrn->OutHumRat` 270 refs / 41 files; `OutWetBulbTemp` 95/21; `OutDewPointTemp` 15/4; `OutRelHum(Value)` 20/8; `OutEnthalpy` 15/11; `OutAirDensity` 5/3 (EvaporativeCoolers:1113, FiniteDifferenceGroundTemperatureModel:281) | outdoor humidity | moist Earth air | see PRS-08 | Values defined in PRS-08 (dry). Any module still pulling outdoor air into the cabin is errored (OUT-06..09) | P0 |
| OUT-04 | WeatherManager.cc:2210-2232 (`IsRain`, `IsSnow`, snow ground-reflectance modifier); `IsRain` 28 refs / 14 files (wet exterior surfaces HBSM:7759, 8021, 8717, 9422; DataSurfaces:290; HAMT, CondFD, ground HX, TranspiredCollector, windows) | precipitation flags | EPW rain/snow | a planetary EPW with junk precipitation columns would wet surfaces (h = 1000, T = wet bulb) | Off-Earth: `UseRainValues = UseSnowValues = false`, `IsRain = IsSnow = false` | P0 (cheap) |
| OUT-05 | ZoneContaminantPredictorCorrector.cc:1177, 1181 (`OutdoorCO2`, `OutdoorGC` from schedules); `OutdoorCO2` 54 refs / 10 files; used in 1747-1748, 1854 (OAMFL/VAMFL/EAMFL/CTMFL/MDotOA terms) and initial values 1322-1362 | outdoor contaminants | ~400 ppm | Mars 950 000 ppm, only reaches the cabin through outdoor-air terms (errored) | Document; keep. The init to `OutdoorCO2` (1322-1339) should use a cabin initial value off-Earth | P2 |
| OUT-06 | HeatBalanceAirManager.cc:238-1340 (`GetSimpleAirModelInputs`: `ZoneInfiltration:DesignFlowRate` 682, `:EffectiveLeakageArea` 927, `:FlowCoefficient` 1008); ZoneEquipmentManager.cc:6740-6860 (`CalcAirFlowSimple` infiltration) | infiltration | outdoor-density basis (6774); Sherman-Grimsrud/AIM-2 stack & wind coefficients calibrated with Earth g/ρ (6801-6830); driving ΔP of a few Pa | Moon: **NaN** (PRS-05). Physically, a cabin at 70 kPa against vacuum/700 Pa *leaks out*: choked flow of cabin gas plus make-up gas from tanks, not outdoor air coming in | Severe error off-Earth for all 3 objects. Add a `ZoneCabinLeakage` model (mass rate or %/day, make-up gas T, W = 0) feeding MCPI/MCPTI/OAMFL with the make-up temperature | P0 (error) / P1 (leakage) |
| OUT-07 | HeatBalanceAirManager.cc:1341-1967 (`ZoneVentilation:DesignFlowRate`, `:WindandStackOpenArea`), 387/431 (`ZoneAirBalance:OutdoorAir`); ZoneEquipmentManager.cc:5745-6100, 6922; EarthTube.cc:151; CoolTower.cc:138; ThermalChimney.cc:165; `AvailabilityManager:HybridVentilation` (SystemAvailabilityManager); `SurfaceProperty:ExteriorNaturalVentedCavity` (HBSM:10075-); `WindowProperty:AirflowControl` with outdoor source/exhaust | natural/outdoor ventilation | outdoor air available | meaningless in vacuum/CO2; NaN with outdoor density | Severe error off-Earth (input stage) | **P0** |
| OUT-08 | AirflowNetwork: `AirflowNetwork:MultiZone:ExternalNode`, WindPressureCoefficient*, Surface openings to outdoors; Solver.cpp:7308 (outdoor ρ for wind pressure), 7553, 8867, 8926, 9444, 9467, 9691; Elements.cpp:4065, 4145-4146; plus GRV-05 | AFN | outdoor air, Earth g, PB 101325 | external links meaningless; internal multizone flow (hatches, fans, ducts) is valid with body g and cabin P | Off-Earth: forbid external nodes and outdoor-facing openings; internal-only AFN with `zoneBaroPress()` and body g | P2 |
| OUT-09 | OutAirNodeManager.cc:540-622 (OA node T/W/Press from outdoors); OA intake users: Controller:OutdoorAir/MixedAir, DOAS (AirLoopHVACDOAS), ZoneHVAC:OutdoorAirUnit, ERV/HRV, ideal-loads OA (PurchasedAirManager.cc:2034, 2338, 2725, 2769) | outdoor air to HVAC | breathable outdoor air | would push 700 Pa CO2 or vacuum "air" into cabin HVAC at cabin pressure | Severe error off-Earth if any OA intake has min/design OA > 0 (ideal loads: OA fields must be blank/0). Air-cooled condenser inlets: heat-rejection audit | P0 (ideal loads), P1 |
| ZHB-01 | ZTPC:3209-3211, 3965-3967 | `AirPowerCap` | V·`ZoneVolCapMultpSens`·ρ(P)·cp(W)/`TimeStepSysSec` | see PRS-02. Also Δt follows the planetary hour (time audit) | cabin P (P0) + cabin gas (P1) | P0 |
| ZHB-02 | ZTPC:4560-4630 (`correctHumRat`), 3735-3810 (predicted latent load), 5097-5163 (inverse model) | moisture balance | `C = ρ·V·ZoneVolCapMultpMoist/Δt`; B, A include `(OAMFL+VAMFL+CTMFL)·OutHumRat`, `EAMFLxHumRat`, `MDotOA·OutHumRat` (4572-4574); latent via `PsyHgAirFnWTdb` (water, fine); saturation clamp `WZSat` at P | B/C NaN at P = 0. Outdoor terms vanish once objects are errored | cabin P. With PSY-03 W keeps the meaning kg water/kg dry cabin gas | P0 |
| ZHB-03 | ZTPC:5242-5243 (`SumMCp = MCPI+MCPV+MCPM+MCPE+MCPC+MDotCPOA`, `SumMCpT … + MDotCPOA·zone.OutDryBulbTemp`), 4853-4859 | air heat balance sums | outdoor T as source temperature | zero when objects are disabled. `ZoneCabinLeakage` would reuse MCPI/MCPTI with the make-up T | none now | info |
| ZHB-04 | ZCPC:1727-1751, 1837-1860, 2332; InternalHeatGains.cc:513 (`CO2RateFactor` 3.82e-8 m³/s-W), 2286-2298 (gas equipment) | CO2/generic contaminant balance | `CO2Gain = V̇_CO2·ρ_zone·1e6` (1734): the generated volume is treated as if measured at zone density | At 70.3 kPa the ppm(v) rise is under-predicted by 101.3/70.3 = **1.44** (the rate factor is a standard-condition volume). Crew limits are on ppCO2, not ppm | Multiply the gains by `rho_std_Earth/rho_cabin` off-Earth. Report ppCO2 (P2) | P1 |
| ZHB-05 | `ZoneCapacitanceMultiplier:ResearchSpecial` → `ZoneVolCapMultpSens/Moist/CO2/GenContam` (used ZTPC:3209, 4598, ZCPC:1751) | capacitance multipliers | scalar | do **not** use them to fake cabin pressure: they do not change mass-flow/density conversions | leave | info |
| ZHB-06 | ThermalComfort.cc:576-579, 845, 922 (`PInAtmospheres = OutBaroPress/101325` in KSU/Pierce), 1503 | comfort models | outdoor P | reduced-pressure comfort | → `zoneBaroPress()` (already in PRS-03) | P1 |

## 3. Recommended implementation

### 3.1 Cabin (zone) pressure - bit-identical on Earth

1. `DataEnvironment.hh` `EnvironmentData`, add:
   ```cpp
   bool   cabinFollowsOutdoor = true;   // Earth default: zone air pressure IS OutBaroPress
   Real64 CabinBaroPress = DataEnvironment::StdPressureSeaLevel; // Pa, used when !cabinFollowsOutdoor
   bool   ratingPressOverride = false;  // set by ScopedRatingPressure (PRS-09)
   Real64 OutStdBaroPress = DataEnvironment::StdPressureSeaLevel;  // standard OUTDOOR pressure
   Real64 gravity = Constant::Gravity;  // body gravity (9.807 on Earth; literal sites keep their own Earth value)
   bool   outdoorIsVacuum = false, outdoorAirUsable = true;
   Real64 zoneBaroPress() const {
       return (cabinFollowsOutdoor || ratingPressOverride) ? OutBaroPress : CabinBaroPress;
   }
   ```
   A getter (not a mirrored copy) means every existing write to `OutBaroPress` (WeatherManager:2113 and the 6
   rating overrides) keeps working on Earth with no extra code, and the value is the same double, so results are
   bit-identical.
2. Input: a new `Building:CabinAtmosphere` (or fields of `Site:PlanetaryBody`): total pressure {Pa} (optional
   schedule), O2 / N2 / CO2 / Ar mole fractions, make-up gas temperature. If absent on Earth: `cabinFollowsOutdoor = true`.
   If absent off-Earth: severe error (no default habitat pressure). Read it in `HeatBalanceManager` before
   `WeatherManager::GetNextEnvironment` reaches line 4476.
3. `WeatherManager.cc:4476-4478`: `if (earth) {unchanged} else {StdBaroPress = CabinBaroPress_nominal;
   StdRhoAir = PsyRhoAirFnPbTdbW(state, StdBaroPress, 20, 0); OutStdBaroPress = planet surface model}`.
   On Earth, also set `OutStdBaroPress = StdBaroPress`. Use `OutStdBaroPress` at 1751, 2896-2903 (with a planet range)
   and 3554-3569. Relax the IDD minimums (Elevation, DesignDay pressure) and check them in code per planet.
4. `SetCurrentWeather` (2113-2244): after 2113 update `CabinBaroPress` from its schedule. Off-Earth, skip the
   psychrometric block 2126-2138 and set the dry values (PRS-08). Force IsRain/IsSnow false (2210-2232).
   `OutAirDensity` from the outdoor gas model.
5. Mechanical substitution `state.dataEnvrn->OutBaroPress` → `state.dataEnvrn->zoneBaroPress()` in the ~350
   indoor uses. Do it in two reviewed passes: **pass A (P0, ~95 uses)** = files in PRS-02/03 P0 list.
   **Pass B (P1, ~255 uses)** = PRS-03 P1 + PRS-04. Leave the ~133 outdoor uses (PRS-05..07) on OutBaroPress.
   Add a unit test that runs one Earth example file before and after each pass with a binary diff of the ESO/SQL
   output.
6. `ScopedRatingPressure` RAII for the 6 rating blocks (PRS-09): saves both values and sets
   `OutBaroPress = 101325, ratingPressOverride = true`.
7. Psychrometric hazards: add `PB > 0` asserts/guards in the non-Earth branch of `PsyWFnTdpPb`, `PsyWFnTdbRhPb`,
   `PsyTwbFnTdbWPb_raw` (PSY-08/09). This is defence in depth; after step 5 they should not be reached.

### 3.2 Cabin gas properties (P1)

- In `Psychrometrics.hh` add `struct PsyDryGas { bool earthAir = true; Real64 cp = 1.00484e3, R = 287.0,
  eps = 0.62198, invEps = 1.6077687, cpWB_kJ = 1.006; };`. Store it as a namespace-scope `inline PsyDryGas cabinGas;`,
  because `PsyCpAirFnW`, `PsyHFnTdbW`, `PsyTdbFnHW` and the constexpr `PsyRhoAirFnPbTdbW` take no `state` and
  have ~1 000 call sites. Every affected function becomes
  `if (cabinGas.earthAir) { <original literal expression> } else { <parametrised> }`. Literal Earth code means the
  Earth results are bit-identical whatever FMA contraction the compiler does.
- Set it once from `Building:CabinAtmosphere` during input, then call `InitializePsychRoutines` (cache flush,
  PSY-10). Mixture rules: M = Σx·M_i; cp = Σ(mass fraction·cp_i) with N2 1040, O2 918, Ar 520, CO2 844 J/kg-K at
  ~295 K; R = 8314.46/M; eps = 18.01528/M.
- Do **not** route outdoor CO2 through psychrometrics. A small `OutdoorGas` (M, cp, Sutherland
  μ/k) serves exterior convection and `OutAirDensity` only.
- Leave the water property functions, CPCW/CPHW, the Tsat/Psat caches, the constexpr Earth density used for AFN
  reference conditions, `rhoAirSTP`, and the nominal window rating at 101325 Pa.

### 3.3 Gravity (P0 for interior convection, rest P1/P2)

- `state.dataEnvrn->gravity` comes from `Site:PlanetaryBody` (Earth: 9.807).
- Helper `inline Real64 bodyG(EnergyPlusData const &s, Real64 earthLiteral) { return s.dataEnvrn->isEarth ? earthLiteral : s.dataEnvrn->gravity; }`.
  Apply it at each of the 48 src sites (GRV-01..12) with the site's original literal (9.8, 9.80, 9.81, 9.806,
  9.807, 9.80665, or the latitude formula result), so Earth stays bit-identical.
- WCE: replace `static const double GRAVITYCONSTANT` with a settable accessor (default 9.807). This is a small
  third-party patch; record it in `third_party/Windows-CalcEngine` notes.
- ssc PVWatts: leave; the PV audit replaces the cell-temperature model off-Earth.

### 3.4 Disable / error off-Earth (input stage, P0)

At the end of `HeatBalanceAirManager::GetSimpleAirModelInputs` and in the respective `Get*Input` routines, if
`!outdoorAirUsable`: severe error for `ZoneInfiltration:*` (3), `ZoneVentilation:*` (2), `ZoneAirBalance:OutdoorAir`,
`ZoneEarthtube`, `ZoneCoolTower:Shower`, `ZoneThermalChimney`, `AvailabilityManager:HybridVentilation`,
`SurfaceProperty:ExteriorNaturalVentedCavity`, `WindowProperty:AirflowControl` (outdoor source/exhaust), AFN external
nodes / wind-pressure objects, and any OA intake with OA flow > 0 (ideal loads OA, Controller:OutdoorAir, DOAS,
OutdoorAirUnit, ERV). The message should say: "outdoor air is not available on <body>; use ZoneCabinLeakage".
`ZoneMixing`, `ZoneCrossMixing` and `ZoneRefrigerationDoorMixing` stay allowed (inside the cabin).

### 3.5 What to leave alone

Water-only psychrometrics and their caches; `DataConvergParams::HVACCpApprox`; AFN crack reference conditions
(101325 Pa, 20 °C, test standard); NFRC nominal window rating (WindowManager:6479, WindowEquivalentLayer:8088);
coil Earth rating points (only wrap them); EMS `@TodayOutBaroPress` (it is weather data, outdoor meaning is correct);
`OutBaroPressAt` (WindTurbine only).

## 4. Open questions / risks

1. **One cabin pressure or one per zone?** Habitats with airlocks/depressurizable modules need per-zone pressure.
   But ~184 HVAC uses have no zone index. Proposal: one global `CabinBaroPress` first, `Zone::baroPress` later for
   ZTPC/convection only. Decide before pass A so the getter signature (`zoneBaroPress(zoneNum = 0)`) is fixed.
2. **Namespace-global gas block** breaks the "several `EnergyPlusData` instances in one process" API use case if
   they simulate different planets. Accept and document it, or (expensive) thread `state` through ~1 000 calls.
3. **Bit-identity**: the getter and literal-branch patterns guarantee it in principle. An extra `if` in hot inline
   functions can still change inlining and FMA fusion in rare compilers; confirm with binary-identical ESO on the
   full Earth regression set, not only a few files.
4. The heuristic OutBaroPress split (±10) must be confirmed line by line during the substitution. Several HVAC
   components (evaporative-cooler secondary air, heat-recovery secondary side, HPWH inlet, `WaterThermalTanks.cc:12679`)
   are outdoor or indoor depending on the node configuration. Off-Earth they are indoor, because outdoor air is disabled.
5. Moon "outdoor dry-bulb": what value should the generator write into `OutDryBulbTemp` in vacuum? It still feeds
   many modules (ground/regolith, condensers, reports). Suggestion: the local regolith surface temperature, with
   exterior convection forced to 0. This needs agreement with the environment and convection audits.
6. The cabin cp must be the mass-weighted ideal-gas value (~1004 J/kg-K at 26.5 % O2); a mole-weighted value
   (998.4) would be 0.6 % low in air capacitance.
7. Cabin leakage: a choked leak (rate set by orifice area and cabin P) vs a user-given %/day. A mass rate in kg/day is simplest.
   Note that "per day" must be Earth seconds (86 400) and not the planetary hour × 24.
8. Water vapour at reduced total pressure: the W-based model is valid at 70 kPa. In low-pressure pure-O2 cabins
   (34 kPa) the 1e-5 humidity floors and the `max(PB−PDEW,1000)` clamp still work, but the RH validity warnings
   (`EP_psych_errors`) may fire more often.
