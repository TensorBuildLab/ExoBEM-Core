# 05 - Windows and fenestration (audit, ExoBEM-Core fork of v26.2.0)

Scope: `WindowManager.cc/.hh`, `WindowManagerExteriorThermal/Optical/Data.cc`, `WindowEquivalentLayer.cc/.hh`,
`WindowComplexManager.cc` + the TARCOG files it drives (`ThermalISO15099Calc.cc`, `ThermalEN673Calc.cc`,
`TARCOGGasses90.cc`, `TarcogShading.cc`), `Material.cc/.hh` gas objects, `DataSurfaces.cc` window helpers, and
`third_party/Windows-CalcEngine` (WCE). `WindowAC` is out of scope. All line numbers are from the fork as read today.

## 1. Summary

- No window code runs in a model without fenestration, so **nothing here is P0**. A single-zone opaque habitat can
  run without touching this area. Everything needed for "a few small multi-pane port windows" is **P1**.
- There are four window thermal solvers. Each one carries its own copy of the Earth constants:
  BuiltIn (`WindowManager`, the default), External (WCE, opt-in through `WindowsCalculationEngine`),
  BSDF/TARCOG (`Construction:ComplexFenestrationState`) and Equivalent Layer (EQL, `Construction:WindowEquivalentLayer`).
  For v1, fix the BuiltIn path and the shared hooks, and stop the other three with an error when the run is
  off-Earth. The exception is BSDF/TARCOG, which is the only route that already models vacuum glazing.
- Exterior convection is not computed in window code. All four solvers take `SurfHConvExt` from `ConvectionCoefficients`.
  Sky long-wave exchange uses the same `SurfAirSkyRadSplit`/`SkyTempKelvin` as opaque surfaces, so it follows the opaque
  fix automatically. **Ground IR is different from opaque surfaces:** windows always use σ·T_outdoor-air⁴ and ignore
  `SurfaceProperty:GroundSurfaces`.
- The interior film and the condensation check read `OutBaroPress`, which is wrong for a pressurized cabin. On the Moon
  this sends h_cin to the 0.1 W/m²K floor. With the WCE solver the same input gives a divide-by-zero (NaN).
- In BuiltIn gas gaps, a fixed pressure of 1e5 Pa is acceptable for sealed IGUs (the fill density is set at
  manufacture). It is wrong for shade gaps and for gaps vented to the outside. Gravity matters for wide gaps: a 25 mm air
  gap at ΔT = 15 K drops from Nu ≈ 1.9 on Earth to Nu ≈ 1.04 on the Moon.
- Solar optics need no code change. The AM1.5 spectrum is only used for spectral-data glazing and can already be
  replaced from the input file (`Site:SolarAndVisibleSpectrum`).
- Overall difficulty: **moderate**. About 25 code sites need changes. Most are a direct swap of the constant, plus one
  helper for gravity, pressure and IR and one input-validation pass.

### Literal inventory (exact counts)

