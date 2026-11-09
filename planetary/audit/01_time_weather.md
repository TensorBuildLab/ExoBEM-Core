# 01 — Time base, calendar, simulation loop, schedules, weather input, sizing

Scope: Data/DataGlobals, DataGlobalConstants, DataHVACGlobals, SimulationManager, HeatBalanceManager (warmup),
WeatherManager, DataEnvironment, SolarShading (sun position only), ScheduleManager, SizingManager,
OutputProcessor, GroundTemperatureModeling. All line numbers are from the `planetary` branch (v26.2.0).

## 1. Summary

- The "planetary hour" (1 h = solar day / 24) is **workable** and is the right choice. The loop, all arrays of 24 hours ×
  N timesteps, the 1440-minute schedule grid, the 366-day calendar, the warmup logic and OutputProcessor time weighting are
  pure index or fraction bookkeeping. They need no change. The hour-angle formula `15° × (12 − (t + EoT))` is correct for
  any body once `t` and `EoT` are in planetary hours.
- `Constant::rSecsInHour` / `iSecsInHour` / `rSecsInDay` are `constexpr` (DataGlobalConstants.hh:595-605). They **must
  not be changed**. Of the 118 uses of `rSecsInHour`, 65 convert simulation time to seconds (these must follow the
  planetary hour) and 52 are unit conversions with a real 3600 s hour (ACH, kWh, lb/h, cycles/h, user inputs in "hours").
  These 52 must stay 3600. 59 code lines use the literal `3600`: 18 are simulation time, 41 are units.
- Good news: about 1,110 rate × Δt uses go through `TimeStepZoneSec` (330) and `TimeStepSysSec` (780). They are set in only
  4 lines (SimulationManager.cc:954, 1387; HVACManager.cc:211, 321).
- Hidden trap (P0): the CTF solver works in English units with time in **Earth hours** (Construction.cc:380-382, CFK is
  Btu/h-ft-F). `CTFTimeStep` is in the same units as `TimeStepZone`. With planetary hours, every CTF would be wrong by
  the factor SecInHour/3600 (Mars 1.027, Moon 29.53).
- Weather: there is one clean dispatch point, `Weather::ReadWeatherForDay` (WeatherManager.cc:2268). It fills
  `wvarsHrTsTomorrow(ts,hr)` and `TomorrowVariables` (date, EoT, declination). `SetUpDesignDay` is the matching point for
  design days. A planetary EPW file is **not** viable as-is. EPW sentinels and range checks would silently replace Moon-day
  120 °C (≥ 99.9 counts as "missing") and Mars 600 Pa (≤ 31 000 Pa is replaced by StdBaroPress).
- Sun position exists in 3 copies: WeatherManager `CalculateDailySolarCoeffs`, SolarShading `SUN3`, and an FAO-56 copy
  in PlantPipingSystemsManager. Only the daily declination / EoT / distance must be replaced. `DetermineSunUpDown`,
  `SUN4` and `CalculateSunDirectionCosines` can stay.
- Main limits: the Moon zone timestep cannot go below 1 lunar minute = **1 771.8 s**, because `TimeStepsInHour` ≤ 60 and
  divides 60. The HVAC sub-step floor is the same value, so on the Moon at 60 steps/h there is no adaptive sub-stepping.
  On the Moon, Earth-clock crew cycles (24 h) are shorter than one lunar hour and cannot be written as Day schedules.
- Overall difficulty: **moderate**. About 90 mechanical edits, 1 subtle numerical fix (CTF), and 1 new module (planetary
  environment generator, around 4 hook points). Earth stays bit-for-bit because SecInHour = 3600.0 exactly and the
  factor becomes 1.0 exactly.

### Time-step bounds under the planetary hour

Solar days: Moon (mean synodic) 29.530588853 d = 2 551 442.9 s → **hour = 106 310.1 s** (the brief's 106 300 s is a
rounding), minute = 1 771.84 s. Mars sol 88 775.244 s → **hour = 3 698.97 s**, minute = 61.65 s.

| Timesteps/h (allowed: 1,2,3,4,5,6,10,12,15,20,30,60) | Earth | Mars | Moon |
|---|---|---|---|
| 1  | 3 600 s | 3 699 s | 106 310 s (29.5 h) |
| 4  | 900 s | 924.7 s | 26 578 s (7.38 h) → over CTF limit of 7 Earth h (Construction.cc:134) once T10 is fixed |
| 5  | 720 s | 739.8 s | 21 262 s (5.9 h): lowest value that passes the CTF limit |
| 6  | 600 s | 616.5 s | 17 718 s |
| 20 (forced if CondFD, SimulationManager.cc:920-926) | 180 s | 184.9 s | 5 316 s; CondFD inner Δt stays 266 s > 200 s target (HeatBalFiniteDiffManager.cc:618-623) |
| 60 (max) | 60 s | 61.65 s | **1 771.8 s** (matches the 1 800 s of the Python reference `moon_site(dt=1800)`) |
| Min HVAC sub-step (1 planetary min, DataConvergParams.hh:175) | 60 s | 61.65 s | 1 771.8 s = zone step at 60/h → no sub-steps |
| Sizing averaging window default = 1 h (SizingManager.cc:2632-2649) | 3 600 s | 3 699 s | 106 310 s |

Nothing rejects a zone timestep longer than 3 600 s as such. These are the things that misbehave: the CTF 7-Earth-hour
limit (Moon < 5 steps/h, once T10 is fixed), the CondFD sub-step target, the HVAC sub-step floor, Kiva "Hourly" fixed
3 600 s, IceThermalStorage's 1 h normalisation, EMPD with a 1-day penetration depth, and every "per timestep" threshold
tuned for ≤ 1 Earth hour (`MaxZoneTempDiff` 0.3 K per zone step, `IsRainThreshold`).

## 2. Findings

