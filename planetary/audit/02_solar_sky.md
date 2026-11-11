# 02 – Solar geometry, solar radiation, sky / ground long-wave, daylighting

Audit of Thermonaut (fork of EnergyPlus v26.2.0, branch `planetary`). Line numbers refer to
`src/EnergyPlus/*` unless another path is given. Python reference: `exobem/ephemeris/{earth,mars,moon}.py`,
`exobem/solar.py`, `exobem/environment/{twostream,sites,regolith}.py`, `exobem/simulation.py`.

## 1. Summary

- The solar machinery splits cleanly into (a) a **daily** solar ephemeris (sine/cosine of declination,
  equation of time), which uses Earth-only Fourier fits keyed on day-of-year, and (b) an **hourly/timestep**
  geometry that turns (declination, EoT, clock hour, longitude, time-zone meridian) into sun direction
  cosines with `15 deg/hour`. Under the planned "planetary hour" (1 h = sol/24), part (b) is exact for any
  body and can be reused unchanged. Only part (a) has to change, and it lives in two places:
  `Weather::CalculateDailySolarCoeffs` and a duplicate `SolarShading::SUN3`.
- Radiation inputs (`BeamSolarRad` = DNI, `DifSolarRad` = DHI, `GndSolarRad`, `SkyTemp`) are consumed
  planet-agnostically by shading, heat balance and windows. If the planetary environment generator fills the
  same per-timestep `WeatherVars` (DNI from S0/r², delta-Eddington split on Mars, 2.725 K sky on the Moon),
  almost nothing downstream needs to know the planet.
- The real Earth physics that must be branched on is small but spread out: the Perez sky model (1353 W/m²,
  Earth air mass), the sky/air long-wave split `sqrt(0.5(1+cos tilt))`, "ground long-wave temperature = outdoor
  air temperature" (10 core sites), the sky-emissivity models, monthly/snow ground reflectance, design-day
  solar models (1367/1355 W/m², ASHRAE A/B/C, Kasten-Young air mass), Perez luminous efficacy, and AM1.5
  window spectra.
- Difficulty: **moderate**. The P0 set for a single-zone opaque Moon/Mars run touches about 8 functions.
  The one awkward part is that the daily ephemeris is keyed on `DayOfYear` (1..366). The planetary version
  needs an absolute date (JD or sol number). That depends on the calendar decision made by the time/weather audit.

## 2. Findings

Priorities: P0 = needed for a first single-zone, opaque, ideal-loads Moon/Mars run; P1 = windows, HVAC, PV,
sizing, realistic outputs; P2 = rarely used, or flag "unsupported off-Earth".