| Constant | src/EnergyPlus (window scope) | Windows-CalcEngine `src/**` (tests excluded) |
|---|---|---|
| Gravity literal | **4** in WindowManager.cc: `9.81` @3788, 3977, 6480; `9.807` @4534. **5** in WindowEquivalentLayer.cc: `9.81` @5960, 6018, 6047, 6122, 6147. Cross-ref: ConvectionCoefficients.cc:2680 `g(9.81)` (ISO 15099 window interior film) | `GRAVITYCONSTANT = 9.807` defined once (Common/src/Constants.hpp:11), **4** physical uses: IGUGapLayer.cpp:84, IGUVentilatedGapLayer.cpp:107, IndoorEnvironment.cpp:131, DeflectionFromCurves.cpp:131. No bare 9.81/9.807 literal. Tests: 0 |
| `Constant::Gravity` (9.807, DataGlobalConstants.hh:589) | **8**: WindowEquivalentLayer.cc:5796, 8094; TarcogShading.cc:799, 1107; ThermalISO15099Calc.cc:2551, 2704; ThermalEN673Calc.cc:415, 484. (The other 2 in src are in ConvectionCoefficients.cc, outside this scope) | n/a |
| Fixed pressure | `1.0e5`: WindowManager.cc:4397, 4564; WindowManagerExteriorThermal.cc:689, 707, 742; TARCOGGasses90.cc:112 (EN673 only) = **6**. `101325`: WindowManager.cc:6479 (nominal), WindowEquivalentLayer.hh:839 (`PAtmSeaLevel`, used **6×** @5952, 6010, 6039, 6114, 6139, 7618), WindowEquivalentLayer.cc:8088 (ratings) = **3 literals**. IDD defaults 101325: `WindowMaterial:Gap` Pressure (idd 6046-6049), `WindowThermalModel:Params` Initial Pressure (idd 9360-9365) | `101325` literal **12×**: Gases/src/GasItem.hpp:12 (`DefaultPressure`, used 4× in Gas.cpp:11,19,25 and GasItem.cpp:87), Tarcog/src/BaseShade.cpp:339, DeflectionFromCurves.hpp:11 (`defaultPressure`, used @41, 89, 90), Environments.hpp:22, 30, IGU.hpp:72, 73, IGUEN673.hpp:31, IndoorEnvironment.hpp:13, Layers.hpp:42, 44, OutdoorEnvironment.hpp:28. `VACUUMPRESSURE = 13.3322` (Constants.hpp:12). Tests: 43 × `101325` |
| `OutBaroPress` read by window code | WindowManager.cc:2561 (dew point); WindowManagerExteriorThermal.cc:813 (indoor), 842 (outdoor); WindowComplexManager.cc:2995 (both sides). Cross-ref ConvectionCoefficients.cc:2697 | n/a (passed in) |
| Other hard-coded air properties | WindowManager.hh:73-80 `AirDens=1.29`, `AirDDensDT`, `AirVis`, `AirDVisDT` (+ unused `AirCon`, `AirDConDT`, `AirPrandtl`, `AirDPrandtlDT`). Uses: AirDens 7× (3762, 3787, 3806, 4095, 4107, 4215, 4228), AirVis 1× (3763). Gap cp `1008.0` 7× (3793, 3807, 3985, 4096, 4108, 4217, 4229). EQL: `287.097` (R_air) 5× (5952…6139); air k/μ/cp fits in SLtoGL/SLtoAMB/GLtoAMB | `BaseShade.cpp:339` builds an air `CGas` at 101325 |

