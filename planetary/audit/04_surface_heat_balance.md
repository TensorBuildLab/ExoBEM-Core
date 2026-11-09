# Audit 04 – Surface heat balance, conduction, convection, ground contact, envelope moisture

Scope: `HeatBalanceSurfaceManager.cc` (outside/inside face balances), `ConvectionCoefficients.cc/.hh` (namespace `Convect`),
`Construction.cc` (CTF), `HeatBalFiniteDiffManager.cc` (CondFD), ground models (`Site:GroundTemperature:*`, Kiva,
GroundDomain, F/C-factor), `MoistureBalanceEMPDManager.cc`, `HeatBalanceHAMTManager.cc`, `EcoRoofManager.cc`.
All line numbers are from the `planetary` branch (v26.2.0, unmodified).

## 1. Summary

The surface heat balance itself (CTF/CondFD conduction, inside heat balance iteration, interior LW exchange) is generic
physics and can stay. What is Earth-bound is the **outside boundary**: (a) every exterior convection correlation encodes
Earth air at 1 atm and 1 g, and none of them is zero in vacuum; (b) the exterior long-wave model sends part of the sky view and
the whole ground view to the **outdoor air temperature**; (c) the LW coefficients are secant ("h·ΔT") coefficients
evaluated at the **previous timestep's** surface temperature, with no iteration. That is accurate on Earth because convection
damps it. In vacuum, on a low-mass skin, it can go unstable. (d) The CTF generator works internally in **hours**, using
`TimeStepZone`. With a planetary hour this silently computes CTFs for the wrong physical timestep. It also rejects any CTF
timestep >= 7 h. (e) CondFD clamps every node at -100 °C (lunar night surfaces reach ≈ -175 °C). It also has an integer
sub-step `Delt` that cannot represent planetary seconds. Interior convection (TARP) overestimates cabin natural convection by
about 2.3× on the Moon (70 kPa, 1.62 m/s²). Ground contact can be modelled cleanly as the Python reference does: put the
regolith inside the floor construction and use a Dirichlet deep-ground temperature (`Ground` BC). Kiva, GroundDomain, F/C-factor,
HAMT and EcoRoof are Earth-specific and should be fenced off. Overall difficulty: **moderate**. The P0 changes sit in about
six functions and can all be gated on `planet.active`, so Earth stays bit-for-bit.

## 2. Findings

Legend: HBSM = HeatBalanceSurfaceManager.cc, CC = ConvectionCoefficients.cc, CCh = ConvectionCoefficients.hh,
FD = HeatBalFiniteDiffManager.cc, CON = Construction.cc. "planet.*" = the planned `Site:PlanetaryBody` state.