### 2.1 Solar position

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| S01 | WeatherManager.cc:4129-4235 (coeffs 4171-4183, `DayCorrection = 2π/366` 4168, decl 4192-4198, EoT 4200-4205) | `CalculateDailySolarCoeffs` | 9-term Fourier fit (Threlkeld) of Earth declination (±23.45°) and EoT (±16 min) vs. day-of-year; 366-day year | Wrong declination and EoT on Mars (obliquity 25.19°, eccentricity 0.0934, EoT up to ±50 Mars-min) and on the Moon (subsolar latitude ±1.54°, period 346.6 d) | Branch on body: call new `Planetary::dailySolarGeometry(state, jdAtSolStart)` (port of `mars.py`/`moon.py`). It returns sinDec, cosDec, EoT in *planetary hours* and r [AU]. Keep the Earth code byte-identical | P0 |
| S02 | SolarShading.cc:9449-9504 (`X = 0.017167*JulianDayOfYear` 9485); callers 9056-9071 | `SUN3` (duplicate of S01 without state) used by `PerformSolarCalculations` | Same Earth Fourier fit, 2π/366 | Shading/sunlit fractions and `SurfCosIncAng` (which drive beam on **opaque** walls) computed for Earth sun paths, inconsistent with S01 | Replace the SUN3 loop in `PerformSolarCalculations` by the same planetary function as S01, iterating JD by one sol per day. Both call sites must use one implementation | P0 |
| S03 | SolarShading.cc:463-475 (default 20, warn >31); 9036-9071 | `ShadowingCalcFrequency`, `ShadowingDaysLeft`, averaged `AvgSinSolarDeclin/AvgEqOfTime` | Averaging declination over 20 days is fine when one day = 1/365 of the seasonal cycle | Mars: 20 sols ≈ 11° of Ls, about the same error as on Earth (OK). Moon: 20 lunar days = 590 Earth days = 1.7 eclipse years, so averaging sinDec gives ≈0. Wrong sun paths at polar sites | Off-Earth Moon: force frequency = 1 (one lunar day) or Timestep method; Mars: keep default, document. Emit a warning if the user gives >1 on the Moon | P0 (Moon) |
| S04 | WeatherManager.cc:2841, 2847-2855 (weather file); 3546, 3597-3598 (design day); SolarShading.cc:9056 | `TomorrowVariables.DayOfYear = OrdinalDay(Month,Day)`, passed to S01/S02 | Ephemeris keyed on Earth calendar day-of-year | No absolute time, so Mars Ls / lunar phase can't be found from (Month, Day) | Add `Real64 Planetary::jdAtSolStart(state, Year, DayOfYear)` (or keyed on the sol number in the planetary weather record). Use it at all three call sites. Needs the calendar decision (see Q1) | P0 |
| S05 | WeatherManager.cc:4260 (`CalculateSunDirectionCosines`), 4292-4298 (`DetermineSunUpDown`), SolarShading.cc:9530 (`SUN4`), 5079-5083 (`FigureSunCosines`) | Hour angle `H = 15·(12 − (t+EoT)) + (TZM − Lon)` | 15°/hour = 360°/24 h | **Exact on any body** if hour = sol/24 and EoT is in planetary hours. Longitude east-positive matches Mars24 IAU (exobem) | **Leave unchanged.** Convention: clock = local mean solar time at `TimeZoneMeridian`. Set Mars/Moon `TimeZone = Lon/15` (LMST at site) or 0 (MTC / "lunar prime-meridian time"). EoT := LTST − clock time at mid-sol | — (reuse) |
| S06 | WeatherManager.cc:4528-4560 | `CheckLocationValidity`, `GetSTM` (7433) | Time zones −12..+14, warnings if TZ differs from longitude/15 by >1 h | Harmless if TZ = Lon/15. With MTC (TZ 0 at Lon 77°) it gives a false "Solar Positions will be incorrect" severe message | Skip the STM comparison off-Earth | P2 |
| S07 | WeatherManager.cc:4303-4321 | `DetermineSunUpDown` azimuth via `acos(.../(CosLat·sinZ))` | — | At \|lat\| = 90° exactly: 0/0 gives NaN in the reported azimuth only (SOLCOS stays fine). Lunar south-pole sites are typically −89.5…−89.9° | Clamp \|lat\| ≤ 89.99° off-Earth, or guard the azimuth | P2 |
| S08 | DataEnvironment.hh:81 `SunIsUpValue = 1e-5`; all shading | Sun = point source, no refraction | — | Moon: no refraction (correct). Polar Moon/Mars: grazing sun, finite disk 0.27°·(1/r) not modelled (exobem uses `horizon_visible_fraction`) | Generator multiplies DNI by the visible-disk fraction (as exobem does). E+ geometry unchanged. Terrain via `Shading:Site:Detailed` or the external-shading schedule | P2 |
| S09 | WeatherManager.cc:4295-4298; SolarShading.cc:5077-5081; WeatherManager.cc:3866-3870 | `CurrentTime` = end of timestep (TS1: mid-hour, `TS1TimeOffset = −0.5`) | — | exobem evaluates the sun at the step midpoint. Moon at 60 ts/h: half a timestep ≈ 0.25° | Accept; note as a known E+/Python difference in verification | P2 |
| S10 | (whole chain) | Daily-constant declination/EoT | Declination changes ≤0.4°/day on Earth | Moon: subsolar latitude changes up to ~0.8° across one lunar day (it is held constant). Lunar EoT from Earth's orbital eccentricity is ±1.9° (≈±0.13 lunar h) and nearly constant over one lunar day. Libration in longitude does **not** move the subsolar point | Accept daily constant (use the mid-sol value). Optional later: per-timestep update when `DetailedSolarTimestepIntegration` is on | P2 |