## 2. Findings

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| W01 | WindowManager.cc:4534 | `WindowGasConductance` (Grashof) | g = 9.807 | Gap Gr scales with g. 12 mm air gap: Nu 1.02→1.00 (<3%). 25 mm gap at ΔT 15 K: Nu 1.9→1.04, so U is overestimated by up to ~45% of the gap conductance | `gLocal(state, 9.807)` (helper, §3) | P1 |
| W02 | WindowManager.cc:4397, 4564 | `WindowGasConductance`, `WindowGasPropertiesAtTemp` `pres(1.0e5)` | Every gap is at 1e5 Pa | Correct for sealed IGU gaps (density fixed at manufacture). Wrong for shade gaps (cabin side should be ~70 kPa; exterior side should be 0 or ~600 Pa) and for vented gaps. No way to express a vacuum gap | Add `Real64 pressure = 1.0e5; bool vacuum = false;` to `Window::WindowGap` (WindowManager.hh:415-421) and use them here. Vacuum: con = free-molecular term (or 0), gr = 0 | P1 |
| W03 | Material.hh:100-109, Material.cc:70-86; IDD `WindowMaterial:Gas` keys (idd 5861-5865), `WindowMaterial:GasMixture` (idd 5981-), `WindowMaterial:Gap:EquivalentLayer` (idd 7314-7318) | `GasType`, `gases[10]` table | Only Air/Ar/Kr/Xe in ISO 15099 Table B. A mixture can only use these 4 (Material.cc:1229-1253) | Mars vented gap / CO2 fill / N2 fill is only possible through a single `Custom` gas (Material.cc:1036-1047; MW ≥ 20 is allowed, so CO2 at 44 works). No CO2 in mixtures | Append `CO2` (and `Vacuum`) to the enum, the names and empty table slots 5-6. Append IDD keys at the end so Earth files are unchanged. Suggested CO2 fit (from NIST values 220-350 K, verify before use): k = -5.44e-3 + 7.38e-5·T, μ = 4.3e-7 + 4.85e-8·T, cp = 521.7 + 1.067·T, M = 44.01, γ = 1.30 | P1 |
| W04 | WindowManager.cc:2433-2441 | `CalcWindowHeatBalanceInternalRoutines`: gap between glass and interior/exterior shade | Filled with `GasType::Air` at 1e5 Pa (via W02) | Interior shade: cabin gas at cabin pressure, ρ about 30% lower at 70.3 kPa. Exterior shade on the Moon: the gap is vacuum but is modeled as conducting air (h ≈ k/gap + natural flow). Mars: CO2 at ~600 Pa | Interior: Air coefficients at `zoneAirPressure`. Exterior: Mars gives CO2 at `OutBaroPress`; Moon gives vacuum or a severe input error (W26) | P1 |
| W05 | WindowManager.cc:3762-3763, 3787-3788, 3793, 3806-3807; WindowManager.hh:73-78 | `ExtOrIntShadeNaturalFlow` (stack-driven gap flow) | ρ = 1.29 - 0.004·T °C (air at 1 atm), μ = Earth air, `9.81`, cp 1008 | Gap velocity and heat removal (∝ ρ·g) are too high by ~6× (Moon) and ~2.6× (Mars), even for an interior shade in the cabin. Exterior shade: driven by "outdoor air" `tout` that does not exist on the Moon | Off-Earth: take ρ and μ from `WindowGasPropertiesAtTemp` for the gap (already done in the between-glass routine) and use `gLocal(state, 9.81)`. Earth branch unchanged | P1 (interior shades) |
| W06 | WindowManager.cc:3977 (also 3985); 4095-4108, 4215-4229 | `BetweenGlassShadeNaturalFlow`, `BetweenGlassForcedFlow`, `BetweenGlassShadeForcedFlow` | `9.81`; `AirDens`; cp 1008 | Same as W05 for between-glass blinds and shades and airflow windows | `gLocal`; gas-law ρ off-Earth | P2 |
| W07 | WindowManager.cc:3531, 4075-4077, 4191-4193, 3710-3715 | Airflow windows (`WindowProperty:AirflowControl`), shade-gap inlet | Source/exhaust = outdoor air (`tout`, `OutHumRat`) | Meaningless in vacuum. On Mars it would bring 600 Pa CO2 into the cabin | Error if airflow source or destination = Outdoor and !isEarth; indoor-source airflow may stay | P2 (flag) |
| W08 | WindowManager.cc:2561 | Inside-glass, frame and divider condensation flag | `PsyTdpFnWPb(RoomHumRat, OutBaroPress)` | Moon: P≈0 gives vapour pressure ≈ 0, so the dew point is far below any surface temperature and condensation is never reported (psychrometric warnings are possible). Mars: much too low | Use `zoneAirPressure(state, surf.Zone)` | P1 |
| W09 | WindowManager.cc:2575 | Airflow-gap condensation, outdoor source | `OutDewPointTemp` | No outdoor humidity off-Earth | Unreachable once W07 is enforced. Leave as is | P2 |
| W10 | ConvectionCoefficients.cc:2680, 2697; called inside the window iteration at WindowManager.cc:3363-3375 (TARP default) | `CalcISO15099WindowIntConvCoeff` | g = 9.81; ρ at `OutBaroPress`; ISO 15099 air k and μ | Natural h_cin ∝ P^0.5·g^0.25. With the correct cabin (70.3 kPa) h_cin is 0.53× Earth on the Moon and 0.65× on Mars. With `OutBaroPress` as now: Moon gives ρ = 0, Nu = 0, clamp at `LowHConvLimit` 0.1 (DataHeatBalance.hh:1817); Mars gives ~0.06× Earth | `gLocal(state, 9.81)`; zone air pressure (the function needs a zone or pressure argument; callers at 2780, 3531, 5008). Owned jointly with the convection audit | P1 |
| W11 | WindowManager.cc:2206-2210, 2482-2486, 2616-2620; WindowComplexManager.cc:2826-2831; WindowEquivalentLayer.cc:785-791; DataSurfaces.cc:319-324 (`getOutsideIR`, WCE path) | Exterior IR, 5 copies + 1 reporting split | Sky part: `SurfAirSkyRadSplit`·σT_sky⁴ + (1-split)·σT_out⁴ (same as opaque). **Ground part: ViewFactorGroundIR·σT_out⁴** | Sky follows the opaque fix (split = 1 in vacuum, T_sky = 2.7 K). Ground IR uses outdoor *air* temperature, which does not exist on the Moon; regolith is 100-390 K. Opaque surfaces can use `SurfaceProperty:GroundSurfaces` (ConvectionCoefficients.cc:447-459), but no window file reads `UseSurfPropertyGndSurfTemp` (0 hits) | Factor into one `Window::exteriorIR(state, SurfNum, tout)` helper. Off-Earth: ground term uses the planetary regolith surface temperature (or GroundSurfaces). Gate on `!isEarth` to keep Earth bit-for-bit | P1 |
| W12 | WindowManager.cc:2190, 2216, 2447; WindowComplexManager.cc:2837-2839 (`ibc(1)=2`); WindowManagerExteriorThermal.cc:843 (`HcPrescribed`); EQL `HCOUT` (4438, 4923) | Exterior convection for all 4 solvers | Taken from `SurfHConvExt` (ConvectionCoefficients) | Correct once ConvectionCoefficients returns 0 (vacuum) or low-density Mars values. All solvers accept h_cout = 0: the only division is ThermalISO15099Calc.cc:2380 `/(hcout+hrout)`, and hrout > 0 | No window change. Confirm the convection audit does not floor exterior h for windows | P1 (verify) |
| W13 | WindowManager.cc:2197, 2219, 2474; WindowComplexManager.cc:2816; WindowEquivalentLayer.cc:777; DataSurfaces.cc:290 | Wet glass when raining | `IsRain`, so T_out = wet-bulb | None, as long as the planetary generator keeps `IsRain = false` | None (state it in the generator contract) | - |
| W14 | WindowManagerExteriorThermal.cc:813-815 → WCE IndoorEnvironment.cpp:115-131 | WCE indoor film (`CalculateH`, E+ h_cin ignored) | Room gas = Air at `OutBaroPress`, `GRAVITYCONSTANT` | Moon: P < 13.33 Pa, so WCE switches to "vacuum" properties (μ = 0, ρ = 0; GasItem.cpp:62-80) and Gr divides by μ² = 0, giving NaN/inf. Mars: h_cin ~0.06× | Pass `zoneAirPressure`. Also W18. Or forbid `ExternalWindowsModel` off-Earth in v1 | P1 (if WCE allowed) |
| W15 | WindowManagerExteriorThermal.cc:689, 707, 742 | WCE `getGapLayer`, `getShadeToGlassLayer`, `getComplexGapLayer` `pres = 1e5` | Same as W02/W04 | WCE could do vacuum gaps natively (GasItem.cpp:121-128), but E+ always sends 1e5 Pa | Use `WindowGap.pressure` / `MaterialComplexWindowGap::Pressure` | P2 |
| W16 | WindowManagerExteriorThermal.cc:765 | `getGas` `vacuumCoeff = 1.4` | γ = 1.4 for every gas | Only used in WCE's vacuum branch; wrong γ for Ar/Kr/Xe/CO2 | Pass `gas.specHeatRatio` | P2 |
| W17 | WCE Tarcog/src/BaseShade.cpp:339 | `CIGUShadeLayer::equivalentConductivity` | Air at 101325 Pa | Shade permeability conductance uses Earth air | Take pressure from the adjacent gap | P2 |
| W18 | WCE Common/src/Constants.hpp:11 (+4 uses, see inventory) | `ConstantsData::GRAVITYCONSTANT` | 9.807, `static const` | Every WCE gap, vented gap, indoor film and deflection uses Earth g | Patch third_party: runtime setting (e.g. in the `CGasSettings` singleton, default 9.807); E+ sets it at init when !isEarth. Record in third_party/PATCHES.md | P1 if WCE allowed, else P2 |
| W19 | WindowComplexManager.cc:2995-2997 | `CalcComplexWindowThermal` environment pressures | `presure(1) = presure(nlayer+1) = OutBaroPress` | Indoor side should be cabin pressure. TARCOG recomputes the indoor film (`ibc(2)=0`, 2835) with that pressure in ThermalISO15099Calc.cc:2530-2551, so on the Moon h_cin → 0 | `presure(nlayer+1) = zoneAirPressure(zone)`; outdoor stays `OutBaroPress` | P1 (BSDF route) |
| W20 | ThermalISO15099Calc.cc:2551, 2704; TarcogShading.cc:799, 1107 | TARCOG `filmi`, `filmg`, shading vent flow | `Constant::Gravity` | Earth g in the indoor film, gap Nu and vented-shade flow | `gLocal(state, Constant::Gravity)` (state is already passed in) | P1 if BSDF vacuum glazing is used, else P2 |
| W21 | ThermalEN673Calc.cc:415, 484; TARCOGGasses90.cc:112 | EN 673 standard in `WindowThermalModel:Params` | g and 1e5 Pa by definition (rating standard) | Not a physical model off-Earth | Leave the code alone; error if EN673 is selected and !isEarth | P2 (flag) |
| W22 | TARCOG deflection (`TemperatureAndPressureInput`, WindowComplexManager.cc:2641-2644, 2780, 2995) | Pane deflection | Same `Pa` on both sides; fabrication P_ini default 101325 | A habitat window holds ~70 kPa ΔP and the outside can be 0 Pa. The model gives nonsense or fails | Error off-Earth (structural design is out of scope) | P2 (flag) |
| W23 | WindowComplexManager.cc:2872-2893 | TARCOG indoor/outdoor "gas" | Pure air both sides | Indoor: acceptable once pressure is fixed (W19). Outdoor: only matters for exterior or vented shades | None in v1 (exterior shades blocked by W26) | P2 |
| W24 | WindowEquivalentLayer.hh:839 + 6 uses; .cc:5960, 6018, 6047, 6122, 6147 (`9.81`), 5796 (`Constant::Gravity`), 5884-5901 `HIC_ASHRAE` (used @6023, 6127), `287.097` 5×; IDD gap type `VentedOutdoor` (idd 7330) | EQL gap density, shade/glass-to-ambient correlations | 101325 Pa, Earth g, Earth air fits, dimensional 1.46·(ΔT/L)^¼ | Every EQL convection term is Earth-only | v1: severe error for `Construction:WindowEquivalentLayer` when !isEarth. Retrofit later (pressure per side, `gLocal`) | P2 (flag) |
| W25 | WindowEquivalentLayer.cc:362-364, 5791-5792 | EQL gas transfer (`FG.AVISC = gas.cp.c0`, …; `FRA` uses `BCP·TM²`, `BVISC·TM²`) | **Pre-existing Earth bug**: viscosity filled with cp coefficients; wrong quadratic terms | Gap Ra is underestimated by ~10², so EQL gaps already run as pure conduction (Nu ≈ 1) and gravity barely matters there | Do **not** fix in this fork (Earth bit-for-bit). Report upstream | info |
| W26 | (new) input check, e.g. in `InitGlassOpticalCalculations` (WindowManager.cc:154) or HeatBalanceManager input pass | Off-Earth fenestration validation | n/a | Without it, unsupported features run silently with Earth physics | Severe errors for: exterior shade/blind/screen when there is no atmosphere; airflow windows with outdoor source/exhaust; EQL; `ExternalWindowsModel` (until W14/W18 are done); EN673; deflection. Warnings for: SimpleGlazingSystem and SpectralAverage glass (Earth-rated), spectral glazing without a planetary spectrum | P1 |
| W27 | WindowManager.cc:5771-6530 (`CalcNominalWindowCond`, `WindowTempsForNominalCond` incl. 6479-6480), 4826-4828 (asp 1.524 m); WindowComplexManager.cc:3058-3077; WindowEquivalentLayer.cc:7992-8101 (8088, 8094); WCE `getOutdoorNfrc`/`getIndoorNfrc` (WindowManagerExteriorThermal.cc:898, 918) | NFRC/ISO rating U-factor and SHGC (EIO, tabular) | Earth rating conditions (h_out 26/15, 255.15 K, 101325 Pa, 9.81) | None. These are ratings, not simulation | **Leave alone.** Label in docs as "Earth NFRC rating" | - |
| W28 | Material.cc:2429-2472 (`WindowMaterial:SimpleGlazingSystem`) and its conversion in WindowManager | U/SHGC → equivalent layer | Converted with Earth NFRC films; U already contains Earth gap convection | A small bias on gap convection. Layer conductance itself is fine | Keep; warning off-Earth (W26). Recommend layer-by-layer input for habitat windows | P2 |
| W29 | WindowManager.hh:427-449 (`wle`, `e`: ISO 9845-1 / ASTM E892 AM1.5 global on 37° tilt, 107 points 0.300-2.537 µm); 451-470 (`wlt3`, `y30`: CIE 1931 photopic) | Solar and visible spectral weighting | Earth surface spectrum | Only used for `Spectral`/`SpectralAndAngle` glazing (`solarSpectrumAverage` 1981, `visibleSpectrumAverage` 1995) and the WCE optical path (WindowManagerExteriorData.cc:115-129). Moon is AM0 (ASTM E490): more UV, a few % of energy outside 0.3-2.5 µm. Mars is dust-reddened, UV-cut and changes with τ | **No code change**: `Site:SolarAndVisibleSpectrum` + `Site:SpectrumData` already override both (WindowManager.cc:8248-8405, max 107 pairs). Ship two datasets (Moon AM0, Mars τ≈0.5 surface). Keep the photopic curve (human eye) | P2 (P1 if spectral glazing is used) |
| W30 | Glass with `SpectralAverage` data, `Construction:WindowDataFile`, BSDF matrices | Pre-integrated optical properties | Integrated by the manufacturer or WINDOW over AM1.5 | ~1-3% bias in τ_sol off-Earth; cannot be corrected in-engine | Document; warning (W26) | P2 |
| W31 | Material.cc:500-504, 858 (`GlassTransDirtFactor`) | Soiling | Static dirt factor | Mars dust deposition is time-varying; only a constant factor is possible | Document; future schedule-driven factor | P2 |
| W32 | WindowManager.cc:5549-5770 `CalcWinFrameAndDividerTemps` | Frame/divider and edge-of-glass | Takes films from the window solver; edge-of-glass ratio is Earth-rated user input | Follows the film fixes; edge ratio stays Earth-rated | None | P2 |