### 2.1 Outside face: boundary condition branches, rain, LW radiation

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| S01 | CC:480-648 (switch), 566, 593-595, 627-635; HBSM:7747, 7857, 7930 | `InitExtConvCoeff` all algorithms | Some air is always present: TARP/DOE-2/MoWiTT natural term = f(\|Ts-Ta\|) and is never 0 | In vacuum the Walton natural term alone gives ≈1.31·200^(1/3) ≈ 7.7 W/m²K for ΔT = 200 K. That is a spurious heat path larger than MLI's conductance. | At the top of `InitExtConvCoeff`: `if (planet.vacuum) {HExt = 0; HAir = 0; set Kiva lambdas to KIVA_CONST_CONV(0); goto LW;}`. A user value cannot do it, because input is limited to ≥ `LowHConvLimit` (CC:1082, 1217, 1351; minimum > 0 in IDD). | **P0** |
| S02 | CC:487-498, 1817-1821; 661, 669 | `CalcASHRAESimpExtConvCoeff` (SimpleCombined) | Combined conv + LW film for Earth: D = 8.23-12.49 W/m²K at zero wind; HSky = HGround = HAir = 0 | Sky temperature is ignored and radiation is lumped at Earth ambient. Meaningless on the Moon or Mars. | Fatal off-Earth ("SimpleCombined not valid with Site:PlanetaryBody") | **P0** |
| S03 | HBSM:7759-7767, 8021-8023; FD:1627-1631, 2774 | rain branch (`IsRain`) | Wetted surface: HConvExt = 1000 W/m²K, TempExt = wet bulb; CondFD outer node pinned to wet-bulb | Any spurious `IsRain` (e.g. a planetary weather file with precipitation columns) would pin surfaces to a wet-bulb that does not exist | Environment must force `IsRain = false` off-Earth. Add an assert/guard in `CalcHeatBalanceOutsideSurf` (6 uses: HBSM 7759, 8021, 8717, 9422; FD 1627, 2774) | **P0** |
| S04 | SurfaceGeometry.cc:329; used CC:665, 677; DataSurfaces.cc:321-325; WindowEquivalentLayer.cc:789; WindowComplexManager.cc:2829 | `SurfAirSkyRadSplit = sqrt(0.5(1+cosTilt))` | Earth atmosphere: the near-horizon part (1-β) of the sky view radiates at air temperature | Vertical wall: 29% of its sky view would exchange with "air" (undefined in vacuum, ≈210 K on Mars) instead of 2.7 K space. On Mars the downwelling IR is already in T_sky. | Set the split to 1.0 when `planet.active && !planet.skyIncludesAir` (Python: `sky_includes_air=False`) | **P0** |
| S05 | CC:447 (`TGround = TAir`), CC:669-674; HBSM:9824 (`TGround = OutDryBulbTemp`); FD:1702-1707 (`Tgnd = TempOutsideAirFD`); DataSurfaces.cc:324-325 (windows) | ground LW temperature | Ground surface ≈ outdoor air temperature | Moon: the ground is a 390 K regolith at noon and ≈95 K at night, with no air. Mars: regolith differs from air by ±30-60 K. Ground-view LW would be wrong or undefined. Also the guard at CC:669 (`TSurf == TAir → HGround = 0`) tests the air, not the ground. | Use a new global `state.dataEnvrn->GroundSurfTempC` (planetary regolith surface T from the environment generator) when `planet.active`. Keep the existing per-surface `SurfaceProperty:GroundSurfaces` override (CC:457-460, HBSM:9837). Separate the HGround guard from HAir. | **P0** |
| S06 | CC:450-460 vs HBSM:9827-9839 | `SurroundingSurfaces.groundTempSched` | — (latent inconsistency) | `InitExtConvCoeff` builds HGround with TAir, but `CalcOutsideSurfTemp` multiplies it by the *scheduled* ground T, so the secant coefficient and the temperature disagree. This matters if a user tries the LocalEnvironment workaround. | Use the same TGround in both places (planet branch only, or as an upstream fix) | P1 |
| S07 | CC:661-679; HBSM:7747 (`TempExt = SurfOutsideTempHist(1)`), 9879-10016 | `HSky/HGround/HAir/HSrdSurf` secant coefficients, `CalcOutsideSurfTemp` | h = εσF(Ts²+Tk²)(Ts+Tk). This is exact at the *lagged* Ts (previous timestep). TH11 is solved once per timestep with no re-evaluation. | 3 K sky / 390 K regolith is **not** a problem in itself: the secant form is exact at T0 for any ΔT, and there is no singularity (Tsky^4 ≈ 0). The problem is the **lag**. Applied flux / true flux = (T0/T1)³ (with Tsky → 0): -7% for 380→390 K, +73% for a 300→250 K step. For a skin whose outside conductance K_o (≈ CTFOutside[0]) plus convection is small, the cross-timestep map has gain λ ≈ -3h_s/(h_s+h_c+K_o) with h_s = εσF·T³ ≈ 2.9 W/m²K at 390 K. With h_c = 0 (vacuum) and an MLI/beta-cloth skin (K_o ≈ 0.8 W/m²K at Δt = 1772 s), λ ≈ -2.4: a growing period-2 oscillation (limit cycle). On Earth h_c ≥ 3-20 W/m²K keeps \|λ\| < 1. | Off-Earth only: use the **tangent (Newton) form** written in the existing h·(T_eff − T) shape: h_t = 4εσF T0³, T_eff = (T_k⁴ + 3T0⁴)/(4T0³). Then iterate 3-5 times inside `CalcOutsideSurfTemp`, re-evaluating at the new TH11 (cheap and local). Earth keeps the secant form (bit-for-bit). After convergence the error is 0; without iteration it is second order (≈6εσT0²ΔT² ≈ 5 W/m² for ΔT = 10 K at 390 K). Python reference: simulation.py "Newton-linearised about To_g" with a fixed-point loop. | **P0** |
| S08 | FD:1715-1727, 1745-1746, 1815-1824 | CondFD `ExteriorBCEqns` uses HSkyFD/HGrndFD/HAirFD frozen for the whole zone step | Same lagged secant coefficients, held for all `J` sub-steps (≤200 s) of a zone step | Same instability/lag as S07 for regolith and MLI surfaces modelled with CondFD | Off-Earth: recompute the tangent h_t, T_eff from the current `TDT_i` in each Gauss-Seidel pass (`ExteriorBCEqns`, both schemes and the R-layer branch) | **P0** |
| S09 | HBSM:7392-7997 (13 calls to `PsyRhoAirFnPbTdbW(OutBaroPress,…)` and `PsyWFnTdbRhPb(...,OutBaroPress)`), 7826, 7843 | CondFD/HAMT moisture boundary blocks in every BC branch | OutBaroPress ≈ 101 kPa, outdoor humidity exists | In vacuum ρ_air = 0 and ρ_v = 0, so `HMassConvExtFD = 0/0` = NaN (dry ExternalEnvironment branch, HConvExt = 0). This traps under `DEBUG_ARITHM_*` (api/EnergyPlusPgm.cc:252, 266). `PsyPsatFnTemp` also warns below -100 °C. CondFD never uses the value (FD:517 sets it to 0); only HAMT does. | Off-Earth: skip these blocks unless the surface is HAMT (HAMT is fenced off anyway). Set `HMassConvExtFD = 0`. Keep `TempOutsideAirFD`, `HSkyFD`, `HGrndFD`, `HAirFD` and `HSurrFD` assignments. | **P0** (if CondFD is used) |
| S10 | HBSM:7378-7441, 7442-7502; WeatherManager.cc:2088-2092; GroundTemperatureModeling/Site*GroundTemperatures.cc:164-177 | `Ground` / `GroundFCfactorMethod` BC = Dirichlet `GroundTemp[BuildingSurface/FCFactorMethod]` | 12 monthly values (default 18 °C if the object is absent), indexed by `Month`; `secPerMonth = NumDaysInYear·86400/12` | Floors would sit on 18 °C instead of a lunar ≈250 K / Mars ≈210 K deep regolith. The month index follows whatever planetary calendar is chosen. | Off-Earth: overwrite `GroundTemp[BuildingSurface]` with `planet.deepGroundTemp` (a constant, or a schedule from the regolith model). If it is missing, give a fatal error instead of the 18 °C default. The Dirichlet BC itself is the right model (same as Python `ground: Dirichlet T_deep`). | **P0** |
| S11 | HBSM:7503-7576, 7520 | `OtherSideCoefNoCalcExt` | Sinusoid `sin(2π CurrentTime/SinusoidPeriod)`, both in (planetary) hours | Works off-Earth (generic Robin/Dirichlet). The period is interpreted in planetary hours (index time). | Leave as is. Document that the period is in planetary hours. OSC with `ConstTemp = T_deep` and film = 1/R_regolith is a valid fallback ground BC. | P2 |
| S12 | HBSM:7577-7652, 7590 | `OtherSideCoefCalcExt` | HSky/HGrd/HAir zeroed (HBSM:7368-7373), single film coefficient | Generic, OK in vacuum | Leave | — |
| S13 | HBSM:7653-7722, 9903-9922; CalcExteriorVentedCavity HBSM:10060-10145 | `OtherSideCondModeledExt` (OSCM) | TConv/HConv/TRad/HRad, EMS-actuatable | Generic. This is the cleanest hook for coupling an external regolith or radiator model through EMS/PythonPlugin. The vented-cavity model behind it uses outdoor air density (HBSM:10084-10086) and is meaningless in vacuum. | Keep OSCM. Fatal for `SurfaceProperty:ExteriorNaturalVentedCavity` when `planet.vacuum`. | P2 |
| S14 | HBSM:7729-7732; EcoRoofManager.cc:122 (g = 9.81), 188, 216-217, 268 (`Pa = StdBaroPress`), 280-378, 854 | `CalcEcoRoof` | Vegetation, evapotranspiration, 1 atm, Earth gravity, `TimeStepZoneSec = MinutesInTimeStep·60` | Meaningless off-Earth | Fatal: "Material:RoofVegetation unsupported off-Earth" | P2 |
| S15 | HBSM:2661-2693, 7739-7741, 9986-10016; CC:563-565, 631-633 | exterior movable insulation (`SurfaceControl:MovableInsulation`) | LW/convection coefficients are evaluated at the *wall* temperature under the insulation, not at the insulation's outer face | In vacuum (radiation only) with MLI as movable insulation (R ≈ 15), the outer face (e.g. 390 K) differs from the wall (≈290 K). The secant then underestimates emission by (290/390)³ ≈ 0.41, so the outer face runs far too hot. | Off-Earth: solve the massless insulation face with its own tangent LW iteration (outer-face temperature T_mi = (q + Σh_k T_k + H_mi·T_wall)/(Σh_k + H_mi), iterated). Otherwise warn that movable insulation is approximate. | P1 |
| S16 | HBSM:9823 | `TSky = SkyTemp` (°C) | — | 2.7 K = -270.45 °C works numerically (TSurf == TSky guard CC:661). No Psy calls on TSky. | Leave | — |
| S17 | DataEnvironment.cc:100-114, 187-188 | `OutDryBulbTempAt` (fatal below -100 °C), `WindSpeedAt` (power law, `SiteWindExp` 0.22, BL 370 m, met-station coefficient 1.5863 for 10 m) | Earth terrain classes, standard lapse rate × EarthRadius | Mars polar and high-latitude nights fall below -100 °C and give a fatal error. In vacuum, `SurfOutDryBulbTemp` needs a finite placeholder. Mars wind sensors are ~1-2 m high. (Cross-ref: environment agent.) | Planet: skip the -100 °C fatal. Set the gradient to 0 and use a placeholder T_air in vacuum. Mars: give the wind sensor height and exponent in `Site:PlanetaryBody`. | P1 |