### 2.2 Extraterrestrial irradiance, clear-sky models, direct/diffuse split

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| S11 | WeatherManager.cc:3501-3511 | `GlobalSolarConstant = 1367`, `ZHGlobalSolarConstant = 1355`, Zhang-Huang C0..C5, D, K | Earth TSI; regression on Earth weather (cloud, RH, wind) | Design-day beam/diffuse wrong for any planet | Off-Earth: new `DesDaySolarModel::Planetary`. ASHRAE/Tau/Zhang-Huang give a severe error off-Earth | P1 |
| S12 | WeatherManager.cc:4207 | `AnnVarSolConstant = 1.000047 + …` | Earth orbit (e = 0.0167), 1/r² ±3.3% | Mars 1/r² varies ±19% (r = 1.381…1.666 AU); Moon ≈ Earth | Return 1/r² from the planetary ephemeris (S01). Store `state.dataEnvrn->SunDistanceAU` and `ExtraterrestrialDNI = S0/r²`, with S0 = 1361 from `Site:PlanetaryBody` | P1 (design) / P0 in generator |
| S13 | WeatherManager.cc:4171-4180, 4209-4234 | ASHRAE A, B, C coefficients (incl. southern-hemisphere half-year shift 4218-4223) | Earth clear-sky extinction | Meaningless off-Earth | Not used by the planetary model; leave Earth code alone | P1 (covered by S11) |
| S14 | WeatherManager.cc:3883-3940 | Design-day `ASHRAE_ClearSky` / `ASHRAE_Tau(2017)` / `Zhang_Huang` | Earth atmosphere, KT diffuse correlation | — | Planetary design-sol model: Moon DNI = S0/r², DHI = 0. Mars: C++ port of `twostream.delta_eddington_surface` (w0 0.885, g 0.74, spherical air mass with R/H = 3390/11, as in `sites.py:197-214`) with a design τ | P1 |
| S15 | WeatherManager.cc:4026-4057 | `AirMass` (Kasten-Young 1989) used by ASHRAE Tau | Earth refraction/scale height; limit 37.08 | Mars air mass is different (spherical shell, H ≈ 11 km); Moon has none | Not called off-Earth if S14 is done; Mars air mass lives in the generator | P1 |
| S16 | WeatherManager.cc:2233-2238 | `GndSolarRad = (DNI·cosZ + DHI)·GndReflectance`; zeroed when sun down | Generic | Correct for any body once DNI/DHI and reflectance are planetary | Reuse | — |
| S17 | HeatBalanceSurfaceManager.cc:2857-3046 | `InitSolarHeatGains`: `SurfSkySolarInc = DHI·mult·SurfAnisoSkyMult`, `SurfGndSolarInc = GndSolarRad·ViewFactorGround` | Generic | Correct for any body | Reuse | — |
| S18 | Photovoltaics.cc:1931-1955; PlantPipingSystemsManager.cc:4284 | `AbsoluteAirMass` (exp(−0.0001184·alt)), `MeanSolarConstant = 0.08196 MJ/m²·min` | Earth atmosphere scale height 8.4 km; Earth TSI | PV spectral factor F1 and the ground-surface energy balance are Earth-specific | Cross-ref PV / ground audits. Flag Sandia PV and PipingSystem ground surface "unsupported off-Earth" until ported | P1/P2 |

### 2.3 Sky diffuse model, ground reflectance, view factors

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| S19 | SolarShading.cc:2630-2803 (air mass 2718-2724, `Delta = DHI·AirMass/1353` 2727, F11R.. tables 2677-2690); caller HeatBalanceSurfaceManager.cc:469-473 | `AnisoSkyViewFactors` (Perez 1990) | Earth sky brightness/clearness bins; `AirMassH = 1 − 0.1·Elev/1000`; 1353 W/m² | Moon: never called (DHI = 0, so `SurfAnisoSkyMult = 0`), correct. Mars: Perez coefficients fitted to Earth skies. Delta is mis-scaled (Mars ETR ≈ 490-720 W/m²), and the elevation correction uses Earth's 10 km scale height. The delta-Eddington beam already includes the forward aureole, so the remaining diffuse is close to isotropic (exobem default `model="isotropic"`) | New `SkyDiffuseModel {Perez, Isotropic}` in `Site:PlanetaryBody` (default Isotropic off-Earth). In `AnisoSkyViewFactors` set F1 = F2 = 0 when Isotropic. The rest of the routine then gives `SurfAnisoSkyMult = ViewFactorSky·DifShdgRatioIsoSky`, keeping sky shading. If Perez is kept off-Earth, use `ExtraterrestrialDNI` in place of 1353 and the planet's air mass | P0 (Mars) |
| S20 | SurfaceGeometry.cc:1303-1309, 4981-5002, 6363-6400, 9516-9517, 9664-9665 | `ViewFactorSky = 0.5(1+cosT)`, `ViewFactorGround = 0.5(1−cosT)`, IR copies | Flat infinite horizon | Generic geometry; valid on any body. Lunar polar craters need user-set view factors or SurroundingSurfaces | Reuse | — |
| S21 | WeatherManager.cc:2097-2098; 6927-6980 (`Site:GroundReflectance`, monthly, default 0.2) | `GndReflectance = GroundReflectances(Month)` | Monthly albedo; month = 1/12 Earth year | Month index is meaningless for a sol calendar. Lunar regolith albedo depends on incidence angle, A(i) = 0.12 + 0.06(i/45)³ + 0.25(i/90)⁸ (`regolith.py:73-75`). Mars ≈ 0.14-0.25 | First run: user enters 12 equal values (no code). Proper fix: off-Earth, after 2098 set `GndReflectance = today.Albedo` (EPW Albedo field, already parsed into `WeatherVars::Albedo` WeatherManager.hh:727 and currently used only by PVWatts) and a visible albedo for daylighting, both from the generator | P0 (input) / P1 (hook) |
| S22 | WeatherManager.cc:2226-2231; 6985-7045 | Snow modifier `SnowGndRefModifier(ForDayltg)` when `IsSnow` | Earth snow | No snow; Mars seasonal CO₂ frost (albedo ~0.6) could reuse it | Off-Earth: generator sets `IsSnow = false`; Mars frost is an open question | P2 |
| S23 | HeatBalanceSurfaceManager.cc:461, 10293-10331; SurfaceGeometry.cc:8240-8350 | `SurfaceProperty:GroundSurfaces` (temp/reflectance schedules), `SurfaceProperty:SurroundingSurfaces` (sky-temp / ground-temp schedules, view factors) | — | Usable today as a **no-code** route for planetary ground temperature/reflectance via schedules | Document as fallback only. See S30 for its inconsistencies | P1 |