## 3. Specific questions answered

**Gas-gap heat transfer (BuiltIn model).** Properties come from quadratic fits in T (Material.cc:77-80, ISO 15099 Table
B). Mixtures use ISO 15099 eq. 56-68 (WindowManager.cc:4440-4525), which is general and needs no change. Density uses
the ideal-gas law at a fixed 1e5 Pa (not 101325, and not `OutBaroPress`), with R = 8314.51. Gravity: 9.807 in
`WindowGasConductance`, 9.81 in the shade-flow routines. Nusselt: `NusseltNumber` (4774-4879, ISO 15099 eq. 42-53,
tilt-aware). In the continuum regime, conductivity does not depend on pressure. Pressure and g enter only through
Gr ∝ g·ρ². Mean free path for CO2 at 600 Pa is ~10 µm, so a Mars gap vented to the outside is still continuum
conduction (k ≈ 0.012 W/mK at 220 K) with almost no convection. A Moon vented gap is true vacuum (radiation only).
- *CO2 fill*: possible today as a single `WindowMaterial:Gas` with Type = Custom (BuiltIn, BSDF, WCE and EQL all accept
  it). Not possible in `WindowMaterial:GasMixture`.
- *Vacuum glazing / evacuated gap*: **BuiltIn: no.** The gas is always continuum. A crude workaround exists: a Custom
  gas with k ≈ 1e-6 and a huge viscosity, which gives Nu = 1 and h ≈ 0 while the pane-to-pane IR stays. **EQL: no.**
  **WCE via E+: no** (E+ hard-codes 1e5 Pa), although the WCE library itself switches to free-molecular conduction
  below 13.33 Pa. **BSDF/TARCOG: yes.** `WindowMaterial:Gap` Pressure < `WindowThermalModel:Params` Vacuum Pressure
  Limit (default 13.238 Pa) calls `GassesLow` (TARCOGGasses90.cc:250-273, free-molecular). `WindowGap:SupportPillar`
  is used by `filmPillar` (ThermalISO15099Calc.cc:2728-). It needs BSDF input, and its indoor film has the W19/W20
  issues.