### 2.2 Convection correlations (`Convect` namespace)

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| C01 | CCh:409, 433, 455; used CC:1902-1948 (`CalcASHRAETARPNatural`), 566, 622, 635, 6087 | `CalcASHRAEVerticalWall` 1.31·ΔT^(1/3); `CalcWaltonUnstable…` 9.482·ΔT^(1/3)/(7.238-\|cosθ\|); `CalcWaltonStable…` 1.810·ΔT^(1/3)/(1.382+\|cosθ\|) | Turbulent natural convection h = C·k(gβΔT/να)^(1/3) with air properties at ≈20 °C, 101.3 kPa, g = 9.81 baked into C | Scale factor h/h_Earth = (k/k0)[(g/g0)(T0/T)(ν0α0)/(να)]^(1/3) (Python `tarp_scale_factor`). Mars exterior (CO2, 600 Pa, 210 K, 3.71 m/s²): ≈0.025, i.e. TARP is ~40× too high. Lunar cabin (70.3 kPa, 1.62 m/s²): ≈0.43 (2.3× too high). Mars cabin (3.71 m/s²): ≈0.57. Vacuum: should be 0. | New physical algorithm (§3.2). Optionally a "ScaledTARP" mode multiplying by the factor above, for continuity with Earth validation. | **P0** (interior on Moon/Mars, exterior on Mars) |
| C02 | CC:5943-5990 (`2.537·Rf·sqrt(P·V/A)`, leeward ×0.5), 682-695, 550-559 | Sparrow forced term (TARP) | Air at 1 atm: h ∝ k·(V/ν)^0.5 | Mars at 600 Pa: ν(CO2, 210 K) ≈ 7·10⁻⁴ m²/s vs 1.5·10⁻⁵, so h is ≈0.06× Earth. TARP overestimates by ~17×. | Physical flat-plate forced term (§3.2) | **P0** (Mars) |
| C03 | CC:6025-6043 (0.84, 3.26 V^0.89, 3.55 V^0.617), 6085-6134 | MoWiTT, DOE-2 (default outside algorithm, IDD `\default DOE-2`) | Field-measured fits for Earth air | Same as C01/C02; no physical basis to rescale | Off-Earth: fatal, or auto-switch to the physical algorithm with a warning | **P0** (Mars) |
| C04 | CC:641-643, 3586-3933 (`EvaluateExtHcModels`: ASHRAE, Walton, Alamdari-Hammond, Fohanno-Polidori, Sparrow, MoWiTT, DOE-2, Jurges, McAdams, Mitchell, ClearRoof, Blocken, Emmel) | Adaptive exterior | All Earth-air correlations. Wind at 10 m (Emmel/Blocken). | Not rescalable | Fatal off-Earth (or map every class to the physical model) | P1 |
| C05 | CC:6343-6382 (`CalcClearRoof`: g = 9.81, ν = 15.89e-6, k = 0.0263, Pr = 0.71, ρ from OutBaroPress) | ClearRoof | Fixed air properties at 300 K | Wrong gas; ρ = 0 in vacuum | Unsupported off-Earth | P2 |
| C06 | CC:6438-6573 (`CalcASTMC1340ConvCoeff`: ρ = 22.0493/T·16 ≈ 352.8/T kg/m³, i.e. 1 atm; air k, μ, cp fits; `Constant::Gravity`) | ASTM C1340 | Physically structured Ra/Re Nusselt model, but with hard-wired 1 atm air | Wrong density at a 70 kPa cabin | Good template: replace its property block with the gas-property API to make the new algorithm (§3.2) | P1 |
| C07 | CC:142-392 (`InitIntConvCoeff`), 323-342, 1824-1881 (ASHRAE simple 3.076/4.040/0.948/3.870/2.281 W/m²K) | interior TARP (default) and ASHRAESimple | Earth cabin air, 1 g | Lunar cabin natural convection overestimated ≈2.3×. Interior film resistance is a large share of a well-insulated habitat's U-value, and it sets the radiant/convective split. | Add `HcInt::PlanetaryPhysical` (and/or a scaled TARP) and make it the default when `planet.active`. Kiva lambdas CC:1891-1896, 1954-1958 too. | **P0** |
| C08 | CC:2045-2055, 2113-2114, 2147-2232, 4926-5016 | CeilingDiffuser (Fisher-Pedersen) | ACH-based Earth fits; ACH uses `Constant::rSecsInHour`; ρ from `OutBaroPress` | ACH must stay per **3600 s** (physical unit of the correlation), so do NOT switch it to the planetary hour. ρ must be the cabin pressure, not outdoor (0 Pa on the Moon gives ρ = 0 and a division by zero at CC:2115). | Use cabin pressure for ρ. Keep 3600 for ACH (also CC:2276, 4758). Warn: correlation is Earth-1 g. | P1 |
| C09 | CC:2337, 2680, 4027, 5729, 6353 (5× `constexpr g = 9.81`), 6458 (`Constant::Gravity`); air constants CC:4028, 5730-5732, 6354-6356 | Trombe wall `CalcNusselt`, ISO 15099 window interior, adaptive interior classification (GrH, Re), Fohanno-Polidori, ClearRoof, ASTM C1340 | g = 9.81, ν = 15.89e-6, k = 0.0263 | Wrong gravity and gas | Replace with `planet.gravity` and gas API where kept; the rest is P2/unsupported | P1 |
| C10 | CC:2268, 2700, 4270, 4756 | ISO 15099 window h_in, Trombe ACH, adaptive interior Re, user-curve ACH | `PsyRhoAirFnPbTdbW(OutBaroPress, …)` used for **indoor** air | Outdoor pressure ≠ cabin pressure. Vacuum gives ρ = 0, so Re = 0 and divisions by zero (CC:4274). | Cabin-pressure accessor (shared with the zone-air agent) | P1 |
| C11 | third_party/kiva/src/libkiva/Algorithms.cpp:72-81, 106-114; Cell.cpp:735 | Kiva DOE-2 convection; exterior IR `eσ(Tamb²Fqtr²+Ts²)(Tamb·Fqtr+Ts)` | Sky referenced to outdoor air through effective emissivity; Walton constant typed as **7.283** (E+ uses 7.238) | IR goes to zero or infinity in vacuum (Tamb ≈ 0); air-based throughout | Kiva unsupported off-Earth (see G03). Report the 7.283 typo upstream. | P2 |