### 2.4 Long-wave: sky temperature, sky/air split, ground temperature, exterior LW coefficients

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| S24 | WeatherManager.cc:3191-3214 | `CalcSkyEmissivity`: Clark-Allen (default), Brunt, Idso, Berdahl-Martin, cloud correction (1 + 0.0224·N …) | Water-vapour emissivity of Earth air (0.618-0.787 base), dew point | Moon: should be T_sky = 2.725 K (exobem `T_CMB`). Mars: CO₂ + dust, ε_sky = clip(0.08 + 0.125τ, 0.05, 0.6) plus dust re-emission 0.45·⟨G_toa,h − G_h⟩_sol (`sites.py:220-252`) | Add `SkyTempModel::Planetary` **at the end** of the enum (names 121-130) so Earth enum values do not change. Moon: SkyTemp = 2.725 K − 273.15. Mars: L↓ from the generator, `SkyTemp = (L↓/σ)^¼`. Never call the Earth emissivity models off-Earth | P0 |
| S25 | WeatherManager.cc:2736-2738, 8871-8873 (`calcSky`), 8876 | `IRHoriz <= 0` gives 9999 = missing, which falls back to Clark-Allen from dry bulb | Earth IR is never ≤ 0 | Moon L↓ = σ·2.725⁴ = 3.1×10⁻⁶ W/m². If a planetary EPW stores it as integer 0, it is treated as missing and sky emissivity is computed from "dry bulb" (very wrong). The EPW route also passes through dew point/RH-based models | Off-Earth: skip the ≤ 0 guard, take IR as given, or bypass `calcSky` entirely for the internal generator (write `HorizIRSky`, `SkyTemp` into `wvarsHrTsTomorrow` directly). Also check the EPW range validator for the IR field (weather audit) | P0 |
| S26 | WeatherManager.cc:3845-3851; 3982-4018; 6706-6900 | Design-day sky temperature (same models); `WeatherProperty:SkyTemperature` (schedule / DB-delta / DP-delta) | — | Schedule value −270.425 °C works today as a no-code Moon fallback | Design sol uses `SkyTempModel::Planetary` | P1 |
| S27 | SurfaceGeometry.cc:329 (set), 876 (init 0); consumers ConvectionCoefficients.cc:665, 677; DataSurfaces.cc:323-324; WindowManager.cc:2208-2209, 2484-2485, 2617, 2620; WindowComplexManager.cc:2829-2830; WindowEquivalentLayer.cc:789-790 (17 lines, 6 files) | `SurfAirSkyRadSplit = sqrt(0.5·(1 + cosTilt))` | Thick, near-isothermal Earth boundary layer: near-horizon sky radiates at air temperature (TARP/Walton) | Moon: no air, so the (1−split) part (29% for a wall) would exchange with "outdoor air temperature", which is undefined. Mars: the generator's L↓ is already hemispheric. Splitting it double-counts warm near-horizon air | Off-Earth (`skyIncludesAir = false`): set `SurfAirSkyRadSplit = 1.0` at SurfaceGeometry.cc:329. Then HAir = 0 automatically everywhere. Matches exobem `simulation.py:319-322` | P0 |
| S28 | ConvectionCoefficients.cc:446-460, 661-680 | `InitExtConvCoeff`: `TSky = SkyTempKelvin`, **`TGround = TAir`** (surface outdoor dry bulb), HSky/HGround/HAir = σε F (T⁴ − Tᵣ⁴)/(T − Tᵣ); guard `TSurf == TAir` (669) also zeroes HGround | Ground surface temperature ≈ outdoor air temperature | Moon: lunar regolith 95-390 K vs. undefined air. Mars: ground diurnal swing ≈ 2× the air swing (`sites.py` air model). Ground LW to every wall would be wrong by up to ±100 W/m² | Add `state.dataEnvrn->GroundSurfTemp` (°C) / `…Kelvin`, filled per timestep from the generator (`WeatherVars::GroundSurfTemp`, new). Off-Earth: `TGround = GroundSurfTempKelvin` (unless GroundSurfaces property applies). Change the 669 guard to test TGround for HGround | P0 |
| S29 | HeatBalanceSurfaceManager.cc:9823-9839 (`CalcOutsideSurfTemp`), uses at 9865-9870, 10023 | `TSky = SkyTemp`, **`TGround = OutDryBulbTemp`** (global, not the surface value used in S28) | As S28 | As S28; also a small existing Earth inconsistency (HGround linearised about surface T_air, applied with global T_air) | Same helper as S28 so both sites use the identical ground temperature | P0 |
| S30 | ConvectionCoefficients.cc:450-460 vs HeatBalanceSurfaceManager.cc:9832-9834; HeatBalFiniteDiffManager.cc:1703-1706 | SurroundingSurfaces `groundTempSched` is used in the balance but **not** in the HGround linearisation. CondFD reads `GroundSurfsProperty(Surf)`, indexed by surface number instead of `SurfPropertyGndSurfIndex` (upstream bug); default `Tgnd = TempOutsideAirFD` | — | The no-code schedule route (S23) gives inconsistent HGround and, for CondFD, wrong data. CondFD ground = air as in S28 | Fix the index and use the S28 helper in CondFD. Make HGround use the same TGround as the balance (only when off-Earth, if bit-for-bit Earth is required) | P1 |
| S31 | DataSurfaces.cc:306-328 (`getOutsideIR`, used by WCE WindowManagerExteriorThermal.cc:830-844); WindowManager.cc:2195-2210, 2475-2486, 2603-2620; WindowComplexManager.cc:2815-2831; WindowEquivalentLayer.cc:775-790 | Window outside IR: `Outir = F_sky[split·σT_sky⁴ + (1−split)·σT_out⁴] + F_gnd·σT_out⁴`; `tout` = wet bulb if raining | Ground and near-horizon sky at outdoor air temperature | As S27/S28 for every window model (4 models) | Off-Earth: split = 1 (S27). Ground term uses `GroundSurfTempKelvin`. Keep `tout` for the convection side | P1 |
| S32 | ConvectionCoefficients.cc:661-662 | `extConvAlgo == ASHRAESimple`: HSky = HGround = HAir = 0 (radiation folded into an Earth combined coefficient) | Earth combined h_c+h_r correlation | Sky LW lost off-Earth | Severe error if ASHRAESimple (outside) is used off-Earth (cross-ref convection audit) | P0 |
| S33 | HeatBalanceKivaManager.cc:389; HeatBalanceHAMTManager.cc:1183-1209; EcoRoofManager.cc:215-217; PhotovoltaicThermalCollectors.cc:1150, 1386; TranspiredCollector.cc:1294, 1905; SolarCollectors.cc:1838-1840; PipeHeatTransfer.cc:1380-1431; PondGroundHeatExchanger.cc:574; SurfaceGroundHeatExchanger.cc:537, 733 | Component sky/ground LW (27 sky-temperature reads in 17 files outside WeatherManager) | Kiva `skyEmissivity = T_sky⁴/T_out⁴`; ground = outdoor air in collectors/PVT | Kiva emissivity formula undefined in vacuum; collectors assume air | Cross-ref ground (Kiva) and plant/PV audits. Flag EcoRoof, HAMT, collectors, ponds and pipes "unsupported off-Earth" | P1/P2 |