**Films.** The exterior film is shared with opaque surfaces (W12). Sky LW uses the same split as opaque, but ground LW
does not (W11). The interior film uses ISO 15099 with `OutBaroPress` and g = 9.81, through
`Convect::CalcISO15099WindowIntConvCoeff`, which is re-called inside the window iteration (W10). TARCOG and WCE compute
their own interior film with the same Earth inputs (W19, W14). EQL takes `SurfHConvInt` from ConvectionCoefficients.

**Shades, blinds, screens.** Interior shade gaps use Air at 1e5 Pa, ρ = 1.29 and g = 9.81 (W04, W05). This must become
cabin gas at cabin pressure. Exterior devices are modeled as an air gap ventilated by outdoor air. That is unusable on
the Moon and is wrong on Mars (W04, W05, W26). Between-glass devices sit in sealed gas, so only g needs to change
(W06).

**Condensation/frost.** The only checks are WindowManager.cc:2557-2600 (inside glass, frame, divider: room dew point at
`OutBaroPress`, W08) and the outdoor-airflow gap check (W09). EQL and TARCOG have no condensation check. No frost model
exists.

## 4. Habitat port window: what to support

Reference design (ISS-Cupola-like): an outer debris pane, a gap vented to the outside, two redundant pressure panes with
a sealed dry-N2/air gap, an inner scratch pane, and a cabin-side gap open to cabin air.