### 2.3 Conduction: CTF and CondFD

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| K01 | CON:194, 376-384 (English units, rk in Btu/**h**·ft·°F), 501, 586, 600-614, 907, 932, 986, 1205, 1220, 1562-1578 | `calculateTransferFunction`: `CTFTimeStep = TimeStepZone` (hours) | One "hour" = 3600 s. All physics is in Btu/h, so the CTF time step is in Earth hours. | With a planetary hour, `TimeStepZone` = 1/N **planetary** hours, but it would be used as 1/N Earth hours: CTFs computed for a timestep 29.5× (Moon) or 1.03× (Mars) too short. Thermal mass response is wrong by that factor. | Add `Real64 const hrScale = state.dataGlobal->SecInHourPhys / 3600.0` (=1.0 exactly on Earth). Use `CTFTimeStep*hrScale` where the step enters physics (CON:501 dxn, 586 dtn comparison, 1205, 1220, 1562-1578). Keep `CTFTimeStep` and `NumHistories` in planetary-hour units for history bookkeeping (HBSM:5678, 5715, 5796 use `TimeStepZone`). | **P0** |
| K02 | CON:134, 945-976 | `MaxAllowedTimeStep = 7.0` (h) | Earth constructions converge well below 7 h | Lunar hour = 29.5 Earth h. With `Timestep` < 5 per hour every massive construction gives a fatal "CTF calculation convergence problem". A 1 m regolith layer (α ≈ 3·10⁻⁹ m²/s, capped at 19 nodes) needs dtn = ρc·dx²/k ≈ 248 h, so it fails at any timestep. | Compare in physical hours (`CTFTimeStep*hrScale`). Off-Earth require `Timestep` ≥ 6 per planetary hour on the Moon (≤ 4.9 Earth h). Document that CTF regolith must be split into ≤ 0.15 m sublayers (dtn ≈ 5.6 h), or use CondFD (preferred, K05). | **P0** |
| K03 | CON:254-258 | `Thickness > 3.0 m` → error | Building layers < 3 m | Regolith covers of 3 m+ are rejected for CTF | Allow larger off-Earth, or document "split into layers" | P1 |
| K04 | CON:293-297; Construction.hh:68 (`MaxCTFTerms = 19`) | massless outer/inner layers given "air at 1 atm, 300 K" mass (cp 1.007, ρ 1.1614, k 0.0263) | Numerical surrogate only | Not physics (just a tiny capacitance). Fine off-Earth. | Leave | — |
| K05 | FD:574 (`int Delt`), 616-623, 1205, 1215 (`nint(TimeStepZoneSec/Delt)`), signatures FD:1581, 1880, 1999, 2383 (`int const Delt`) | CondFD sub-step | `Delt = 3600/N/index ≤ 200 s` is always an exact integer on Earth | Moon (106 300 s hour, N = 60): 1771.7/9 = 196.85 → `int` 196 → 9 sub-steps = 1764 s, so 0.43% of each step is never integrated. N = 1: index stops at 20 with Delt = 5315 s. | `Real64 Delt = TimeStepZoneSec / index` (physical seconds); J_end = index. Bit-identical on Earth, because all Earth values are integers. | **P0** |
| K06 | DataHeatBalSurface.hh:66-67; FD:2691-2730 (`CheckFDNodeTempLimits`, called FD:1855, 1992, 2206, 2256, 2359, 2539), FD:2575; HBSM:8390, 8504, 8605, 8784, 9489, 9590-9595, 9696; HeatBalanceHAMTManager.cc:1412, 1433 | `MinSurfaceTempLimit = -100 °C` (constexpr), `…BeforeFatal = -250 °C` | Earth surfaces never below -100 °C | CondFD **clamps every node** (including the outer face) to -100 °C. Lunar night regolith/skin at ≈ -175 °C would be held at -100 °C: large energy error plus recurring severe errors. (CTF does not clamp the outside face; the inside-face clamps are fine for habitats.) | Make it a runtime member (default -100/-250 for bit-for-bit); off-Earth set it to about -268/-272 °C. `MaxSurfaceTempLimit` 200 °C is fine (lunar max ≈ 120 °C). | **P0** |
| K07 | FD:1748-1787, 1922-1960 (`TempCond` sum ≥ 0 test, `terpld`), 1779-1786 (`Cp = max(Cpo, ΔH/ΔT)`), FD:409-416 (sentinel -100), IDD `MaterialProperty:VariableThermalConductivity` (≤ 100 pairs), `MaterialProperty:PhaseChange` (≤ 100 T-H pairs) | temperature-dependent k(T), cp(T) | PCM use | **Usable for Hayne regolith as is.** k(T) = k_c[1+χ(T/350)³] as ≥ 3 piecewise-linear pairs over -253..+177 °C. cp(T) as an enthalpy table H(T) = ∫cp dT. Caveats: (i) effective cp is clamped below by the Material Specific Heat, so set that to min cp in range (cp(100 K) ≈ 283 J/kgK; IDD minimum is 100); (ii) `terpld` is flat outside the table, so ΔH = 0 and cp falls back to Cpo; the table must cover 20-450 K; (iii) assert(u2 ≥ 3) needs ≥ 3 pairs. | Document the recipe. Optional new `MaterialProperty:VariableSpecificHeat` (T-cp pairs, no clamp). Depth-varying ρ and k_c (Hayne H = 6 cm) → several layers. | **P0** (doc) / P1 (new object) |
| K08 | FD:782-805 | node spacing `dx = sqrt(3·α·Delt)`, uniform per layer, no node cap | Earth walls: tens of nodes | 1 m lunar regolith: dx ≈ 1.35 mm, so ≈740 nodes in one layer, times Gauss-Seidel sweeps (`MaxGSiter = 30`, HeatBalFiniteDiffManager.hh:341) times 9 sub-steps times inside iterations. Feasible but slow. Splitting into layers does not coarsen the grid. | New optional fields in `HeatBalanceSettings:ConductionFiniteDifference`: max nodes per layer and geometric growth factor (Python `layer_cells`: fine at the faces, stretched inside) | P1 |
| K09 | FD:1704 | `GroundSurfsProperty(Surf)` | — (upstream bug: indexed by surface number instead of `SurfPropertyGndSurfIndex`) | Wrong or out-of-range ground temperature for CondFD surfaces that use `SurfaceProperty:GroundSurfaces`, which is the natural regolith-temperature workaround | Fix (planet-gated for bit-for-bit, and submit upstream) | P1 |
| K10 | FD:1762 | `kt = +kt1*(T-20)` | — (upstream bug: should be `+=`) | Exterior node conductivity collapses to kt1·ΔT if a user uses the linear `tk1` coefficient | Fix as K09. Prefer the VariableThermalConductivity table for regolith. | P1 |
| K11 | FD:1580-1878, 2383-2550 (no `SurfQAdditionalHeatSourceOutside/Inside`) | CondFD BCs ignore `SurfaceProperty:HeatBalanceSourceTerm` | — | Cannot impose a geothermal flux (Moon 0.018 W/m², Python `q_geo`) on an adiabatic-bottom CondFD regolith; CTF path does honour it (HBSM:9886) | Add the source term to `ExteriorBCEqns` / `InteriorBCEqns` (planet-gated, or as a general fix) | P2 |
| K12 | HeatBalFiniteDiffManager.hh:70 (`TempInitValue = 23 °C`); HBSM:2417-2660 (`InitThermalAndFluxHistories`), 8064 | initial node temperatures 23 °C | Earth walls equilibrate within the warm-up days | 1 m regolith: τ ≈ L²/(π²α) ≈ 1 Earth year ≈ 12 lunar days. A 50 K initial offset still leaves ~7 K after 25 warm-up lunar days, and the warm-up convergence test may stop earlier on slow drift. | Off-Earth initialisation: linear profile T_deep → surface mean (Python), or a pseudo-transient steady solve with period-mean BCs (Python simulation.py "steady" rows, dt growing to 1e9 s) | P1 |
| K13 | HeatBalanceManager.cc:839-863 | warns if `TimeStepsInHour < 20` for CondFD/HAMT | Index-based | Harmless off-Earth (the Moon at 20/h is a 5315 s step, still stable because CondFD is implicit). The warning text assumes Earth minutes. | Leave | P2 |

### 2.4 Ground models

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| G01 | WeatherManager.cc:2088-2097; GroundTemperatureModeling/*.cc (Kusuda-Achenbach 124-244, Xing 103-203, FiniteDifference 280-283, 438, 507-600, 776, 996) | `Site:GroundTemperature:*` and undisturbed models | Monthly values; annual Earth-day sinusoids (`NumDaysInYear·rSecsInDay`); FD model uses air temperature, wind and evapotranspiration | The monthly objects are fine as user data (constant at depth on the Moon). The Kusuda/Xing/FD models compute an Earth annual wave. | Off-Earth accept only `BuildingSurface` / `FCfactorMethod` (constant) or the planetary value (S10). Fatal for the undisturbed models unless the planetary year/day is wired in (environment agent). | P1 |
| G02 | HeatBalanceManager.cc:4907-5060 (`Rfilm_in 0.135`, `Rfilm_out 0.03`, Earth soil) | F/C-factor constructions | Empirical Earth slab/wall soil resistance | Not valid for regolith | Fatal off-Earth | P2 |
| G03 | HeatBalanceKivaManager.cc:179-198 (30-day steps × `24*60*60`, year 365), 226-229 (hourly weather index ×24), 242-254 (`deepGroundTemperature = annual mean dry-bulb`), 382-389 (`skyEmissivity = Tsky⁴/Tout⁴`), 451 + SurfaceGeometry.cc:10986-10989 (`timestep 3600` or `MinutesInTimeStep·60`), 578-665 (re-reads the EPW, Earth sky-emissivity correlation 0.787+0.764 ln(Tdp/273)); libkiva Ground.cpp:720, 743; Foundation.cpp:150-153 (air props) | Kiva | Earth weather file, air-referenced IR, deep ground = mean air temperature | libkiva itself is a generic 2-D FD solver, but the E+ wrapper and the IR boundary are Earth-only. In vacuum `outdoorTemp` is undefined and the IR coefficient degenerates. | Fatal "Foundation:Kiva unsupported off-Earth" for v1. Future option: patch BoundaryConditions with an explicit sky T and ground T, deep T = planet value, and physical seconds. | P2 |
| G04 | PlantPipingSystemsManager.cc:4283-4560 (FAO-56 evapotranspiration, 4427-4440: `365`, declination 0.409, `rSecsInDay`), 5700 | `Site:GroundDomain:*` (slab/basement) | Earth solar geometry, grass and evapotranspiration | Meaningless off-Earth | Fatal off-Earth | P2 |
| G05 | — (design) | habitat on or under regolith | — | Recommended v1 model, identical to the Python reference: floor construction = [regolith layers (k(T), cp(T)) … floor], outside BC `Ground` = planetary deep T (S10), CondFD. Buried shell = [regolith cover layers … MLI … shell], outside BC `Outdoors` with regolith α/ε as the outer layer; its sky and ground views use S04/S05. No lateral (2-D) heat flow. | See §3.5 | **P0** (recipe) |

### 2.5 Moisture in envelopes

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| M01 | MoistureBalanceEMPDManager.cc:120 (`P_amb = 101325`), 227, 232 (periods `24*3600`, `21*24*3600`), 355-358, 546, 570, 588-589, 702-703 (6× `OutBaroPress`), 607, 613, 629, 678 (4× `TimeStepZone*3600`) | EMPD | Indoor vapour diffusivity ∝ 1/P with P = **outdoor** pressure; 3600 s hours | EMPD is an indoor-only model: P must be the cabin pressure (70 kPa); on the Moon `OutBaroPress = 0` gives a division by zero and negative W. Rates use Earth seconds. | Cabin-pressure accessor; `TimeStepZoneSec`; period = 86 400 s (crew day) or a user input | P2 (cheap; P1 if latent buffering is wanted) |
| M02 | HBSM:8286-8290, 8912-8957 | inside EMPD/HAMT moisture transfer | `OutBaroPress` for zone air density and W | Same as M01 | Cabin pressure | P2 |
| M03 | HeatBalanceHAMTManager.cc:676 (`deltat = TimeStepZone*3600`), 1183-1196 (ext cells = outdoor air, ground = air), 1238 (`HMassConvExtFD`), 1286 (rain suction), 1320, 1337, 1463, 1472 (`WVDC(T, OutBaroPress)`), 1686-1710 | HAMT | Outdoor humid air at ~1 atm, rain, vapour diffusion in pores at outdoor P | Vacuum: WVDC ∝ 1/P → ∞; outdoor RH undefined; rain | Fatal "HAMT unsupported off-Earth" | P2 |

## 3. Recommended implementation

All changes are gated on `state.dataEnvrn->planet.active` (false by default), so the Earth path is never touched.

### 3.1 State needed from other agents (read-only here)
- `planet.active, planet.vacuum, planet.gravity [m/s²], planet.skyIncludesAir (false off-Earth)`.
- Outdoor gas: `planet.outdoorGas` (CO2 mixture on Mars) with `k(T)`, `mu(T)`, `cp`, `R`, plus outdoor pressure `OutBaroPress`.
- Cabin gas per zone: `zoneGas(zoneNum)` and `zonePressure(zoneNum)` (zone-air agent). The Python `Gas` class
  (exobem/gas.py: Sutherland μ, k; ideal-gas ρ) is the template. Put it in one C++ header, `PlanetaryGas.hh`.
- `state.dataEnvrn->GroundSurfTempC` (regolith surface T, from the environment generator) and `planet.deepGroundTempC`.
- `state.dataGlobal->SecInHourPhys` (= solar day/24; 3600 on Earth).

### 3.2 Physics-based convection (`ConvectionCoefficients.cc`, new section `Convect::Planetary`)
Port exobem/convection.py one-to-one:
```cpp
struct GasState { Real64 k, nu, alpha, Pr; };            // from PlanetaryGas at film T, pressure P
Real64 hNatural(GasState g, Real64 Ts, Real64 Ta, Real64 grav, Real64 cosTilt, Real64 Lv, Real64 Lh);
  // Ra = grav*beta*|dT|*L^3/(nu*alpha), beta = 1/T_film
  // vertical: Churchill-Chu  Nu = (0.825 + 0.387 Ra^(1/6) / (1+(0.492/Pr)^(9/16))^(8/27))^2, L = surface Height
  // horizontal, L = A/P: enhanced (hot-up / cold-down) Nu = 0.54 Ra^0.25 (Ra<1e7) else 0.15 Ra^(1/3);
  //                      reduced Nu = 0.27 Ra^0.25; Nu >= 1
  // blend h = (1-|cosTilt|) h_v + |cosTilt| h_h  (same weighting as Python)
Real64 hForced(GasState g, Real64 V, Real64 L);           // flat plate, L = sqrt(A): Re<5e5 0.664 Re^0.5 Pr^(1/3),
                                                          // else max(lam, (0.037 Re^0.8 - 871) Pr^(1/3))
Real64 hMixed = std::cbrt(pow_3(hn) + pow_3(hf));
Real64 tarpScale(GasState g, GasState g0, Real64 T, Real64 T0, Real64 grav);   // optional "ScaledTARP"
```
- New enum values `HcExt::PlanetaryPhysical`, `HcInt::PlanetaryPhysical` (ConvectionConstants.hh:62, 235) and an IDD
  key `PlanetaryPhysical` in `SurfaceConvectionAlgorithm:Inside/Outside` and `SurfaceProperty:ConvectionCoefficients`.
- In `InitExtConvCoeff` (CC:394), insert before the switch:
  `if (planet.active) { HExt = planet.vacuum ? 0.0 : hMixed(outdoorGas(film T, OutBaroPress), wind at Z, …); Kiva lambdas → const; }`
  and fatal for `ASHRAESimple`. On Mars, MoWiTT/DOE-2/TARP/Adaptive give a fatal error or auto-switch with a warning
  (decide in review; Python uses physical whenever planet ≠ Earth).
- In `InitIntConvCoeff` (CC:312): new case using the cabin gas at `MAT` and zone pressure, `grav = planet.gravity`,
  `V = user cabin velocity (default 0.1 m/s)`. When `planet.active` and the zone uses TARP, default to the physical model
  (or the scaled TARP) and print a one-time note. Keep `LowHConvLimit`.
- Replace the 5 `g = 9.81` and the `Constant::Gravity` constant (C09) with `planet.gravity` only inside models kept off-Earth.
- Mars wind: `WindSpeedAt` with planet-supplied sensor height and exponent (S17). Rain/snow are always false.

### 3.3 Exterior LW: tangent linearisation (S04, S05, S07, S08)
- `SurfaceGeometry.cc:329`: `SurfAirSkyRadSplit = planet.active && !planet.skyIncludesAir ? 1.0 : sqrt(...)`.
- New helper in `Convect`: `calcExtLWTangent(state, SurfNum, T0_K, absExt, HSky, TSkyEff, HGrd, TGrdEff, HSrd, TSrdEff, HAir, TAirEff)`
  with `h_k = 4 ε σ F_k T0³`, `T_eff,k = (T_k⁴ + 3T0⁴)/(4T0³)`. Here T_k = sky (planet), ground (`GroundSurfTempC` or the
  `SurfaceProperty:GroundSurfaces` average), and surrounding surfaces. These keep the existing h·(T_eff − T) algebra, so all
  TH11 formulas (HBSM:9883-10016) and the radiant-system coefficients (HBSM:10042-10056) are reused unchanged.
- New per-surface arrays `SurfTSkyEffExt`, `SurfTGrdEffExt`, `SurfTSrdEffExt` (DataHeatBalSurface). `CalcOutsideSurfTemp`
  reads them instead of `TSky`/`TGround`/`TSrdSurfs` when `planet.active`.
- In `CalcOutsideSurfTemp`, off-Earth only: `for (int it = 0; it < 4 && |ΔTH11| > 1e-3; ++it) { recompute tangent coeffs at TH11; solve TH11; }`.
  Then recompute the report flux `SurfQdotRadOutRepPerArea` with the exact εσF(T_k⁴ − TH11⁴).
- In CondFD `ExteriorBCEqns` (FD:1714-1825), off-Earth: compute `hsky, hgnd, Tsky_eff, Tgnd_eff` from the current `TDT_i`
  at every Gauss-Seidel pass. `Tgnd` = planetary ground T (also fixes FD:1706).
- Movable insulation (S15): solve the insulation outer-face temperature with the same tangent loop.
- Unit tests: (a) massless plate in vacuum, absorbed q = εσT⁴ to 0.01 K; (b) MLI skin, 3 K sky, 60 steps per lunar hour:
  no period-2 oscillation (fails with the current secant form, passes with tangent + iteration); (c) Earth regression files unchanged.

### 3.4 Conduction
- CTF (K01, K02): `hrScale` as described. `MaxAllowedTimeStep` is compared in physical hours. Add an input check off-Earth:
  `TimeStepZoneSec ≤ 6·3600` or a fatal error with advice. Allow > 3 m layers off-Earth (K03).
- CondFD (K05, K06): `Real64 Delt`; sub-steps derived from `TimeStepZoneSec`; `MinSurfaceTempLimit` and
  `MinSurfaceTempLimitBeforeFatal` become runtime members of `HeatBalSurfData` (11 call sites listed in K06), off-Earth −270/−272 °C.
- CondFD grid (K08) and initial profile (K12): optional fields `Maximum Nodes per Layer`, `Grid Growth Factor`, and
  `Initial Temperature Profile = Uniform | LinearToGround | SteadyState`. Fix K09, K10 and K11 (gated).
- Regolith recipe (document now, no code): `Material` (ρ, base cp = min cp, k_ref) per depth band (0-2 cm ρ 1100,
  2-6 cm, 6-20 cm, 20-100 cm ρ 1800) + `MaterialProperty:VariableThermalConductivity` (Hayne k(T), ~20 pairs from
  -253 to +177 °C) + `MaterialProperty:PhaseChange` (tk1 = 0; H(T) = ∫cp_Hayne dT, ~20 pairs) +
  `SurfaceProperty:HeatTransferAlgorithm:Construction` = CondFD for the regolith constructions only. Mars regolith: constant
  k from thermal inertia (Python `RegolithColumn.mars`), so CTF is acceptable if split into ≤ 0.15 m layers.

### 3.5 Ground contact
- `Ground` BC = Dirichlet at `planet.deepGroundTempC` (S10). It is applied at the bottom of the regolith layers in the floor
  construction (same as Python `is_gnd` → Dirichlet `T_deep`). `GroundTemp[BuildingSurface]` and `[FCFactorMethod]` are
  overwritten each day in WeatherManager.cc:2088 when `planet.active`. Missing value → fatal error.
- Fallbacks needing no new code: OSC (`ConstTemp` schedule = T_deep, film = 1/R) or OSCM + EMS/PythonPlugin for an external
  regolith model.
- Fence off with clear fatal errors: Kiva, `Site:GroundDomain:*`, F/C-factor constructions, undisturbed ground models without
  a planetary calendar.

### 3.6 Moisture
- Off-Earth: skip the outside moisture blocks (S09) except for HAMT, and make HAMT and EcoRoof fatal.
- EMPD (optional): cabin-pressure accessor, `TimeStepZoneSec`, configurable period.

### 3.7 Leave alone
Inside heat balance iteration (`CalcHeatBalanceInsideSurf2`), interior LW exchange (ScriptF), the CTF state-space math and
history interpolation (bookkeeping in `TimeStepZone` units), CondFD node equations (implicit, unconditionally stable),
OSC/OSCM, `SurfaceProperty:LocalEnvironment` / `SurroundingSurfaces` / `GroundSurfaces` (useful hooks), and the
Material property objects. Keep 3600 s in ACH-based correlations (C08): ACH is a physical unit there, not the planetary hour.

## 4. Open questions / risks

1. **Gas-property ownership.** Exterior (Mars CO2) and interior (cabin N2/O2 at 70 kPa) convection need the same gas API as the
   zone-air and psychrometrics work. Agree on one `PlanetaryGas` header before writing the convection code.
2. **Default interior algorithm off-Earth.** Switching TARP to the physical model silently changes results. The alternative
   (fatal unless the user picks one) is more explicit. Recommendation: auto-switch to the physical model with a warning, and
   offer "ScaledTARP" for comparison against Earth validation.
3. **Stability proof.** The λ ≈ -3h_s/(h_s+h_c+K_o) criterion (S07) is an estimate. Confirm it with test (b) in §3.3, and on
   the Python verification cases (Moon MLI module, regolith-covered module) after the port.
4. **CTF on the Moon.** Even with `hrScale`, CTFs for 1 m regolith need fine sub-layering and ≥ 6 timesteps per lunar hour.
   CondFD is the robust route, but at ~700 nodes per metre it is slow. The grid-stretching option (K08) may be needed before
   regolith runs are practical.
5. **Warm-up.** Regolith time constants (~1 Earth year) exceed what E+ warm-up was designed for. Without K12, lunar
   results depend on initialisation. Also check how the warm-up convergence test (other agent: zone/simulation manager)
   behaves with 29.5-day "days".
6. **Upstream bugs found** (K09 `GroundSurfsProperty(Surf)`, K10 `kt = +kt1`, CondFD ignoring heat-balance source terms,
   Kiva 7.283 vs 7.238). Fixing them ungated changes Earth results for affected inputs. Keep the fixes gated and report them upstream.
7. **2-D effects.** A buried habitat loses heat laterally and through berm edges. The 1-D model (Python and the proposed E+
   setup) ignores this. A planetary Kiva is the eventual tool, but it needs libkiva IR boundary changes (C11, G03).
8. **Mars specifics not covered here:** dust deposition changing α and ε over time (could be done with EMS or schedules), and CO2
   frost on surfaces (latent heat). Both are out of scope for v1.