### 2.5 Daylighting

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| S34 | WeatherManager.cc:7343-7431 (coeff tables 7361-7376, `ExtraDirNormIll` monthly 7375-7376, `relAirMass` with elevation 7389-7390, `93.73` 7391-7392, `AtmosMoisture = exp(0.07·Tdp − 0.075)` 7413) | `DayltgLuminousEfficacy` (Perez 1990) | Earth-sky luminous efficacy fits; Earth extraterrestrial illuminance by month; water vapour from dew point | **Moon bug:** DHI = 0 gives SkyBrightness = 0, then `DirLumEff = 0` (7423-7424), so `HISUNF = 0` and no daylight from the sun at all. Mars: dust-reddened efficacy unknown | Off-Earth: `PDIRLW` = beam efficacy from `Site:PlanetaryBody` (Moon: AM0 ≈ 93.7 lm/W, the code's own extraterrestrial value); `PDIFLW` = diffuse efficacy (Moon 0; Mars user/estimated). Keep SkyClearness/SkyBrightness only for sky-type weighting | P1 |
| S35 | WeatherManager.cc:7295-7341 | `DayltgCurrentExtHorizIllum`: HISKF = DHI·PDIFLW, HISUNF = DNI·cosZ·PDIRLW, `CloudFraction = (DHI/GHI)²` | — | Generic once S34 is fixed (Moon: CloudFraction 0, HISKF 0) | Reuse | — |
| S36 | DaylightingManager.cc:8567-8620 (`DayltgSkyLuminance`); 5260-5324 (`DayltgExtHorizIllum`); 5982-5993, 6857-6868 (sky-type weighting); 6120-6156 | CIE clear, clear-turbid, intermediate, overcast luminance distributions; weighting by Perez clearness | Earth sky radiance shapes | Moon: HISKF = 0, so sky terms vanish (correct). Mars: brownish sky with strong aureole; CIE shapes are an approximation, but daylight factors are renormalised by HISKF | Accept for Mars (P2); document. Ground luminance uses `GndReflectanceForDayltg` (3113-3115, 7418, 7439, 8109-8119), set from the planetary visible albedo (S21) | P2 |
| S37 | DaylightingManager.cc:5698-5723; third_party/DElight/DFcalcs.cpp:161-189 (`phsmax = 113.5 − \|lat\|`, ±110° azimuth), SOL.cpp:222-245 (`dsolic`, Earth monthly extraterrestrial illuminance, 2π/366), SOL.cpp:602-640 (`sun1` Earth Fourier), 678 (hour angle 0.2618 rad/h) | DElight | Earth obliquity 23.5° built into the sun-position grid; Earth calendar | Sun grid range wrong on Mars (obliquity 25.2°) and the standalone `dillum` path uses an Earth ephemeris | Flag `Daylighting:DElight` "unsupported off-Earth" (severe error) | P2 |

### 2.6 Window solar/visible spectra

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| S38 | WindowManager.hh:426-445 (`wle`, `e`: ISO 9845-1 AM1.5 global, 107 points 0.30-2.537 µm); WindowManager.cc:1981-1993 (`solarSpectrumAverage`), 583-736, 943; WindowManagerExteriorData.cc:118-140, 248; WindowManagerExteriorOptical.cc:329-343 | Spectral averaging of glazing T/R/A | Terrestrial AM1.5 spectrum (atmosphere absorption bands, UV cut) | Moon: AM0 (ASTM E490) has more UV and blue light and ~7% of its energy below 0.3 µm. Mars surface: dust-reddened. Spectral-to-broadband glazing properties can shift by a few % (more for low-e and tinted glass) | No code needed: ship `Site:SolarAndVisibleSpectrum` + `Site:SpectrumData` for AM0 and Mars, **resampled to exactly 107 points** on the same grid (see R4). Warn off-Earth when glazing uses `SpectralAverage` input (user-supplied AM1.5 averages) | P1 |
| S39 | WindowManager.cc:8290-8395 | `CheckAndReadCustomSpectrumData` | — | Fewer than 107 pairs leave trailing `wle = e = 0`. The integrand step at the last real point then becomes negative in `solarSpectrumAverage` (1988), which looks like an upstream defect | Supply 107 pairs (S38), or fix by limiting the loop to the entered count (Earth runs with full default spectra stay unchanged) | P1 |
| S40 | WindowManager.cc:1995-2020 (`visibleSpectrumAverage`), `wlt3`/`y30` (photopic × illuminant) | Visible properties | Photopic eye response (planet-independent) × Earth illuminant | Illuminant weighting differs slightly (Moon: no atmosphere) | Leave; optional custom visible spectrum | P2 |

## 3. Recommended implementation

### 3.1 Data to add (all defaults reproduce Earth exactly)

`DataEnvironment.hh` (or a new `DataPlanetary.hh` owned by the `Site:PlanetaryBody` reader):

```cpp
enum class PlanetBody { Earth, Moon, Mars, Custom };
enum class SkyDiffuseModel { Perez, Isotropic };
struct PlanetarySolar {
    PlanetBody body = PlanetBody::Earth;
    Real64 solarConstant1AU = 1361.0;    // W/m2 (exobem TSI_1AU); Earth code keeps its own 1367/1353/1355
    Real64 epochJD = 0.0;                // JD(UTC) of clock 00:00 at TimeZoneMeridian on sol 1 of the run
    Real64 solDaySec = 86400.0;          // shared with the time audit (planetary hour = solDaySec/24)
    SkyDiffuseModel skyDiffuse = SkyDiffuseModel::Perez;   // Isotropic default off-Earth
    bool skyIncludesAir = true;          // false off-Earth -> SurfAirSkyRadSplit = 1
    Real64 cmbSkyTempK = 2.725;          // Moon / Custom vacuum
    Real64 beamLumEff = 93.73, diffLumEff = 0.0;  // lm/W, used only off-Earth
};
// per sol / per timestep state
Real64 SunDistanceAU = 1.0;              // from ephemeris (per sol)
Real64 ExtraterrestrialDNI = 0.0;        // S0 / r^2
Real64 GroundSurfTemp = 0.0, GroundSurfTempKelvin = 0.0;   // regolith skin T for LW exchange
```

`WeatherManager.hh` `WeatherVars` (713-732): add `Real64 GroundSurfTemp`. Reuse the existing `Albedo`
(727) for the per-timestep ground solar reflectance, and add `AlbedoVis` if a separate visible value is wanted.

### 3.2 New module `PlanetaryEphemeris.{hh,cc}`

A port of `exobem/ephemeris/{earth,mars,moon}.py` and `__init__.horizontal_geometry`:

```cpp
struct DailySun { Real64 sinDecl, cosDecl, eotHours /*planetary h*/, rAU; };
DailySun dailySolarGeometry(EnergyPlusData const &state, Real64 jdSolStart);
Real64   jdAtSolStart(EnergyPlusData const &state, int year, int dayOfYear);   // calendar audit decides mapping
```

- Mars: Allison & McEwen (2000) / Mars24 (`mars.py:28-49`): Ls, declination
  `asin(0.42565 sin Ls) + 0.25 sin Ls`, EoT (deg) / 15 → Mars hours, r(M). Evaluate at mid-sol
  (jdSolStart + 0.5·solDaySec/86400) and use TT − UTC = 69.184 s.
- Moon (`moon.py:31-41`): subsolar latitude `1.5424·sin(λsun − Ω)` gives the declination. EoT = (clock − LTST)
  at mid-sol, where LTST = 12 + (TZM − lon_ss)/15 wrapped to ±12; r = Earth's r.
- EoT sign: E+ uses `t + EoT` = apparent solar time, the same as Mars24's LTST = LMST + EOT/15. No sign flip.
- Write a unit test against the Python values (zenith/azimuth at 3 sites × 4 seasons, tolerance 0.01°).

### 3.3 Hooks (each guarded by `body != Earth`; Earth branch untouched)

1. **Daily ephemeris (S01, S04, S12):** at the top of `CalculateDailySolarCoeffs` (WeatherManager.cc:4129),
   branch off-Earth. Callers at 2847 and 3597 pass `jdAtSolStart(Year, DayOfYear)` (new overload or extra
   argument). Return EoT, sin/cos declination; set `AnnVarSolConstant = 1/r²` and `SunDistanceAU`.
   The A, B, C outputs are unused off-Earth.
2. **Shading ephemeris (S02, S03):** in `PerformSolarCalculations` (SolarShading.cc:9056-9071), replace the
   `SUN3(PerDayOfYear…)` loop with the same `dailySolarGeometry`, stepping jd by `solDaySec/86400` per sol.
   In `InitSolarCalculations` after 466-475, force `ShadowingCalcFrequency = 1` for the Moon (warn).
   Do **not** touch `SUN4`, `FigureSunCosines`, `CalcPerSolarBeam`, `FigureSolarBeamAtTimestep`,
   `CalculateSunDirectionCosines`, `DetermineSunUpDown`. They are exact under planetary hours.
3. **Generator contract (S12, S14, S24, S25):** the planetary environment generator fills
   `wvarsHrTsTomorrow(ts,hr)` per timestep with `BeamSolarRad` (DNI), `DifSolarRad`, `HorizIRSky`, `SkyTemp`,
   `Albedo`, `GroundSurfTemp`, `IsRain = IsSnow = false`. It must compute the sun with E+'s own
   `CalculateSunDirectionCosines(CurTime, EoT, sinDec, cosDec)` using the same `CurTime` convention as
   `SetUpDesignDay` (WeatherManager.cc:3863-3874). This keeps DNI zero exactly when E+ says the sun is down.
   The design-day per-timestep loop (3860-3960) is the template, and a planetary design sol (S14) can share
   the code.
   - Moon: DNI = S0/r²·(visible disk fraction), DHI = 0, T_sky = 2.725 K, T_ground from a regolith column.
   - Mars: DNI/DHI from the delta-Eddington port (`twostream.py:23-80`) with τ(Ls) (`sites.mars_dust_tau`),
     w0 = 0.885, g = 0.74, spherical air mass, L↓ = ε(τ)σT_air⁴ + 0.45·⟨G_toa,h − G_h⟩_sol.
   - If a planetary EPW is used instead, bypass the `IRHoriz <= 0` guard (2736, 8871) off-Earth.
4. **Ground reflectance (S21, S22):** in `SetCurrentWeather` after 2098, set off-Earth
   `GndReflectance = today.Albedo; GndReflectanceForDayltg = today.AlbedoVis`, skip the snow block (2226).
   Also set `GroundSurfTemp(Kelvin)` from `today.GroundSurfTemp` next to `SkyTemp` (2186-2187).
5. **Sky/air split (S27):** SurfaceGeometry.cc:329 sets `SurfAirSkyRadSplit = skyIncludesAir ? sqrt(...) : 1.0`.
6. **Ground LW temperature (S28-S31):** add `inline Real64 groundLWTempC(state, SurfNum)` (DataSurfaces).
   On Earth it returns the value each call site uses today (so bit-identical); off-Earth it returns
   `GroundSurfTemp`, with SurfaceProperty:GroundSurfaces still taking precedence. Apply at
   ConvectionCoefficients.cc:447 (and guard 669), HeatBalanceSurfaceManager.cc:9824, HeatBalFiniteDiffManager.cc:1706
   (fix 1704 index), DataSurfaces.cc:321-325, WindowManager.cc:2206-2210 / 2482-2486 / 2618,
   WindowComplexManager.cc:2827-2831, WindowEquivalentLayer.cc:786-790, HeatBalanceHAMTManager.cc:1195.
   That is 10 core sites. HSky/HGround formulas stay as they are; they are exact radiation linearisations and
   work at T_sky = 2.7 K.
7. **Sky diffuse (S19):** in `AnisoSkyViewFactors` (SolarShading.cc:2718-2739), if `skyDiffuse == Isotropic`
   set F1 = F2 = 0 and skip Epsilon/Delta. The per-surface loop then yields
   `ViewFactorSky·DifShdgRatioIsoSky` (keeping sky-diffuse shading). For Perez off-Earth, replace 1353 with
   `ExtraterrestrialDNI` and the air mass with the planet's.
8. **Daylighting (S34):** in `DayltgLuminousEfficacy` (WeatherManager.cc:7343), off-Earth return
   `beamLumEff`/`diffLumEff` from `Site:PlanetaryBody`. Still compute SkyClearness/SkyBrightness for the CIE
   weighting. This fixes the Moon `HISUNF = 0` problem.
9. **Input validation:** severe error off-Earth for `ASHRAESimple` outside convection (S32), ASHRAE/Tau/
   Zhang-Huang design-day solar models (S11), `Daylighting:DElight` (S37), Clark-Allen/Brunt/Idso/Berdahl-Martin
   sky models (S24). Warnings for SpectralAverage glazing (S38), EcoRoof, Kiva and collectors (S33).

### 3.4 Leave alone

Polygon clipping / pixel counting shading, `SkyDifSolarShading` (isotropic + horizon patch shading),
solar reflection manager, interior solar distribution, window optical solvers, daylight-factor machinery
and `DayltgSkyLuminance`, view-factor geometry, `HSky/HGround/HAir` formulas, all Earth constants
(1367/1353/1355/93.73, Perez tables, ASHRAE coefficients). Leaving these bit-for-bit is the main thing
that keeps Earth output identical.

## 4. Open questions / risks

- **Q1 Calendar → absolute date.** The ephemeris needs JD per sol. E+ has 12 months of 28-31 days, but a
  Mars year is 668.6 sols. Whatever mapping the time/weather audit picks, S01 and S02 must use the same
  `jdAtSolStart`. During warm-up the first sol is repeated (same JD), which is fine.
- **Q2 Lunar clock.** exobem runs the Moon with UTC crew schedules (`sites.py:118-119`) and an Earth-second
  time step. The brief's planetary hour (106 300 s) makes `HourOfDay` = lunar solar hour, which the solar
  code needs (shading is precomputed for 24 "hours" per day). If an Earth-hour clock were ever used on the
  Moon, the precomputed-shading design breaks. It would then need Timestep shading plus a sun position from
  absolute time. Schedules on lunar hours are a schedule-audit issue.
- **Q3 Outdoor "dry bulb" on the Moon.** After S27/S28, LW no longer reads T_air off-Earth. The `TSurf == TAir`
  guards and window `tout` still read it. It must be finite (never NaN); setting it to the regolith skin
  temperature or a fixed placeholder works.
- **Q4 Mars luminous efficacy and sky luminance shape.** There is no validated value in the dossier. CIE skies
  are an approximation. Daylighting on Mars should stay P2 until data exists.
- **Q5 Mars CO₂ frost and dust storms.** Seasonal frost albedo (~0.6) could reuse the snow modifier. Storm
  τ ≈ 5-9 makes the delta-Eddington diffuse dominant, so the isotropic assumption matters more. Verify against
  Appelbaum & Flood tables (`twostream.appelbaum_net_flux_function`).
- **Q6 Lunar polar sites.** Sun near the horizon all day: the finite disk (handled in the generator), terrain
  masks, and |lat| → 90° azimuth singularity (S07). Lunar declination drift within one lunar day (~0.8°, S10)
  may matter for low-sun polar walls. This would need a per-timestep declination update (code change in
  `DetermineSunUpDown`/`FigureSunCosines` only when Detailed solar integration is on).
- **R1 Consistency.** DNI from the generator and SOLCOS from E+ must use identical sun geometry. Otherwise
  beam is clipped at sunrise/sunset (`SetCurrentWeather` 2236-2240 zeroes radiation when E+ says the sun is
  down). Hence hook 3: the generator calls E+'s own sun routine.
- **R2 Timestep sampling.** E+ evaluates the sun at the timestep end (or mid-hour for 1 ts/h). exobem uses the
  step midpoint. Expect small differences in E+/Python verification, and recommend ≥ 6 timesteps/hour on the Moon.
- **R3 Bit-for-bit Earth.** Every change is guarded by `body != Earth`. Do not "clean up" the duplicated SUN3
  / CalculateDailySolarCoeffs Earth code or the 1367/1353 constants. Changing the enum order of
  `SkyTempModel` would change the eio and `getEnumValue` behaviour, so append new values.
- **R4 Custom spectrum defect (S39).** With fewer than 107 pairs the solar-weighted average picks up a negative
  end step. Ship 107-point AM0/Mars spectra, or fix the loop bound.
- **R5 Upstream CondFD index bug (S30)** affects Earth models using SurfaceProperty:GroundSurfaces with
  CondFD. Fixing it changes Earth results for those (rare) models. Decide whether the fork fixes it
  unconditionally or only off-Earth.