**Supported in v1 (BuiltIn model, P1 work):**
- `Construction` made of `WindowMaterial:Glazing` (SpectralAverage, or Spectral plus a planetary spectrum) and
  `WindowMaterial:Gas` layers. Up to 5 glass layers in BuiltIn (`maxGlassLayers = 5`, WindowManager.hh:85).
- Sealed gaps: Air/Ar/Kr/Xe/Custom/CO2 at their fabrication fill (1e5 Pa default), with planetary g (W01).
- Vented-to-outside gap: new `Vacuum` gas type (Moon) or CO2 at `OutBaroPress` (Mars). This needs W02/W03 plus an
  optional appended field "Gap Vent Type {Sealed, VentedOutdoor}" on `WindowMaterial:Gas`. The gas and pressure are
  re-set each timestep from the planet atmosphere.
- Interior shade or blind (cabin gas, cabin P, planetary g; W04/W05).
- Frames/dividers with user conductance; correct films; condensation at cabin pressure.

**Unsupported off-Earth (severe error unless noted):** exterior shades/blinds/screens on airless bodies (Mars: also
blocked in v1); airflow windows with an outdoor source or exhaust; `Construction:WindowEquivalentLayer`;
`ExternalWindowsModel` (until W14/W18 are done); EN673; TARCOG deflection. Warnings only: `SimpleGlazingSystem`,
Earth-integrated optical data, and spectral glazing without a planetary spectrum. BSDF/TARCOG stays allowed *after*
W19/W20, as the route for true vacuum glazing with pillars.