Priority key: P0 first single-zone Moon/Mars ideal-loads run, P1 windows/HVAC/plant/PV/realistic outputs, P2 rare
module (flag "unsupported off-Earth").

Class key used below: **S** = simulation-time seconds (must follow the planetary hour); **U** = unit conversion with a
real 3 600 s hour (must stay 3 600); **I** = index / label (leave alone).

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| T01 | DataGlobalConstants.hh:593-605 | `Constant::{i,r}SecsInHour`, `rSecsInDay`, `rHoursInDay`, `rMinutesInHour` (constexpr) | 1 h = 3 600 s, 1 d = 86 400 s | Cannot be made run-time. Replacing them globally would also break 52 + 41 unit uses (T07) | Keep them as the Earth-hour **unit**. Add run-time `state.dataGlobal->SecInHour`, `SecInMinute`, `SecInDay`, `HourToEarthHr` (= SecInHour/3600). Set them once (see §3) | P0 |
| T02 | SimulationManager.cc:952-954, 1384-1387 | `TimeStepZone`, `MinutesInTimeStep`, `TimeStepZoneSec` | `TimeStepZoneSec = TimeStepZone*3600` | Every zone rate×Δt (330 uses / 25 files: InternalHeatGains 144, RefrigeratedCase 43, HeatBalanceSurfaceManager 35, SolarShading 31, OutputProcessor 17, …) uses Earth seconds | `TimeStepZoneSec = TimeStepZone * SecInHour`. `TimeStepZone` (fraction of an hour) and `MinutesInTimeStep` (int) stay as they are (S→fixed at source) | P0 |
| T03 | HVACManager.cc:211, 321 | `TimeStepSysSec` | `TimeStepSys*3600` | 780 uses / 104 files (PackagedThermalStorageCoil 58, ElectricPowerServiceManager 53, HVACManager 52, VariableSpeedCoils 33, SystemReports 30, …) | Use `* SecInHour`. Both lines are the only setters | P0 |
| T04 | ZoneTempPredictorCorrector.cc:4931; HeatBalFiniteDiffManager.cc:619, 1454; RoomAirModelAirflowNetwork.cc:871-878 (3); AirflowNetwork/src/Solver.cpp:7697, 8792, 12128; HVACControllers.cc:2510, 2525; SystemAvailabilityManager.cc:578; Coils/CoilCoolingDX.cc:699; CoilCoolingDXCurveFitPerformance.cc:221; CoilCoolingDXAshrae205Performance.cc:222 (`iSecsInHour`); OutputReportTabular.cc:3482, 6308, 6335, 6513, 6610, 6635 | inline `TimeStep{Zone,Sys} * Constant::rSecsInHour` (class S) | 3 600 s | Wrong Δt by SecInHour/3600: CondFD inner Δt, AFN duct radiation J/m², controller time, night-cycle run time (user seconds → steps), DX report energy, tabular "per second" values | Replace with `TimeStepZoneSec`/`TimeStepSysSec` or `state.dataGlobal->SecInHour`. 22 lines. ZTPC:4931 is the HybridModel inverse (P2). HBFD:619 is P0 only when CondFD is used | P0 (HBFD), P1 rest |
| T05 | RefrigeratedCase.cc (19 lines: 10901, 11207, 11238, 11797, 12218, 12629, 13029, 13212, 13584, 13591, 13596, 13932, 15028, 15055, 15097, 15223, 15395, 16111, 16141); PondGroundHeatExchanger.cc:496-506 (4); FuelCellElectricGenerator.cc:321, 325, 3545, 3554; MicroCHPElectricGenerator.cc:1430, 1435; GeneratorDynamicsManager.cc:125, 134; PlantPipingSystemsManager.cc:214, 218, 4433; GroundHeatExchangers/Vertical.cc:505, 1013, 1497; Slinky.cc:676; IceThermalStorage.cc:1491, 1543; EconomicTariff.cc:2560 | same pattern, class S, rare modules | 3 600 s | Same scaling error | Same mechanical replacement (43 lines). Vertical.cc:505/1013 also hard-code an 8 760-h / 365-d Earth year (T25) | P2 |
| T06 | MoistureBalanceEMPDManager.cc:607, 613, 629, 678; HeatBalanceHAMTManager.cc:676; PCMThermalStorage.cc:238 | literal `TimeStepZone*3600.0` / `TimeStepSys*3600.0` (class S) | 3 600 s | EMPD/HAMT moisture and PCM tank use Earth Δt | → `TimeStepZoneSec` / `TimeStepSysSec` | P1 (EMPD/HAMT inside cabin), P2 PCM |
| T07 | ConvectionCoefficients.cc:2055, 2276, 4758, 6427, 6480; HeatBalanceAirManager.cc:864, 1490, 2559, 3062, 3923-4161 (9); DataSizing.cc:999, 1158, 1165, 1177; HVACManager.cc:2307, 2503; ZoneTempPredictorCorrector.cc:4877-4878, 5124-5125; ZoneContaminantPredictorCorrector.cc:2084-2085; SurfaceGeometry.cc:14999; TranspiredCollector.cc:1454; HeatBalanceSurfaceManager.cc:10129; AirflowNetwork Solver.cpp:7352, 7361, 7420; WaterManager.cc:967; WaterThermalTanks.cc (18); PackagedThermalStorageCoil.cc:2352-2368 (4); IceThermalStorage.cc:110, 914, 1497, 1505, 1507; RefrigeratedCase.cc:1159; DXCoils.cc:12629-12650; CoilCoolingDXCurveFitSpeed.cc:829-850; VariableSpeedCoils.cc:7696, 7705; WaterToAirHeatPump(Simple).cc (4); OutputReportTabular.cc:7361-7427, 7994, 10032; OutputReportTabularAnnual.cc:1130, 1133; EconomicTariff.cc:425-446; DataConversions.hh:68; PlantPipingSystemsManager.cc:4288; FiniteDifferenceGroundTemperatureModel.cc:509; EcoRoofManager.cc:1042; PCMThermalStorage.cc:191 | `rSecsInHour` or `3600` as a **unit** (class U): ACH = h⁻¹, kWh, lb/h, Btu/h, cycles per hour, L/day, m/h rain, user "hours" (recovery time, draw time, storage hours) | Real 3 600 s | Correct as-is. A blanket search-and-replace would break them | **Leave alone.** Document that user input "per hour" means Earth hour. Optional: alias `Constant::rSecsPerHourUnit` to make the intent explicit, plus a CI grep rule that bans `TimeStep(Zone\|Sys)\s*\*\s*Constant::rSecsInHour` | P0 (as "do not touch") |
| T08 | OutputProcessor.cc:189; EcoRoofManager.cc:854, 862, 863, 866, 957, 966; Photovoltaics.cc:1316; SurfaceGeometry.cc:10989; ExternalInterface.cc:2138 | `MinutesInTimeStep * 60.0` used as seconds (class S) | 60 s/min | PV cell-temperature Δt and Kiva Δt are wrong. OutputProcessor's `op->TimeStepZoneSec` is set but never read | → `TimeStepZoneSec`. ZoneEquipmentManager.cc:2414 (`sizingPeakTimeStamp`) and General.cc:1112 `ParseTime` are labels (class I): leave them | P1 (PV), P2 rest |
| T09 | HeatBalanceKivaManager.cc:195, 451; SurfaceGeometry.cc:10986; GroundHeatExchangers/Slinky.cc:272-273 | Kiva "Hourly" step 3 600 s, accelerated step `24*60*60`, Slinky `ts = 3600`, year = **356**×24×3600 (an existing Earth typo) | Earth hour/day | Kiva step does not match the planetary zone step | Use SecInHour / SecInDay. Report the Slinky 356 typo upstream; do not fix it here (it would change Earth results) | P2 |
| T10 | Construction.cc:134, 194, 380-382, 501, 586-612, 907, 932, 945, 1205, 1220, 1562-1578 | CTF solver in English units (`CFK` = Btu/**h**-ft-F, DataConversions.hh:65-69). `CTFTimeStep` is in units of `TimeStepZone`. `MaxAllowedTimeStep = 7.0` | Time unit = Earth hour | With planetary hours, the state-space matrix exponential uses Δt in planetary hours as if they were Earth hours: Mars error 2.7 %, Moon ×29.5 in Δt, so CTFs are badly wrong. HeatBalanceSurfaceManager.cc:5715, 5796 divide `SumTime` (planetary h) by `CTFTimeStep`, so the stored value must stay in planetary hours | Keep `CTFTimeStep` in planetary hours. Inside `calculateTransferFunction` use `ctfDtEarthHr = CTFTimeStep * HourToEarthHr` at 501, 945, 1205, 1220, 1562-1578, and use `dtn / HourToEarthHr` at 586-591. Factor is 1.0 on Earth (exact). Coordinate with the constructions audit | **P0** |
| T11 | SimulationManager.cc:511-628 (also SizingManager.cc:311, 501; HVACSizingSimulationManager) | Environment → day → `HourOfDay` 1..24 → `TimeStep` 1..`TimeStepsInHour` loops, `EndHourFlag` / `EndDayFlag` | 24 slots per day | Correct for planetary hours | Leave alone (class I) | – |
| T12 | SimulationManager.cc:895-946 | `Timestep` input: 1..60, must divide 60 (`Div60` at :720). CondFD forces ≥ 20. Warning below 4 | 60 min/h | Moon minimum Δt = 1 771.8 s. A finer Moon step would need > 60 steps/h, which breaks the integer `MinutesInTimeStep` (division by zero in ScheduleManager.cc:221) and the 1440-minute grids | Keep the limits. In planetary mode, warn on the Moon if steps/h < 5 (CTF) and suggest 60. Echo the step in seconds to the .eio (SimulationManager.cc:1450) | P0 (checks), P2 (finer grid) |
| T13 | SimulationManager.cc:961-1017, 1405-1415; DataConvergParams.hh:175; HVACManager.cc:309-321 | `ConvergenceLimits` minimum system timestep in **integer minutes** (0-60). `LimitNumSysSteps = TimeStepZone/MinTimeStepSys` | 1 min = 60 s | On the Moon at 60 steps/h, the sub-step floor equals the zone step, so the adaptive HVAC step never triggers even when `MaxZoneTempDiff` is exceeded | In planetary mode, read a minimum system time step in **seconds**: `MinTimeStepSys = sec / SecInHour`. Nothing is sized by the number of sub-steps (checked HVACManager). OutputProcessor's `CurMinute` becomes fractional, which is harmless | P1 |
| T14 | SimulationManager.cc:495-503, 554-559 | `isFinalYear` (≤ 365/366 days). Tabular reset "last year" when `DayOfSim > 365` and 364 days remain | Earth year = 365 d | For a Mars run of 669 sols, the annual tabular reports cover only the last 365 sols. For the Moon (12.4 lunar days per year) it is irrelevant | Use `PlanetYearDays` (round(year/solar day)) in planetary mode, or disable the reset | P1 |
| T15 | HeatBalanceManager.cc:200-245, 3310-3420; DataHeatBalance.hh:96-97 | Warmup repeats day 1 until zone max/min T and loads converge. `MinLoad = 100 W`. Default max 25 days | Days are short | Body-agnostic. One Moon warmup day = 29.5 Earth days (25 days ≈ 2 Earth years, cheap at 1 440 steps/day). Deep regolith coupling may need more days | No code change. In planetary mode, maybe default `MaxNumberOfWarmupDays` higher and document | P2 |
| T16 | WeatherManager.cc:2268-2285 | `ReadWeatherForDay` → `ReadEPlusWeatherForDay` (2287-3172) | EPW, hourly | – | **Main hook**: `if (state.dataPlanet->active) { Planetary::ReadDay(state, DayToRead, Environ); return; }`. It must fill `TomorrowVariables` (Year/Month/DayOfMonth/DayOfYear/DayOfYear_Schedule/DayOfWeek/HolidayIndex, DST = 0, EoT, sin/cos declination) and all `wvarsHrTsTomorrow(ts,hr)` fields of `WeatherVars` (WeatherManager.hh:713-732) | P0 |
| T17 | WeatherManager.cc:2477-2519, 2872-2918, 8304-8315 | EPW sentinels and range checks: DryBulb ≥ 99.9 = missing (replaced by 6 °C). Out of range < −90 or > 70 °C. Pressure ≤ 31 000 or > 120 000 Pa → **replaced** by StdBaroPress. Wind > 40 m/s | Earth climate | Moon day (≈ 120 °C) becomes 6 °C. Moon night (−170 °C) gets flagged. Mars 600 Pa becomes about 101 kPa without any error | Do not use EPW for planets. Use the generator (T16), or a new planetary CSV reader behind the same hook. Never route planetary data through `InterpretWeatherDataLine` | P0 |
| T18 | WeatherManager.cc:2101-2135, 2223-2232 | `SetCurrentWeather`: psychrometrics on outdoor air at `OutBaroPress` (`PsyWFnTdbRhPb`, `PsyTwbFnTdbWPb`, `PsyTdpFnWPb`, `PsyRhoAirFnPbTdbW`, `PsyHFnTdbW`) | Moist air, P ≈ 101 kPa | P = 0 (Moon) gives 0/0 → NaN humidity ratio. Mars: CO₂ treated as moist air | Planetary branch after copying `today`: OutHumRat = 0, OutWetBulb = OutDewPoint = OutDryBulb (or −100 °C), OutAirDensity / OutEnthalpy from the body gas model, IsRain = IsSnow = false. Keep EMS overrides | P0 |
| T19 | WeatherManager.cc:2087-2097 | Ground temps `getGroundTempAtTimeInMonths(..., Month)`, `GndReflectance(Month)`, `CalcWaterMainsTemp` | Monthly Earth values | A 13-lunar-day run falls entirely in calendar "January", so ground BC temperature is constant and arbitrary | In planetary mode, set `GroundTemp[*]` from the regolith model (per timestep) and `GndReflectance` from body albedo. Water mains from a schedule (T30) | P0 (ground-contact floors), else P1 |
| T20 | WeatherManager.cc:4129-4235 (called at 2847 and 3597) | `CalculateDailySolarCoeffs`: Earth Fourier series in `X = 2π·DayOfYear/366`. Gives sin δ, EoT, `AnnVarSolConstant` (1 ± 0.033), ASHRAE A/B/C | Earth orbit | Wrong declination / EoT / distance | Not called on the planetary path. The generator supplies EoT [planetary h], sin/cos δ and r [AU] per day from the ephemeris (Mars24 Allison-McEwen; Moon mean elements + Cassini, as in `exobem/ephemeris`). Keep the Earth code unchanged | P0 |
| T21 | SolarShading.cc:9449-9504 (`SUN3`), called at 9060 and 9071 inside `PerformSolarCalculations` (8970-9095) | Second copy of the Earth declination / EoT series. Shadowing period average over `ShadowingCalcFrequency` (default 20 days, :463-470) | Earth orbit | Shading and sunlit fractions would use Earth sun paths | Add a planetary branch: `Planetary::dailySolar(state, dayOffset, sinDec, eot)` with dayOffset = Count − 1 from the current sim day. A 20-day period is fine (Moon δ ≤ 1.54°; Mars changes < 0.4°/sol) | P0 |
| T22 | WeatherManager.cc:4237-4274, 4276-4335; SolarShading.cc:5050-5085, 9506-9534 | Hour angle `15·(12 − (t + EoT)) + (TZM − Lon)`. `TS1TimeOffset = −0.5` (DataEnvironment.hh). Sun evaluated at the end of the timestep | 15° per hour | **Correct** with planetary hours, as long as EoT is in planetary hours and TZM is defined | Leave the code alone. In planetary mode set `TimeZoneMeridian = Longitude` (local mean solar time; Mars LMST) and EoT_h = eot_deg/15 (Mars24 sign: LTST = LMST + EOT/15; both use east-positive longitude). Skip `CheckLocationValidity` / `GetSTM` time-zone warnings (4498-4583, 7433) | P0 |
| T23 | WeatherManager.cc:8318-8376, 3046-3124 | Linear hourly → timestep interpolation. Solar uses mid-hour weights (`SolarInterpolation`) | EPW hourly integrals | On the Moon one "hour" is 29.5 Earth h. Interpolated irradiance is inconsistent with `SunIsUp` near the terminator | The generator writes `(ts,hr)` values directly at the same instant as `DetermineSunUpDown` (t = hr−1 + ts/N, or hr − 0.5 when N = 1). No interpolation | P0 |
| T24 | WeatherManager.cc:3485-4025, 5931-6650 | `SetUpDesignDay` / `GetDesignDayData`: GlobalSolarConstant 1367, Zhang-Huang 1355, ASHRAE clear-sky / τ models, Kasten-Young air mass (4026), `DefaultTempRangeMult[24]` Earth diurnal shape (5984), Zhang-Huang "3 h ago" `mod(hour+20,24)`, pressure must be within 10 % of StdBaroPress, input ranges −90..70 °C (6149, 6233, 6254, 6271) | Earth atmosphere / climate | Design days are meaningless off-Earth. Sizing needs them | Planetary branch at the top of `SetUpDesignDay`: run the generator for a design epoch (date, Ls, or "hot/cold extreme") and fill `DesignDay(EnvrnNum)` + `wvarsHrTsTomorrow`. Keep `KindOfSim::DesignDay` so all sizing machinery works. New input: `SizingPeriod:PlanetaryDesignDay` (epoch, dust τ). Reject classic DesignDay in planetary mode | P0 (if sizing used; ideal loads can skip) |
| T25 | GroundTemperatureModeling/KusudaAchenbachGroundTemperatureModel.cc:124, 166, 196, 217, 243-244; XingGroundTemperatureModel.cc:103, 138, 174, 203-206; FiniteDifferenceGroundTemperatureModel.cc:187, 223, 235, 319, 438, 447, 776, 801, 915-1026; SiteBuilding/Deep/FCFactor/ShallowGroundTemperatures.cc:173/166/177/164 | Annual harmonic with `secsInYear = 86400·NumDaysInYear(365)`. Xing period 365 d. FD model: one-year daily-step pre-simulation that needs the EPW (:187). `NumDaysInYear/12` integer division | Earth year, Earth seasons, daily step | Annual harmonic is irrelevant on the Moon (the diurnal 29.5-d wave dominates). Mars year is 668.6 sols. FD fails without EPW | Mark "unsupported off-Earth" in planetary mode. The regolith model (Site:PlanetaryBody) supplies ground temps (T19). If kept, parameterise `secsInYear = PlanetYearSec` and the day period = SecInDay (Earth unchanged) | P1 (GHX/slabs), P2 |
| T26 | WeatherManager.hh:783 (`NumDaysInYear = 365`) and its 40 uses (ground models above; ZoneTempPredictorCorrector.cc:1660-2370 adaptive comfort arrays; WeatherManager.cc:2654) | Earth year length | 365 | Labels mixed with physics | Leave as calendar length. Physics users take `PlanetYearDays` (T25) | P2 |
| T27 | ScheduleManager.cc:181-236, 636-638, 1042-1074, 1397-1727, 1994-2000, 2038-2052, 2179-2303, 2435-2502, 2811-2823, 2884-2914, 2961, 3208-3214, 3449, 3735-3985, 4163-4344 | Day schedule = 24 × N values from a 1440-minute grid. Minutes per item must divide 60. Year = 366 day slots. Schedule:File 8 760/8 784 rows. DST adds 1 h at lookup (2884-2895). Annual hours use 365/366 × 24 | 24 h day, 365/366-d year | All index-based, so it works with planetary hours and minutes as labels. Limits: (a) a Mars year (669 sols) is longer than 366 → annual schedules wrap on the calendar; (b) Moon crew 24-Earth-h cycles are shorter than 1 lunar hour → only Schedule:File at timestep resolution (≈ 29.5 Earth min) can express them; (c) "Until: 07:00" means planetary 07:00 | No change for P0 (constant or planetary-day schedules). P1: new option "Earth-clock" schedule (evaluate a Day schedule at mission elapsed seconds mod 86 400) for People / Lights / Equipment on the Moon | P1 |
| T28 | WeatherManager.cc:1242-1717, 5686-5930; WeatherManager.hh:818-820 | Day of week, holidays (`SpecialDayTypes(366)`), DST ranges (`DSTIndex(366)`) | Gregorian calendar | Labels; harmless. DST would shift planetary schedules by one planetary hour | Planetary mode: force DST off (error if `RunPeriodControl:DaylightSavingTime` is present), keep holidays and the 7-day week as labels | P1 |
| T29 | WeatherManager.cc:819-834, 1955-1960, 4337-4416, 4601-4608, 5012-5398, 8378-8510; SimulationManager.cc:1658-1713 | RunPeriod requires an EPW (fatal "Weather Simulation requested, but no weather file attached"). EPW header processing, end-of-environment `inputWeatherFile.rewind()`, leap-year logic (8447-8485), `TotalDays` from Julian dates | Weather file + Gregorian dates | A planetary run has no EPW. The ephemeris needs an absolute epoch, which RunPeriod does not give | Treat `dataPlanet->active` as "weather available" in these checks. Skip rewind / `SkipEPlusWFHeader` / `ReportMissing_RangeData` / `ProcessEPWHeader`. Force `LeapYearAdd = 0`. RunPeriod gives the calendar labels and length (days = sols / lunar days). Site:PlanetaryBody gives the epoch (UTC JD or MSD) of day 1, 00:00 local mean solar time | P0 |
| T30 | WeatherManager.cc:7128-7224 | Water mains correlation `0.986·(DayOfYear − 15 − lag)` | Earth year | Meaningless | Planetary mode: require `Site:WaterMainsTemperature` = Schedule/constant | P2 |
| T31 | WeatherManager.cc:1772, 2203-2215 | `IsRainThreshold = 0.8/TimeStepsInHour` mm; rain/snow flags | Earth | Not applicable | IsRain/IsSnow false in planetary mode (T18) | P2 |
| T32 | OutputProcessor.cc:3355-3420, 3621-3809, 2768 | Reporting on `EndHourFlag` / `EndDayFlag` / `EndMonthFlag` / `EndYearFlag`. Averages weighted by `rxTime` (minutes/minutes). Sums are module energies (J). Time stamps Month/Day/Hour/Minute | – | No seconds inside OutputProcessor: correct as-is. "Hourly" = planetary hour, "Daily" = sol / lunar day, "Monthly" = calendar label (a Moon year sits in January) | Leave alone. P1: add output variables "Site Planetary Elapsed Time [s]", "Site Planetary Local True Solar Time [h]", "Site Planetary Solar Longitude [deg]" (Mars Ls), "Site Sun Distance [AU]" | P1 |
| T33 | OutputReportTabular.cc:7858, 9973 (`< 8759` h annual check); unmet-hours and "time occupied" accumulators (`+= TimeStepZone`); 6308, 6335 (`24*7` lights full-load hours) | "hours" = Earth hours | Reported hours are planetary hours (Moon ×29.5) | Label the columns, or scale by `HourToEarthHr` in planetary mode | P1 |
| T34 | SizingManager.cc:2101-2112, 2632-2655, 4199, 4524; ZoneEquipmentManager.cc:188, 846-849, 1302-1401, 2407-2417 | Sizing arrays = `TimeStepsInHour*24`. VRP diversity loop over 366 days × 24 h. Averaging window default = 1 h of timesteps. Peak time stamp from minutes | 24 h design day | Structural parts are fine. On the Moon the averaging window becomes 29.5 Earth h | Leave the arrays. Planetary default `NumTimeStepsInAvg = 1`. Design periods from T24. `SizingPeriod:WeatherFileDays/ConditionType` unsupported (need EPW) | P1 |
| T35 | ExternalInterface.cc:1835, 1972, 2138, 2146, 2207, 2220; ExternalInterface.hh:341, 406 | FMU/BCVTB time = `24*3600` per day, `SimTimeSteps*Minutes*60` | Earth s | Co-simulation clock is wrong | Unsupported off-Earth (or use SecInDay) | P2 |
| T36 | api/datatransfer.cc (29 uses of `iHoursInDay`); RuntimeLanguageProcessor.cc (EMS `CurrentTime`, `SystemTimeStep` in h) | Plugin / EMS time in hours | User code multiplies by 3 600 | Wrong in user scripts | Add API getter `secondsPerHour()` and EMS built-in `SecondsPerHour`. Document | P2 |
| T37 | EarthTube.cc:661, 1010-1012; PlantPipingSystemsManager.cc:4284-4480 (own FAO-56 sun: 1367 W/m², δ = 0.409 sin(2π·DOY/365 − 1.39)); PipeHeatTransfer.cc:641, 1922; HeatBalanceKivaManager.cc:187-212 (365-day accelerated warm-up); ThermalComfort.cc:2780-3004 (365/366, /24); SolarShading.cc:2727 (1353 W/m² in the anisotropic sky Δ) | Earth year / sun / solar constant | Wrong physics | Flag unsupported off-Earth, except SolarShading:2727 (P1, needs body S₀/r²; see solar audit) | P2 (P1 for :2727) |
| T38 | MoistureBalanceEMPDManager.cc:227, 232 | Penetration depth from a 1-day and 21-day humidity period `24*3600` | Earth day | Cabin humidity cycle follows the crew (Earth) day or the sol | Use SecInDay on Mars. On the Moon keep 86 400 (crew cycle). Make it an option | P2 |
| T39 | WeatherManager.cc:4476 (`StdBaroPress` from the Earth standard atmosphere); 1751 (missing-value pressure); 3555-3566 (design-day pressure 10 % check) | 101 325·(1 − 2.25577e-5 z)^5.2559 | Std pressure / ρ used for flow conversions | Planetary: StdBaroPress = cabin reference pressure (see cabin audit); outdoor pressure from the generator | P0 (cross-ref) |
| T40 | SystemAvailabilityManager.cc (18 × `24.0`, e.g. 2420, 2463), FuelCell / GeneratorDynamics (31 × `rHoursInDay` fractional day) | Times in hours of a 24-h day | – | Consistent with planetary hours (class I). User inputs of optimum start "hours" become planetary hours | Leave; document | P2 |

### Count summary (for the record)

- `Constant::rSecsInHour`: 118 uses in 31 files (+ 2 definitions). **S = 65** (T04 22, T05 43), **U = 52** (T07), 1 comment
  (IceThermalStorage.cc:1541). Per file: RefrigeratedCase 20 (19 S / 1 U), WaterThermalTanks 18 U, HeatBalanceAirManager
  9 U, IceThermalStorage 7 (2 S / 4 U / 1 comment), OutputReportTabular 6 S, ZoneTempPredictorCorrector 5 (1 S / 4 U),
  PondGHX 4 S, PackagedThermalStorageCoil 4 U, HVACManager 4 (2 S / 2 U), FuelCell 4 S, RoomAirModelAFN 3 S,
  PlantPipingSystems 3 S, GHX Vertical 3 S, ConvectionCoefficients 3 U, AFN Solver 3 S, ZoneContaminant 2 U,
  SimulationManager 2 S, MicroCHP 2 S, HVACControllers 2 S, HeatBalFiniteDiff 2 S, GeneratorDynamics 2 S, and 1 each:
  WaterManager U, TranspiredCollector U, SystemAvailabilityManager S, SurfaceGeometry U, HeatBalanceSurfaceManager U,
  Slinky S, EconomicTariff S, DataSizing U, CoilCoolingDXCurveFitPerformance S, CoilCoolingDX S.
- `Constant::iSecsInHour`: 1 use (CoilCoolingDXAshrae205Performance.cc:222, S).
- `Constant::rSecsInDay`: 20 uses. Ground models 15 (Earth-year physics, T25), PipeHeatTransfer 2 (641 U, 1922 S),
  PlantPipingSystems 2 S (4427, 4430), ZoneDehumidifier 1 U (738, L/day).
- `Constant::iHoursInDay`: 170 uses, all I (array sizes and loops; WeatherManager 32, ScheduleManager 31,
  api/datatransfer 29, DaylightingManager 16, SolarShading 9, SizingManager 9, HeatBalanceManager 6, …).
  `rHoursInDay`: 42 uses, all I (GeneratorDynamics 26, FuelCell 5, OutputReportTabular 5, …). Exception:
  EarthTube.cc:661 is U (diffusivity per day → per hour).
- `[ir]MinutesInHour`: 42 uses, `iMinutesInDay`: 9. All I (minute grid).
- Literal `3600` in code (comments excluded): 59 lines. **S = 18** (EMPD 6, ExternalInterface 7, HAMT 1, PCM 1, Kiva 2,
  Slinky 1). **U = 41** (OutputReportTabular 6, EconomicTariff 5, DXCoils 4, CoilCoolingDXCurveFitSpeed 4, DataSizing 3,
  AFN 3, VariableSpeedCoils 2, WaterToAirHeatPump 2, WaterToAirHeatPumpSimple 2, OutputReportTabularAnnual 2,
  ConvectionCoefficients 2, and 1 each in PCM, PlantPipingSystems, IceThermalStorage, FD ground, EcoRoof, DataConversions).
- `24*60*60` / `60*60`: HeatBalanceKivaManager.cc:195 (S), Slinky.cc:273 (S, Earth year), General.cc:1112 (I, ParseTime).
- Literal `86400`: 0. `8760`: 9 lines. GHX Vertical.cc:454, 463, 464 (I, hourly load bins); 503, 506 (S, Earth year);
  OutputReportTabular.cc:7858, 9973 (I); ScheduleManager.cc:1994, 1996, 2000 (I, Schedule:File rows). `8784`: ScheduleManager.cc:2235.
- Literal `365` / `366` as a day count: ScheduleManager 28, WeatherManager.cc 19, WeatherManager.hh 7, HeatBalanceKiva 5,
  ThermalComfort 4, General 4 (OrdinalDay tables), SimulationManager 3, GHX Vertical 3, EarthTube 3,
  PlantPipingSystems 2, SizingManager 1, HeatBalanceManager 1. False positives (AHRI Std 365, fluid tables, Shomate
  coefficient): StandardRatings 7, DXCoils 4, CoilCoolingDX* 3, FluidProperties 3, GeneratorFuelSupply 1,
  WindTurbine 3 (message text).
- Literal `24` in hour tests (`<= 24`, `== 24`, `< 25`): 42 lines in .cc files, all I. Literal `24.0`: 72 lines, mostly I
  (SystemAvailabilityManager 18, TARCOGOutput 16 (not time), ThermalComfort 10, DisplacementVentMgr 5, …).

## 3. Recommended implementation

### 3.1 Run-time hour length (keep the constexpr constants)

1. `Data/DataGlobals.hh` (struct `DataGlobal`) add:
   ```cpp
   Real64 SecInHour   = Constant::rSecsInHour;   // simulation hour length [s] (planetary hour)
   Real64 SecInMinute = Constant::rSecsInMinute; // SecInHour / 60
   Real64 SecInDay    = Constant::rSecsInDay;    // SecInHour * 24 = solar day
   Real64 HourToEarthHr = 1.0;                   // SecInHour / 3600 (exactly 1.0 on Earth)
   ```
   Defaults equal the constexpr values. Unit tests that never call GetProjectData stay unchanged.
2. New input processing `PlanetaryBody::GetInput(state)` (new `PlanetaryBody.{hh,cc}` and
   `state.dataPlanet` with body enum, `solarDaySec`, `yearSec`, `epochJD`, gravity, S₀, …). Call it **first** in
   `SimulationManager::GetProjectData` (SimulationManager.cc:698). That is the first `init_state` call
   (Data/EnergyPlusData.cc:857), so it runs before `TimeStepZoneSec` is computed at :952-954. Set the four globals once.
   Never change them later; add an `assert` in `ManageSimulation` that they are unchanged after input.
3. Change the 4 setters: SimulationManager.cc:954, 1387 and HVACManager.cc:211, 321 → `* state.dataGlobal->SecInHour`.
4. Mechanically replace the 65 S uses of `rSecsInHour` (T04, T05), the 18 S literals (T06, T09, T35), the 10
   `MinutesInTimeStep*60` seconds (T08) and `iSecsInHour` (Ashrae205). Prefer `TimeStepZoneSec`/`TimeStepSysSec`
   when the expression is `TimeStep* × 3600`, otherwise `state.dataGlobal->SecInHour`.
   Do **not** touch the 93 U uses (T07). Optionally rename them to `Constant::rSecsPerHourUnit` in a separate commit. Add a
   CI grep rule that bans `TimeStep(Zone|Sys)\s*\*\s*(Constant::rSecsInHour|3600)`.
5. CTF fix (T10): inside `Construction::calculateTransferFunction`, convert at the physics points only, as listed in T10.
6. Bit-for-bit on Earth: `x * 3600.0` gives the same IEEE result whether 3600.0 is constexpr or a variable. Release
   builds do not use fast-math (cmake/CompilerFlags.cmake:170, 211, 257 are commented out). Multiplying by
   `HourToEarthHr = 1.0` is exact. Check with the full regression suite (expect zero diffs).

### 3.2 Planetary environment generator (weather + sun)

New module `PlanetaryEnvironment.{hh,cc}`, ported from `exobem/ephemeris` and `exobem/environment`. It keeps no weather
state of its own; it writes into the existing structures.

- `void ReadDay(state, int dayToRead, int envrn)`, called from `Weather::ReadWeatherForDay` (WeatherManager.cc:2268)
  when `dataPlanet->active`:
  - calendar labels: Month/Day from `envCurr.StartJDay + dayToRead − 1` via `General::InvOrdinalDay` with LeapYearAdd = 0.
    DayOfWeek cycles 1..7. HolidayIndex from `SpecialDayTypes`. DST = 0.
  - per-day sun: compute decl, EoT, r at local mean solar noon of that day. Use `t_noon = epochJD + ((simDay−1) + 0.5) ·
    SecInDay/86400`. Write `TomorrowVariables.{Sin,Cos}SolarDeclinAngle`, `EquationOfTime` (planetary h) and a new
    `SunDistanceAU`.
  - per `(ts,hr)`: instant `t = (hr−1) + ts/N` planetary hours (or `hr − 0.5` when N = 1, matching
    `TS1TimeOffset`). Compute the same cos-zenith that `DetermineSunUpDown` will compute. Fill beam normal
    `S₀/r²·τ_beam`, diffuse, `HorizIRSky`, `SkyTemp` (2.7 K for vacuum), `OutDryBulbTemp` (Mars near-surface air /
    Moon: a nominal value that is never used), `OutBaroPress` (0 / Mars model), wind, `OutRelHum = 0`, `IsRain = IsSnow = false`.
    Write `wvarsHrTsTomorrow(ts,hr)` directly, with no hourly interpolation.
  - During warmup E+ does not call ReadWeatherForDay at BeginDay, so day 1 repeats automatically. Keep it that way.
- `void SetUpDesignDay(state, int envrnNum)`: the same generator for a design epoch, called from the top of
  `Weather::SetUpDesignDay` (3485).
- `void DailySolar(state, int dayOffset, Real64 &sinDec, Real64 &eot)` for `SolarShading::SUN3`'s callers (9060, 9071).
- `void SetCurrentWeatherPlanetary(state)`, called in `SetCurrentWeather` after the `today` copy (2108). It skips moist-air
  psychrometrics, sets outdoor ρ/h from the body gas, sets `GroundTemp[*]` from the regolith model, sets
  `GndReflectance = albedo` and sets the illuminance from a fixed luminous efficacy (no Perez). Keep the EMS override lines.
- Unchanged and reused: `DetermineSunUpDown`, `CalculateSunDirectionCosines`, `SUN4`, `FigureSunCosines`,
  `CalcPerSolarBeam`, `SetupInterpolationValues` (unused on the planetary path), all 24-hour arrays.
- Site settings in planetary mode: `TimeZoneMeridian = Longitude`. Skip `CheckLocationValidity` and `GetSTM`. Skip
  EPW open / header / rewind (T29). `NumOfDayInEnvrn` from RunPeriod (day = solar day).
- New outputs: elapsed time [s], LTST [h], Ls [deg], sun distance [AU], subsolar lat/long.

### 3.3 Schedules, sizing, outputs

- ScheduleManager: no change for P0. P1: "Earth-clock" evaluation option, i.e. a schedule type (or a field on
  `Schedule:Day:*`) evaluated at `mod(elapsedSec, 86400)` instead of (hour, timestep). Needed for lunar crew
  cycles. A Mars year longer than 366 sols: document the wrap, or add a Ls-indexed year schedule later (P2).
- Sizing: `SizingPeriod:PlanetaryDesignDay`. Planetary default `NumTimeStepsInAvg = 1`. Reject EPW-based sizing periods.
- Outputs: keep OutputProcessor. Tabular "hours" columns scaled by `HourToEarthHr` (or relabelled). Annual reset
  (T14) uses the planet year.
- HVAC: the planetary min system timestep is given in seconds (T13).

### 3.4 What to leave alone

All hour / timestep / day loops. The `iHoursInDay` (170) and minute-grid (51) structural uses. ScheduleManager
indexing. Warmup logic. OutputProcessor accumulation. Day-of-week / holiday labels. The hour-angle formulas. Every U-class
3 600 (ACH, kWh, Btu/h, lb/h, cycles/h, user "hours" inputs). The Earth solar series (they stay for Earth runs). The
Slinky 356-day typo (report it upstream instead).

## 4. Open questions / risks

1. **Moon time resolution.** 1 771.8 s is the floor, and HVAC sub-stepping is lost at 60 steps/h. Ideal loads and the
   envelope are fine (the Python reference uses 1 800 s). On/off thermostats and fast equipment are not. A finer step
   would mean lifting the 60 cap: `MinutesInTimeStep` becomes Real or seconds-based, and the 1440-minute schedule grid
   and ScheduleManager.cc:209-236 must be rebuilt. That is a large, risky change. Recommend deferring it and first
   allowing sub-minute HVAC sub-steps (T13).
2. **Meaning of "hour" for users.** Inputs in "per hour" stay Earth hours (ACH etc.). "Hourly" outputs and schedule times
   are planetary. This needs clear documentation and maybe output column renames. EMS / Python plugin code that
   multiplies by 3 600 will silently be wrong (T36).
3. **Calendar.** A Moon year is 12.4 lunar days (all in "January"). A Mars year is 669 sols (2 calendar years). Monthly
   reports and seasonal schedules are close to meaningless. Should we adopt a planetary calendar (Darian months for Mars;
   "month = lunation" for the Moon)? Defer. Labels are harmless for P0.
4. **Solar-day definition.** We use the mean solar day. The true lunar synodic month varies by about ±0.3 d, and Mars
   LTST − LMST reaches about ±50 min. EoT absorbs both, provided the generator gives EoT per day. Declination is constant
   per day; the error is ≤ 0.8° per lunar day and < 0.4° per sol, which is acceptable.
5. **Sun-position consistency.** `SolarShading` uses period-averaged δ/EoT (20 days) while `SOLCOS` uses daily values.
   This is the same approximation as on Earth. On the Moon near the terminator, beam on/off timing differs by up to one
   timestep (1 772 s), as on Earth.
6. **Bit-for-bit risk.** It is low, but any replaced expression must keep its operand order (e.g. `a / b / 3600` must
   become `a / b / SecInHour`, not `a / (b * SecInHour)`). Review each of the ~95 edits.
7. **CTF (T10)** belongs to the constructions audit as well. Make sure only one agent implements it, and verify it
   against the Python conduction model at Moon Δt (1 772 s and 21 262 s).
8. **Ground / regolith BC.** Ground-contact floors need the regolith model from day 1. The Earth ground-temperature
   objects should be rejected in planetary mode rather than silently used.
9. **Design days.** Is sizing needed for the first run? If not, P0 can be "planetary mode forbids DesignDay and the
   sizing flags", and T24 moves to P1.