## 5. Recommended implementation

1. **Consume the planet globals** from the `Site:PlanetaryBody` work: `state.dataEnvrn->planet.isEarth`, `.gravity`,
   `.atmosphere` (None/CO2/Earth), the regolith surface temperature, and a cabin accessor
   `Real64 zoneAirPressure(EnergyPlusData const&, int zoneNum)` that returns `OutBaroPress` on Earth.
2. **Helper header** (e.g. `PlanetaryPhysics.hh`):
   `inline Real64 gLocal(EnergyPlusData const &s, Real64 earthLiteral) { return s.dataEnvrn->planet.isEarth ? earthLiteral : s.dataEnvrn->planet.gravity; }`.
   It returns the *original* literal on Earth, so the existing 9.81 vs 9.807 mix stays bit-for-bit. Apply it at
   WindowManager.cc:3788, 3977, 4534; ThermalISO15099Calc.cc:2551, 2704; TarcogShading.cc:799, 1107; and
   ConvectionCoefficients.cc:2680 (together with the convection audit). Do **not** touch 6480, 8094 or the EN673 sites
   (they are ratings).
3. **WindowGap pressure / vacuum** (WindowManager.hh:415): add `pressure` (default 1.0e5) and `vacuum`. In
   `WindowGasConductance` and `WindowGasPropertiesAtTemp`, replace `pres` with `wm->gaps[iGap].pressure`. If
   `vacuum`, return con = 0 (optionally the free-molecular `B·P` from `GassesLow`), gr = 0, dens = 0, and skip
   `NusseltNumber` (nu = 1). Fill these fields in the gap-setup loop (2423-2441) from the material and, off-Earth, from
   the cabin or planet for shade gaps and vented gaps.
4. **Shade natural flow** (`ExtOrIntShadeNaturalFlow`): off-Earth branch only. Use ρ and μ from
   `WindowGasPropertiesAtTemp(state, T, gap, ...)` instead of `AirDens`/`AirVis`, `RhoTRef` from ρ(273.15 K) as in the
   between-glass routine (3973-3976), and `gLocal`. Leave cp 1008 (≈1% for N2/O2 cabin gas).
5. **Pressure hooks**: WindowManager.cc:2561, WindowManagerExteriorThermal.cc:813 and WindowComplexManager.cc:2997
   (indoor `presure(nlayer+1)`) use `zoneAirPressure(state, surf.Zone)`. On Earth this returns `OutBaroPress`, so
   nothing changes.
6. **Exterior IR helper**: replace the 5 copies (W11) with `Window::exteriorIR(state, SurfNum, tout)`. In the `!isEarth`
   branch, ground uses `planet.regolithSurfaceTempK` (or `GroundSurfsProperty` when present) and the split
   `(1-split)·σT_out⁴` term is used only when the atmosphere is not None. Keep the reporting split at 2616-2620
   consistent.
7. **Material/IDD**: append `CO2` and `Vacuum` to `GasType`, `gasTypeNames(UC)`, the `gases` table (slots 5-6) and the
   IDD keys (append only). `Vacuum` gets zero coefficients but must skip the c0 > 0 checks (Material.cc:1056-1067) and
   the `NominalR` division (1073, 1177, 1258); for NominalR use radiation only, or set NominalR to a large value.
   Optional new last field on `WindowMaterial:Gas`: "Gap Vent Type" (Sealed default).
8. **Validation pass** (W26) is called once after window constructions are read. This is the cheapest protection and
   should land first.
9. **WCE** (only if wanted in v1): patch `GRAVITYCONSTANT` into a runtime setting, pass gap and indoor pressures and the
   real γ. Otherwise block `ExternalWindowsModel` off-Earth.
10. **Leave alone**: all NFRC/ISO rating code (W27), the CIE photopic curve, the ISO 15099 mixture equations, all
    optical/angular code, the EQL internals (blocked, W24/W25), and the custom-spectrum reader (already sufficient).
11. **Tests**: (a) Earth regression is bit-identical, including a file with `WindowsCalculationEngine` and one with
    `Construction:ComplexFenestrationState`. (b) Unit test of `WindowGasConductance` with g = 1.625 and a 25 mm air gap
    against a hand-calculated Nu. (c) Moon single-zone with a 3-pane port window (vacuum outer gap): check h_cin ≈ 0.53×
    Earth, a stable inside-glass temperature, and no NaN. (d) Mars: CO2 vented gap, conduction-only Nu ≈ 1.

## 6. Open questions / risks

- **Sealed-gap pressure:** should a sealed IGU gap's pressure follow its temperature (constant density)? Holding 1e5 Pa
  is what Earth does and is fine for heat transfer. Leave it.
- **Ground IR on Earth:** making windows honour `SurfaceProperty:GroundSurfaces` would fix an Earth inconsistency but
  would break bit-for-bit for files that use that object. Keep the change gated on `!isEarth` unless the project
  decides otherwise.
- **Exterior h floor:** if ConvectionCoefficients floors exterior h at `LowHConvLimit` or similar, vacuum windows will
  lose heat by "convection". This must be confirmed with the convection audit.
- **Vacuum gaps in BuiltIn:** with h_gap = 0 the layer heat balance becomes radiation-only. Check that the LU solve and
  the iteration (`SolveForWindowTemperatures`) still converge. Low-e coatings then give very small conductances, which
  is physically right but untested.
- **Spectrum override:** it is limited to 107 pairs and is global, so it cannot follow Mars dust τ over time. Glazing
  spectral data usually covers only 0.3-2.5 µm, so AM0 energy outside that band depends on how `Interpolate`
  (WindowManager.cc:2025) clamps at the ends. Verify this before shipping AM0.
- **Pre-existing EQL bug (W25):** it shows that EQL gap convection is not validated on Earth either. That is another
  reason to block EQL off-Earth rather than port it.
- **Cabin gas:** using Air coefficients for a 26.5% O2 cabin mix is a ~1% property error. Pressure is the
  first-order term.
- **Structure:** habitat windows are thick fused-silica pressure panes. Thermal input is fine (conductivity, thickness),
  but structural loading (70 kPa ΔP) is out of scope, hence deflection is blocked (W22).
- **WCE patch:** this is a third_party patch to a `static const` in a header. It needs a PATCHES.md entry, and the WCE
  unit tests (275 test files, 43 uses of 101325) must still pass at the default.
