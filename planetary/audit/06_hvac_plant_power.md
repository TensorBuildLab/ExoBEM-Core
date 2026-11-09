# 06 - HVAC, plant, heat rejection, fluids and electric power

Audit of ExoBEM-Core (fork of v26.2.0, branch `planetary`). Paths are relative to `src/EnergyPlus/` unless noted.
Read-only audit; line numbers are from the fork as checked out.

## 1. Summary

- **Ideal loads in a sealed cabin is close to working.** `ZoneHVAC:IdealLoadsAirSystem` turns outdoor air, economiser and
  heat recovery off when no `DesignSpecification:OutdoorAir` is given (PurchasedAirManager.cc:396-470). What still breaks
  it is pressure and density: 7 saturation calls use `OutBaroPress`, which is 0 Pa on the Moon and ~700 Pa on Mars;
  mass/volume conversion uses `StdRhoAir`, which comes from Earth elevation (WeatherManager.cc:4476-4477); and zone and
  return nodes are given `Press = OutBaroPress` (DataZoneEquipment.cc:2219-2269). These are the only P0 items here.
- **All HVAC air-side psychrometrics treat `OutBaroPress` as the indoor pressure.** The 50 HVAC/plant/power files
  outside the envelope/zone/weather modules use it 354 times, plus 335 `StdRhoAir` uses in 63 files. The cheapest
  correct fix is to keep `OutBaroPress` meaning "pressure the HVAC air sees" (the cabin pressure off-Earth) and add a
  separate `AmbientPress` for the few real-outdoor consumers.
- **Heat rejection to air is meaningless on the Moon and wrong on Mars.** Cooling towers, fluid coolers, evaporative
  coolers, air- or evap-cooled DX/chillers/VRF/refrigeration condensers, air-source heat pumps and outdoor-air systems
  must be refused with an input error. Equipment that is water-cooled or entirely indoors works as-is.
- **A new radiator plant component is needed (P1).** The best template is `FluidCooler:SingleSpeed` (condenser-loop
  structure, sizing, `PassiveCap`) combined with the surface link of `SolarCollector:FlatPlate:Water` (incident solar and
  view factors from a shading surface). `PlantComponent:UserDefined` driven by a Python plugin can prototype it now
  without touching C++.
- **PV:** Simple PV works with planetary incident solar. Sandia needs an AM0/no-atmosphere air-mass branch. All
  cell-temperature models except `IntegratedSurfaceOutsideFace` assume convective cooling to outdoor air. PVWatts (ssc
  `pvwattsv5_1ts`) computes its own Earth sun position and must be blocked. Battery models (KiBaM, ssc Li-ion) use
  `TimeStepSys` as physical hours, and the PV dynamic model uses `MinutesInTimeStep*60`; all of these must follow the
  planetary hour.
- **EMS/Python is a good harness for components, not for the core physics.** Actuators exist for outdoor
  T/RH/solar/wind, per-surface h_conv, OSC models and user-defined plant components. There is no actuator for
  barometric pressure, sun position, hour length, gravity or `StdRhoAir`.
- **Overall difficulty: moderate.** Little new physics is needed apart from the radiator. Most of the work is one
  pressure/density decision applied consistently, plus a central "unsupported off-Earth" validator.

## 2. Findings

Priority: P0 = needed for a first single-zone Moon/Mars run with ideal loads; P1 = HVAC/plant/PV/realistic outputs;
P2 = rare module, flag "unsupported off-Earth".

### 2.1 Ideal loads, air density and pressure

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| H01 | WeatherManager.cc:4476-4477 | `StdBaroPress`, `StdRhoAir` | `101325*(1-2.25577e-5*z)^5.2559`; rho at 20 C dry, about 1.204 kg/m3 | Every volumetric-to-mass conversion is Earth air (335 uses in 63 files, e.g. PurchasedAirManager.cc:1200,1205,2034,2338,2725,2728,2769; Fans.cc:501,634,1261; MixedAir.cc 9 uses). A 70.3 kPa cabin has rho of about 0.836 kg/m3, so flows, fan power and sizing are 44 % off. If elevation is left blank, nothing crashes and the error goes unnoticed. | When planet != Earth: `StdBaroPress = HabitatPressure`, `StdRhoAir = rho(HabitatPressure, 20 C, W=0, cabin gas)`. Print both to EIO `Site:Location` line (WeatherManager.cc:4478-4495). Earth path unchanged. | **P0** |
| H02 | PurchasedAirManager.cc:2234, 2289, 2291, 2539, 2593, 2879, 2880 | `CalcPurchAirLoads`, `CalcPurchAirMixedAir`: `PsyWFnTdbRhPb(...,OutBaroPress)`, `PsyTsatFnHPb(...,OutBaroPress)` | Supply air saturates at outdoor pressure (= indoor on Earth) | At Pb=0, `PsyWFnTdbRhPb` uses `max(PB-PDEW,1000)` (Psychrometrics.hh:1372), so W_sat = 0.622*Pws/1000, about 1.45 at 20 C. The saturation limit then never applies and `PsyTsatFnHPb` returns garbage, so latent cooling and supply humidity are wrong. Mars (700 Pa) has the same problem. | Use cabin pressure (see section 3, option B: `OutBaroPress` holds cabin pressure off-Earth). No code change in this file if option B is used. | **P0** |
| H03 | DataZoneEquipment.cc:2219, 2234, 2250, 2269; ZonePlenum.cc:746, 847; SplitterComponent.cc:345 | `EquipConfiguration::beginEnvirnInit` etc. | Zone, inlet, exhaust and return nodes `Press = OutBaroPress` | Zone nodes report 0 Pa (Moon) and downstream `Node.Press` users (DX coils, mixers) get vacuum. In total 75 places assign a pressure from `OutBaroPress`. | Same as H02 (cabin pressure). | **P0** |
| H04 | DataZoneEquipment.cc:2220 | zone node `HumRat = OutHumRat` at begin environment | Outdoor humidity is a sensible start value | On the Moon, W=0, so the cabin starts bone dry. Warm-up fixes it slowly with latent gains, but the humidistat or RH outputs may be odd during warm-up. | Initialise from a habitat initial RH (new `Site:PlanetaryBody`/habitat field) when off-Earth. Coordinate with the zone-air audit (ZoneTempPredictorCorrector also seeds from `OutHumRat`). | P1 |
| H05 | PurchasedAirManager.cc:394-403, 406-470 | `GetPurchasedAir`: DSOA object makes `OutdoorAir=true` and creates an OA node | Fresh air is available | OA node carries OutDryBulb/OutHumRat/`Press=OutBaroPress` (OutAirNodeManager.cc:544-622), so it injects "vacuum air" or 95 % CO2 as if it were moist air. | Off-Earth: `ShowSevereError` if `design_specification_outdoor_air_object_name` is non-blank (no outdoor air in vacuum/CO2). Later, "make-up gas from storage" could reuse the OA path with a scheduled OA node. | **P0** (input error) |
| H06 | PurchasedAirManager.cc:1747, 1845; Sizing:Zone DSOA | ideal-loads sizing uses `FinalZoneSizing.MinOA` | OA load in sizing | Zone sizing would add an OA load computed from a design day with no air. | Off-Earth: error if `Sizing:Zone` names a DSOA object (zone-sizing audit to confirm). | P1 |
| H07 | PurchasedAirManager.cc:2075, 2872 | `TimeEconoActive/TimeHtRecActive = TimeStepSys` | Reported in hours | These become planetary hours, which is only a labelling issue. Never active off-Earth (no OA). | Leave; document the unit. | P2 |
| H08 | PurchasedAirManager.cc:3039-3046 | energies `= rate * TimeStepSysSec` | 3600 s/hour | Correct if `TimeStepSysSec` follows the planetary hour (time audit). | None here. | - |
| H09 | DataLoopNode.hh:457; 22 compares of `DefaultNodeValues.Press` (DXCoils.cc:607, 9396, 9424, 10470; UnitarySystem, HVACManager, ConvectionCoefficients, PackagedThermalStorageCoil) | node default `Press = StdPressureSeaLevel` used as an "unconnected" sentinel | 101325 Pa means "not set" | Still works as a sentinel. Unconnected nodes report 101325, not cabin pressure. | Leave alone (changing the sentinel risks Earth diffs). | P2 |
| H10 | NodeInputManager.cc:1092-1121, 1182 | `CalcMoreNodeInfo` node RH/wet-bulb/dew-point/density outputs at `OutBaroPress` / `StdBaroPress` | Indoor = outdoor pressure | System node outputs wrong. | Covered by option B and H01. | P1 |
| H11 | HVACManager.cc:2291-2821 | infiltration/ventilation/mixing report densities at `OutBaroPress` and `/StdRhoAir` | Earth outdoor air | Reporting only; infiltration/ventilation must be blocked off-Earth anyway (envelope/zone audit). | Covered by option B; block infiltration objects. | P1 |

### 2.2 Fans, ducts, mixers, coils (air side)

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| H12 | Fans.cc:501-502, 634-635, 1261-1274, 1385, 1404, 1674, 1710, 1788, 1845, 1933, 1996, 2103, 2130 | `rhoAirStdInit = StdRhoAir`; `P = m*dP/(eta*rho)`; Euler number | Standard Earth density | Self-consistent once H01 sets cabin `StdRhoAir`. The fan-law dependence of dP on density is not modelled: a user-entered pressure rise is taken at the cabin density as given. | No code change beyond H01. Document that `Pressure Rise` must be for cabin gas density (~0.69x Earth at 70 kPa). | P1 |
| H13 | MixedAir.cc:3231-3237, 3361-3367, 4668-4685, 4902-4909 | `OAMixerProps::CalcOAMixer` mass-weighted pressure mix; `Controller:OutdoorAir` economiser (MixedAir.cc 3701-3702 relief losses vs `OutDryBulbTemp`/`OutEnthalpy`) | OA is breathable air at ~101 kPa | Mixing vacuum or CO2 at 700 Pa into supply air is nonsense. | Off-Earth: refuse `AirLoopHVAC:OutdoorAirSystem`, `OutdoorAir:Mixer`, `Controller:OutdoorAir`, `Controller:MechanicalVentilation`, `ZoneHVAC:OutdoorAirUnit`, `ZoneHVAC:EnergyRecoveryVentilator`, `AirLoopHVAC:DedicatedOutdoorAirSystem`. | P1 |
| H14 | OutAirNodeManager.cc:119 (`GetOutAirNodesInput`), 443 (`CheckAndAddAirNodeNumber`), 524-635 (`SetOANodeValues`: Temp=OutDryBulb, HumRat=OutHumRat or `PsyWFnTdbTwbPb(...OutBaroPress)`, `Press=OutBaroPress` at :622) | `OutdoorAir:Node` and `OutdoorAir:NodeList` | Weather gives a usable air state | In vacuum the node state is undefined. On Mars the node is CO2 handled as moist air. Every component that registers an OA node passes through these two functions, so they are a natural chokepoint. | Off-Earth with `atmosphere=none`: severe error in both functions, naming the owning object. With `thin CO2`: same error unless the node is only a sensor (`ConnectionType::OutsideAirReference` / sensor). | P1 |
| H15 | DXCoils.cc:9392-9450, 10461-10500, 11128-11167, 11654-11685, 12947-12951 (52 `OutDryBulb/OutWetBulb` + 60 `OutBaroPress` uses in file) | `CalcDoe2DXCoil`, `CalcMultiSpeedDXCoil*`, condenser inlet temperature | Air-cooled: CondInlet = outdoor DB; evap-cooled: wet-bulb approach; curves `f(OAT)` rated at Earth density | Moon: no condenser medium. Mars: rho of about 0.016 kg/m3, so capacity/EIR curves are invalid, and evaporative condensers cannot work at 700 Pa (near the water triple point). | Off-Earth: error for any `Condenser Type = AirCooled / EvaporativelyCooled` in `Coil:Cooling:DX:*`, `Coil:Heating:DX:*`, `Coil:Cooling:DX:CurveFit:OperatingMode` (enum at Coils/CoilCoolingDXCurveFitOperatingMode.hh:139), `Coil:*:DX:VariableSpeed` (VariableSpeedCoils.cc 23 uses), `Coil:Cooling:DX:SingleSpeed:ThermalStorage`. Allowed: condenser in a zone (`IsSecondaryDXCoilInZone`, DXCoils.cc:9413-9419 and 9433-9442), `ZoneHVAC:Dehumidifier:DX` (rejects to zone), water-cooled variable-speed and water-to-air HP coils. | P1 |
| H16 | DXCoils.cc:600-616 and many `PsyTsatFnHPb(...,OutBaroPress)` on the evaporator side; WaterCoils.cc (23), UnitarySystem.cc (9), VariableSpeedCoils.cc (21), HeatRecovery.cc (29), Humidifiers.cc (9) | evaporator/indoor-coil saturation checks | Indoor = outdoor pressure | Cabin coil latent performance is computed at 0 or 700 Pa. | Covered by option B (cabin pressure). | P1 |
| H17 | DXCoils.cc:6859-7262, 12212-12504 (19 uses of `StdPressureSeaLevel`); VariableSpeedCoils.cc (14); Coils/CoilCoolingDX.cc (6) | rated-condition and ADP/bypass-factor calcs at 101325 Pa | Ratings are sea-level by convention | Bypass factor is derived at sea level and then applied in a 70 kPa cabin. This is a second-order effect. | Leave as rating convention. Document. | P2 |
| H18 | EvaporativeCoolers.cc:1116-1118, 1840 (31 `OutBaroPress`, 5 OA uses); HybridEvapCoolingModel.cc; HybridUnitaryAirConditioners.cc | secondary air = outdoor air; water evaporation | Liquid water evaporates into air | Impossible in vacuum or at 700 Pa. | Off-Earth: error for all `EvaporativeCooler:*`, `ZoneHVAC:EvaporativeCoolerUnit`, `ZoneHVAC:HybridUnitaryHVAC`. | P1 |
| H19 | HVACVariableRefrigerantFlow.cc:455, 474, 5647 (32 OA uses); 14992 (`9.80665`), 15152 (pipe height head) | VRF condenser = outdoor air; refrigerant-pipe gravity head | Air-cooled condenser; g = 9.80665 | Air/evap-cooled VRF is meaningless. Water-cooled VRF works, but its pipe static head uses Earth g. | Error on air/evap condenser type. Replace `9.80665` with `state.dataEnvrn->Gravity` (body gravity from `Site:PlanetaryBody`). | P1 / P2 (g) |
| H20 | Humidifiers.cc:787, 805, 1011; DesiccantDehumidifiers.cc:1853, 1864 | gas humidifier and desiccant regeneration use outdoor state | Regen air from outdoors | Desiccant regeneration with outdoor air is impossible. The steam-electric humidifier works (indoor). | Allow `Humidifier:Steam:Electric`. Error on `Dehumidifier:Desiccant:*` when regen inlet is an OA node (H14 catches it). | P2 |
| H21 | SetPointManager.cc:2501-2523 (`SPMOutsideAir`, follow-OAT), SystemAvailabilityManager.cc (7), PlantCondLoopOperation.cc:213-225, 3625-3666, 3998-4004; Plant/EquipAndOperations.cc:884-927 | control on outdoor DB/WB/RH/dew point | Outdoor air temperature is meaningful | The control signal is undefined in vacuum. | Off-Earth: error for `SetpointManager:OutdoorAirReset`, `SetpointManager:FollowOutdoorAirTemperature`, `SetpointManager:CondenserEnteringReset*`, `PlantEquipmentOperation:Outdoor*`, `AvailabilityManager:*Temperature*Turn*` when they use outdoor sensors. | P2 |

### 2.3 Heat rejection and plant

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| H22 | CondenserLoopTowers.cc:434-445, 766-777, 1403-1414, 1644-1655, 1734-1743; design 2608-3716 (`StdBaroPress`, 35 C/25.6 C) | `CoolingTower:SingleSpeed/TwoSpeed/VariableSpeed/VariableSpeed:Merkel` | Evaporative heat and mass transfer to outdoor air | Impossible. | Error off-Earth (object-type blocklist). | P1 |
| H23 | FluidCoolers.cc:276-287, 393-405, 896-905 | `FluidCooler:SingleSpeed/TwoSpeed` | Dry air-cooled UA to OA | No air on the Moon. Mars density makes the UA sizing invalid. | Error off-Earth. **Used as structural template for the radiator (section 3.3).** | P1 |
| H24 | EvaporativeFluidCoolers.cc:261-272, 319, 618-629, 662, 1313-1320 | `EvaporativeFluidCooler:*` | Evaporation | Impossible. | Error off-Earth. | P1 |
| H25 | ChillerElectricEIR.cc:316-326, 355, 1051, 1117-1130, 1335, 1827-1857; same pattern in ChillerReformulatedEIR.cc, PlantChillers.cc (`Chiller:Electric`, `ConstantCOP`, `EngineDriven`, `CombustionTurbine`), ChillerElectricASHRAE205.cc | `DataPlant::CondenserType` (Plant/Enums.hh:277-283) AirCooled/EvapCooled: condenser inlet = OA DB/WB node | OA heat sink | Meaningless. Water-cooled chillers work and are the right "heat-pump lift" device between cabin loop and radiator loop. | Error if `condenser_type` is AirCooled/EvaporativelyCooled. Allow WaterCooled. | P1 |
| H26 | PlantLoopHeatPumpEIR.cc:120, 449, 540, 547, 588 (17 OA uses); `HeatPump:AirToWater*`, `HeatPump:AirToWater:FuelFired:*` | `airSource` branch | Air-source evaporator/condenser | Meaningless. | Error for air-source variants. Allow `HeatPump:PlantLoop:EIR:*` water-source, `HeatPump:WaterToWater:*`, `CentralHeatPumpSystem`. | P1 |
| H27 | RefrigeratedCase.cc:10744, 12026-12030; 14819 (Earth gravity vs latitude formula), 14896, 14915 | `Refrigeration:Condenser:AirCooled/EvaporativeCooled`, `GasCooler:AirCooled`; walk-in door infiltration uses latitude-based Earth g | OA condenser, Earth g | Air/evap condensers meaningless. Door infiltration uses the wrong g. | Error on air/evap condensers. Allow `Refrigeration:Condenser:WaterCooled` and `Cascade`. Use body g at 14819. | P2 |
| H28 | WaterThermalTanks.cc:497, 1393, 1575-1751, 1953-2137, 2534-2545 (`WTTAmbientTemp::OutsideAir`); 2159, 6852-6911, 7016, 12679 (HPWH psych at `OutBaroPress`) | `WaterHeater:*`, `ThermalStorage:*` ambient "Outdoors"; HPWH inlet air OutsideAir/ZoneAndOA | Tank skin UA to outdoor air; heat-pump water heater evaporator in OA | A UA to vacuum is fiction. A fuel-fired water heater vented outdoors has no combustion air. | Error if ambient indicator = Outdoors or HPWH inlet = OutsideAir/ZoneAndOA. Zone or Schedule ambient work. Warn for fuel types other than Electricity. | P1 |
| H29 | PipeHeatTransfer.cc:154-171, 325-335, 461-470, 589 | `Pipe:Outdoor` (OA convection), `Pipe:Underground` (ground model) | Air convection; Earth soil | Outdoor pipe is meaningless. Underground pipe needs regolith properties. | Error on `Pipe:Outdoor`. `Pipe:Underground` works with planetary ground-temperature model (regolith audit). | P2 |
| H30 | SurfaceGroundHeatExchanger.cc:508-538, 1194-1257 (`CalcTopSurfTemp`: `CalcASHRAESimpExtConvCoeff`, rain, sky linearised); PondGroundHeatExchanger.cc:722 (`GravConst 9.81`, evaporation) | `GroundHeatExchanger:Surface`, `:Pond` | Wind convection, rain, evaporation | Top-surface convection and evaporation are wrong; the pond would freeze or boil. | Error on Pond. Surface GHX: P2 (could be adapted with h=0, but the new radiator is better). | P2 |
| H31 | GroundHeatExchangers/Slinky.cc:272 (`ts = 3600.0`), 674; Vertical.cc:454-506 (`8760`, `timeSSFactor`), 1013; Base.cc:134, 426-427 (`iHoursInDay`); IceThermalStorage.cc:110 (`TimeInterval 3600`); PlantPipingSystemsManager.cc:216 | time constants in seconds/hours | 1 h = 3600 s, 8760 h/yr | g-function load aggregation and ice-storage rates would be in the wrong physical time. | Physical seconds: use `SecInPlanetaryHour` for simulation-hour conversions; keep 3600 where the input unit is a real hour. Time audit owns this; listed for completeness. | P2 |
| H32 | Plant/PlantManager.cc:2841, 2857; PlantPressureSystem.cc:326-327; SteamCoils.cc:555 (`101325.0`), 676, 1090, 1234 | plant/steam node `Press = StdBaroPress`, condensate sat temperature at `StdBaroPress` | Loop open to 1 atm | Bookkeeping for liquid loops. Steam condensate temperature follows the cabin pressure once H01 is applied. | Leave (H01 covers it). Steam systems: P2. | P2 |
| H33 | FluidProperties.cc:106-114 (default glycol/water table -35..125 C), 4132-4170 (`getSpecificHeat` out-of-range: recurring warning + clamp) | liquid properties `f(T)` only; no boiling or freezing check | Loops stay liquid near 1 atm | Water at 70 kPa boils at ~90 C, so 82 C hot-water loops are marginal and not detected. A radiator loop at lunar night (sink ~100 K) runs far below -35 C: values clamp silently (warning only) and freezing is not detected. | Recommend user-defined `FluidProperties:Name` (Glycol type with user `FluidProperties:Temperatures/Concentration` tables) for ammonia or HFE/Galden coolants down to -100 C. Add an off-Earth severe warning when a loop's minimum loop temperature is below the fluid's lowest table temperature. Add optional loop-pressure-based boiling check (P2). | P1 |
| H34 | WeatherManager.cc:7047-7160 (`CalcWaterMainsTemp`, Correlation from annual OA temperature) | `Site:WaterMainsTemperature` | Buried pipes track OA climate | The correlation is invalid off-Earth. | Off-Earth: require `Schedule` method (water from storage tank). | P2 |
| H35 | (none; reference: exobem/thermal_control.py) | no object rejects heat to space | Heat always leaves via air or ground | The habitat cannot reject cabin heat in a plant model. | New plant component `HeatRejection:Radiator` (section 3.3). | P1 |

### 2.4 Electric power

| ID | File:line | Function / symbol | Earth assumption (value) | Effect off-Earth | Proposed change | Priority |
|---|---|---|---|---|---|---|
| H36 | Photovoltaics.cc:780-830 | `CalcSimplePV`: `P = A * f * SurfQRadSWOutIncident * eta` | none | Works as soon as the solar engine writes planetary `SurfQRadSWOutIncident`. | None. Works with planetary inputs. | P1 |
| H37 | Photovoltaics.cc:1931-1956 (`AbsoluteAirMass`), 1069, 1000 | Kasten-Young `AM = 1/(cos z + 0.5057(96.08-z)^-1.634)`, `exp(-0.0001184*Altitude)` (8.4 km scale height), `SandiaF1(AMa)` | Terrestrial AM1.5 spectrum, Earth scale height | Moon: physical AM = 0 but code gives 1..36 (and 36.32 at the horizon), and F1 is extrapolated to AM 0..36, so it is wrong. Mars: AM depends on dust tau and CO2 column; the Earth scale height is wrong. | Off-Earth: `atmosphere=none` gives `AMa = 0` and F1 = user "AM0 spectral factor" (default 1.0) instead of the polynomial. Mars: AMa from the planetary sky model (or F1 = 1 with warning). Earth branch untouched. | P1 |
| H38 | Photovoltaics.cc:1003-1061 (`SandiaModuleTemperature`: `E*exp(a+b*Ws)+Ta`, 1775-1810), 1335-1349 (TRNSYS Decoupled NOCT `HeatLossCoef`), 1350-1362, 1445-1452 (Uhlleberg dynamic), 1228-1232 (init to `SurfOutDryBulbTemp`) | cell temperature models | Convective cooling to outdoor air at `SurfOutDryBulbTemp` with wind; NOCT 800 W/m2/20 C/1 m/s | In vacuum, cooling is radiative only: cell temperatures are under-predicted at lunar noon (real ~100 C) and the "ambient" is undefined at night. | Off-Earth: warn for Decoupled/DecoupledUllebergDynamic and the Sandia default; recommend `IntegratedSurfaceOutsideFace` (uses the planetary surface heat balance, Photovoltaics.cc:1365, 1454). Add new mode `RadiativeEquilibrium` for shading-surface PV: solve `(alpha-eta)G = eps_f sigma(F_sky(T^4-Tsky^4)+F_g(T^4-Tg^4)) + eps_b sigma(...)`, with a dynamic option using the module heat capacity. | P1 |
| H39 | Photovoltaics.cc:1316 | `PVTimeStep = MinutesInTimeStep * 60` | 60 s/min of Earth hour | Wrong physical time constant for the Uhlleberg dynamic model. | `PVTimeStep = state.dataGlobal->TimeStepZoneSec`. | P1 |
| H40 | PVWatts.cc:91 (`ssc_module_create("pvwattsv5_1ts")`), 154-169 (lat/lon/tz, `time_step = TimeStepZone`), 400-419 (year/month/day/hour/minute, beam, diffuse, tamb, wspd); ssc `cmod_pvwattsv5.cpp:218-312` (`irr.set_time`, `irr.calc`, `pvwatts_celltemp`) | `Generator:PVWatts` | ssc computes the Earth sun position from date/lat/lon and its own POA and Fuentes cell temperature | Gives Earth sun geometry on the Moon/Mars, even with planetary DNI. | Off-Earth: error on `Generator:PVWatts` and `ElectricLoadCenter:Inverter:PVWatts`. Alternative (P2): feed `poa` from `SurfQRadSWOutIncident` via a different ssc entry. | P1 |
| H41 | ElectricPowerServiceManager.cc:3977-3980, 4033-4036, 4067-4072 | KiBaM `ElectricLoadCenter:Storage:Battery` uses `TimeStepSys` with k [1/h] | sim hour = 3600 s | With planetary hours of 3699 s or 106 300 s, the battery dynamics are 3 % to 30x off. | Use `TimeStepSysSec / 3600.0` (physical hours) everywhere k*dt appears. Earth is bit-identical (3600/3600). | P1 |
| H42 | ElectricPowerServiceManager.cc:3353-3383, 3391, 4150-4151 | ssc Li-ion `battery_t(dt_hr = TimeStepSys)`, `ChangeTimestep(TimeStepSys)` | same | Same as H41 for capacity, voltage, thermal and lifetime models. | Pass `TimeStepSysSec / 3600.0`. Also the compare at :4150. | P1 |
| H43 | ElectricPowerServiceManager.cc:4155-4160 | Li-ion `thermal->T_room = OutDryBulbTemp` if no zone; ssc `thermal_t` uses convective h*A | Battery in outdoor air | Convective heat loss to vacuum is fiction. | Off-Earth: require `Zone Name` for `Storage:LiIonNMCBattery` (error if blank). Same for KiBaM/Simple heat-loss destination (zone or none). | P1 |
| H44 | ElectricPowerServiceManager.cc:3846-3896 | `Storage:Simple` energy `= P * TimeStepSysSec` | none | Works if `TimeStepSysSec` follows the planetary hour. | None. | - |
| H45 | ElectricPowerServiceManager.cc:2417-2600, 2908-3012, 4516-4850 | inverters/converters/transformer thermal losses to zone or outdoors | - | They work. Losses to "outdoors" are simply lost (acceptable). | None. Works as-is. | - |
| H46 | MicroturbineElectricGenerator.cc:756-807, 1293-1305; CTElectricGenerator.cc:377; ICEngineElectricGenerator.cc; MicroCHPElectricGenerator.cc; FuelCellElectricGenerator.cc (+ `Generator:FuelCell:AirSupply`) | combustion/air-breathing generators | Atmospheric O2 intake | Meaningless (no oxidiser). | Error off-Earth. A future `Generator:FuelCell:H2O2` would be new work (P2). | P2 |
| H47 | WindTurbine.cc:955-959; DataEnvironment.cc:191-216 (`OutBaroPressAt`: g 9.80665, M 0.028964, lapse -0.0065) | air density for rotor power | Earth air and standard atmosphere | Moon: no wind. Mars: density uses R_air instead of R_CO2 (about 1.5x low) and an Earth lapse rate. | Moon: error. Mars: density from planetary gas model (`exobem/gas.py MARS_CO2`); P2. | P2 |
| H48 | PhotovoltaicThermalCollectors.cc:1150-1152, 1369 (`gravity 9.81`); SolarCollectors.cc:1154-1262 (efficiency vs `SurfOutDryBulbTemp`), 1384, 1791-1822, 1939, 2039 (`gravity 9.806`); TranspiredCollector.cc | collectors with convective losses, natural convection in gaps | Earth air, Earth g | Loss correlations are invalid in vacuum. | Error for `SolarCollector:UnglazedTranspired*`, PVT. Flat plate / ICS: P2 (unsupported off-Earth warning). | P2 |
| H49 | ElectricPowerServiceManager.cc:484-529 | `Electricity:Purchased` / facility net | Grid exists | Purchased electricity off-Earth is really unmet demand. | Rename in reports off-Earth ("Unmet Electric Demand") or add an output variable. Cosmetic. | P2 |

### 2.5 EMS / Python API (prototype path)

| ID | File:line | Function / symbol | What it can do | Limit | Use | Priority |
|---|---|---|---|---|---|---|
| H50 | WeatherManager.cc:651-697, applied 2110-2180 | "Weather Data"/"Environment" actuators: Outdoor Dry Bulb, Outdoor Dew Point, Outdoor Relative Humidity, Diffuse Solar, Direct Solar, Wind Speed, Wind Direction (7) | Override the weather each zone step (`callbackBeginZoneTimestepBeforeSetCurrentWeather`, api/runtime.h:64) | **No barometric pressure actuator; no sky temperature actuator** (sky is set through `WeatherProperty:SkyTemperature` schedule, WeatherManager.cc:6729, and a `Schedule:Constant` actuator). Solar angles still come from the Earth ephemeris and the 3600 s hour. | Validate component physics at Earth time base only. | P2 |
| H51 | EMSManager.cc:1809-1825, 1845, 1886-1925 | "Surface": Interior/Exterior Surface Convection Heat Transfer Coefficient, Construction State, View Factor To Ground, Outdoor Air Drybulb/Wetbulb Temperature, Outdoor Air Wind Speed/Direction; ConvectionCoefficients.cc:650 applies the ext-h override | Set h_ext ~ 0 for vacuum per surface | The radiation-to-air term (`SurfAirSkyRadSplit`, ConvectionCoefficients.cc:660-668) and `HGround` use `TAir`, so vacuum is still not exact. | Quick vacuum envelope check. | P2 |
| H52 | SurfaceGeometry.cc:11750-11780; HeatBalanceSurfaceManager.cc:7653-7700 | `SurfaceProperty:OtherSideConditionsModel` actuators: Convection Bulk Air Temperature, Convection Heat Transfer Coefficient, Radiation Effective Temperature, Radiation Linear Heat Transfer Coefficient | Exact radiative-sink BC: h_conv=0, T_rad=T_sink (same formula as the radiator sink), h_rad=4 eps sigma T_m^3 recomputed each step | Absorbed solar on OSCM surfaces must be checked; if it is not applied, fold alpha*G into T_sink (thermal_control.py `radiator_sink` does exactly this). | Best EMS emulation of a lunar envelope at Earth time base. | P2 |
| H53 | UserDefinedComponents.cc:137-247, 1248-1299; api/runtime.h:80 (`callbackUserDefinedComponentModel`) | `PlantComponent:UserDefined` with Python plugin: reads inlet T/mdot/rho/cp, writes outlet T and mdot | Prototype the radiator now: a Python `on_user_defined_component_model` computes T_out from `radiator_sink` | Python sees the same Earth time base unless the planetary hour is implemented. | **Recommended low-risk path** for radiator design before writing C++. | P1 |
| H54 | PlantComponentTemperatureSources.cc:147-148, 243-248; PlantLoadProfile.cc:571-581 | `PlantComponent:TemperatureSource` (scheduled boundary T), `LoadProfile:Plant` "Power"/"Mass Flow Rate" actuators | Inject ideal-loads cooling (from `Zone Ideal Loads Supply Air Total Cooling Rate`) into a condenser loop and reject it to a scheduled sink T | Not a radiator. | Couple ideal loads to plant for heat-pump/radiator studies. | P1 |

## 3. Recommended implementation

### 3.1 Cabin pressure and density (P0)

Add the following to `DataEnvironment.hh` (struct `EnvironmentData`):

```cpp
Real64 AmbientPress = DataEnvironment::StdPressureSeaLevel; // true outdoor pressure [Pa] (0 on Moon)
Real64 HabitatPress = DataEnvironment::StdPressureSeaLevel; // cabin pressure [Pa] from Site:PlanetaryBody/habitat input
bool   OffEarth = false;                                    // set when Site:PlanetaryBody != Earth
Real64 Gravity = 9.80665;                                   // body gravity (shared with other audits)
```

**Option B (recommended for the first run).** In WeatherManager, at the point where `OutBaroPress` is set for the
timestep (and in the design-day setup), add:

```cpp
state.dataEnvrn->AmbientPress = <value from weather / planetary generator>;
state.dataEnvrn->OutBaroPress = state.dataEnvrn->OffEarth ? state.dataEnvrn->HabitatPress : state.dataEnvrn->AmbientPress;
```

- **Effect.** All 354 HVAC/plant/power uses of `OutBaroPress` (H02, H03, H10, H16) become correct with no edits,
  because every remaining air-side consumer off-Earth is indoor air. Equipment that really sees outdoor air is refused
  (3.2).
- **Real-ambient consumers to switch to `AmbientPress`:**
  - the `Site Outdoor Air Barometric Pressure` output;
  - exterior convection (convection audit);
  - `OutBaroPressAt` (DataEnvironment.cc:191);
  - WindTurbine.cc:956;
  - the weather range checks (WeatherManager.cc:2495, 2900, 3555).
- **Earth.** `AmbientPress == OutBaroPress`, so results are bit-for-bit identical.
- **Coordination.** The weather, psychrometrics and zone-air audits must agree on this single decision. Envelope
  moisture models (EMPD/HAMT/CondFD exterior) should be declared unsupported off-Earth, because they mix outdoor
  humidity with `OutBaroPress`.

**Option A (later cleanup).** Rename the indoor uses to `HabitatPress` file by file. This is cleaner but means
hundreds of edits with misclassification risk. Do it only after option B results are validated.

**Standard density.** In WeatherManager.cc:4476-4477, when `OffEarth`, set
`StdBaroPress = HabitatPress` and `StdRhoAir = PsyRhoAirFnPbTdbW(HabitatPress, 20, 0)`. If the psychrometrics audit
adds a cabin gas constant for the 26.5 % O2 mixture, use it (M = 29.07 g/mol; about 0.3 % denser than the R=287 value).
This fixes H01, H12 and the plant node pressures (H32).

**Ideal loads input check** (PurchasedAirManager.cc, `GetPurchasedAir` after :393): if `OffEarth` and the DSOA field is
non-blank, call `ShowSevereError(...)` with "outdoor air is not available on <body>; remove Design Specification
Outdoor Air or use a make-up gas model", and set `ErrorsFound = true`. Nothing else in ideal loads needs to change.

### 3.2 Central "unsupported off-Earth" validator (P0 framework, P1 content)

- **Where.** New file `PlanetaryChecks.cc/.hh` with `void CheckUnsupportedInputObjects(EnergyPlusData &state)`, called
  in SimulationManager.cc right after `CheckForMisMatchedEnvironmentSpecifications(state)` (line 288). At that point
  epJSON is parsed, but no component GetInput has run.
- **Data-driven.** Use a constexpr table `{objectType, fieldKey (or empty), forbiddenValuesUC, appliesTo
  (Vacuum|ThinCO2|AnyOffEarth), message}`. Scan with `inputProcessor->getNumObjectsFound` and iterate
  `inputProcessor->epJSON[objectType]` for field-level checks. One `ShowSevereError` per offending object, then
  `ShowFatalError` once at the end.
- **Object-level blocks (any off-Earth):**
  - `CoolingTower:*`, `FluidCooler:*`, `EvaporativeFluidCooler:*`, `EvaporativeCooler:*`;
  - `ZoneHVAC:EvaporativeCoolerUnit`, `ZoneHVAC:HybridUnitaryHVAC`, `AirLoopHVAC:OutdoorAirSystem`, `OutdoorAir:Mixer`,
    `Controller:OutdoorAir`, `ZoneHVAC:OutdoorAirUnit`, `ZoneHVAC:EnergyRecoveryVentilator`,
    `AirLoopHVAC:DedicatedOutdoorAirSystem`;
  - `ZoneHVAC:PackagedTerminalAirConditioner/HeatPump`, `ZoneHVAC:WindowAirConditioner` (always OA-cooled);
  - `HeatPump:AirToWater*`, `Generator:PVWatts`, `ElectricLoadCenter:Inverter:PVWatts`,
    `Generator:InternalCombustionEngine`, `Generator:CombustionTurbine`, `Generator:MicroTurbine`, `Generator:FuelCell`,
    `Generator:MicroCHP`;
  - `Chiller:EngineDriven`, `Chiller:CombustionTurbine`, `ChillerHeater:Absorption:DirectFired`;
  - `Pipe:Outdoor`, `GroundHeatExchanger:Pond`, `SolarCollector:UnglazedTranspired*`,
    `SolarCollector:FlatPlate:PhotovoltaicThermal`, `Refrigeration:GasCooler:AirCooled`,
    `Refrigeration:Condenser:AirCooled/EvaporativeCooled`;
  - Vacuum only: `Generator:WindTurbine`.
  - Also the envelope/zone objects owned by other audits (`ZoneInfiltration:*`, `ZoneVentilation:*`, `ZoneEarthtube`,
    `ZoneCoolTower:Shower`, `ZoneThermalChimney`).
- **Field-level blocks:**
  - `condenser_type` in {AIRCOOLED, EVAPORATIVELYCOOLED} for `Chiller:Electric:EIR`, `Chiller:Electric:ReformulatedEIR`,
    `Chiller:Electric`, `Chiller:ConstantCOP`, `Chiller:Electric:ASHRAE205`, `Coil:Cooling:DX:SingleSpeed/TwoSpeed/
    MultiSpeed/TwoStageWithHumidityControlMode/VariableSpeed`, `Coil:Cooling:DX:CurveFit:OperatingMode`,
    `Coil:Heating:DX:*` (air-source by definition, so block unless the condenser is in a zone);
  - `AirConditioner:VariableRefrigerantFlow*` with air/evap condenser;
  - `HeatPump:PlantLoop:EIR:*` with `condenser_type = AirSource`;
  - `WaterHeater:Mixed/Stratified`, `ThermalStorage:ChilledWater:*` with `ambient_temperature_indicator = Outdoors`;
  - `WaterHeater:HeatPump:*` with inlet air OutdoorAirOnly/ZoneAndOutdoorAir;
  - `ElectricLoadCenter:Storage:LiIonNMCBattery` with blank zone;
  - `ZoneHVAC:IdealLoadsAirSystem` and `Sizing:Zone` with DSOA;
  - `Site:WaterMainsTemperature` with method Correlation*.
- **Warnings (not errors):**
  - `Generator:Photovoltaic` with integration mode Decoupled/DecoupledUllebergDynamic (convective NOCT model);
  - fuel-fired `Boiler:HotWater`, `Coil:Heating:Fuel`, `WaterHeater:*` (no oxidiser modelled);
  - DX/water coils (rated at sea-level density).
- **Backstop.** Errors in `OutAirNodeManager::GetOutAirNodesInput` (:119) and `CheckAndAddAirNodeNumber` (:443) when
  `OffEarth` and atmosphere = none. This catches any OA-node user missed by the table (towers, chiller condenser nodes,
  ideal-loads OA, microturbine combustion air).

### 3.3 New plant component `HeatRejection:Radiator` (P1)

- **Template.** Follow FluidCoolers.cc/.hh (struct `FluidCoolerspecs : PlantComponent`, `factory`, `simulate`,
  `oneTimeInit`, `onInitLoopEquip`, `getDesignCapacities`, `getSizingFactor`, `size()`, condenser-loop flow handling,
  `HowMet::PassiveCap`).
- **Surface link.** Take it from SolarCollectors.cc:328-370 (`Surface` must be `ExtSolar`, area check) and :1087-1120
  (use `SurfQRadSWOutIncidentBeam/SkyDiffuse/GndDiffuse`, `SurfCosIncidenceAngle`). The radiator therefore gets
  shading, planetary irradiance and `Surface.ViewFactorSkyIR / ViewFactorGroundIR` for free. A two-sided radiator
  references two shading surfaces or one surface with a "two-sided" flag (back side uses tilt 180 - tilt).
- **IDD fields (sketch):**
  - Name; Water Inlet Node; Water Outlet Node; Surface Name (Shading:* / Generator-style); Number of Sides (1|2);
  - Radiating Area per Side {m2} (or from surface); IR Emissivity; Solar Absorptance; Fin Efficiency
    (or overall radiator effectiveness);
  - Design Water Flow Rate {m3/s, autosizable}; Nominal Capacity {W, autosizable, at design sink};
  - Sink Temperature Method (RadiativeBalance | Schedule); Sink Temperature Schedule;
  - Minimum Outlet Temperature (freeze protection / bypass setpoint) {C}; Sizing Factor.
- **Physics.** Follow `exobem/thermal_control.py`.
  - Sink temperature: `T_sink^4 = [alpha*(G_b+G_sky+G_gnd) + eps*sigma*(F_sky*T_sky^4 + F_gnd*T_gnd^4)] / (eps*sigma)`.
    `T_sky` is `state.dataEnvrn->SkyTemp` (2.7 K Moon, downwelling-equivalent Mars). `T_gnd` is the planetary regolith
    surface temperature (regolith audit; per-surface `SurfaceProperty:SurroundingSurfaces` ground temperature schedule
    if present, DataSurfaces.hh:1389).
  - Outlet temperature for a plug-flow fluid along a radiating area with no conduction along it:
    `m*cp*dT/dA = -eta*eps*sigma*(T^4 - Ts^4)`. Closed form
    `F(T) = [ln|(T-Ts)/(T+Ts)| - 2*atan(T/Ts)]/(4 Ts^3)`, so `F(T_out) = F(T_in) - eta*eps*sigma*A/(m*cp)`; solve with
    `General::SolveRoot` or Newton. Use a 20-segment explicit march as fallback when `|T-Ts|` is near 0. This also covers
    `T_in < T_sink` (the radiator heats the fluid).
  - Mars: add an optional convective term `h*(T - T_air)` from the planetary low-density convection model.
  - `Q = m*cp*(T_in - T_out)`.
  - Control: if `T_out < MinOutletTemp` or the loop setpoint, bypass a fraction of the flow (same pattern as cooling-tower
    fluid bypass in CondenserLoopTowers.cc) so the mixed outlet meets the setpoint. Report the bypass fraction.
- **Lift.** Do not put a heat pump inside the radiator. Use a water-cooled `Chiller:Electric:EIR` or
  `HeatPump:PlantLoop:EIR:Cooling` (water-source) between the cabin loop and the radiator condenser loop. This is the
  same architecture as `evaluate_thermal_control` (Carnot fraction gives an EIR curve).
- **Registration** (check each against FluidCooler_SingleSpd):
  - `Plant/Enums.hh` `PlantEquipmentType` (after :201);
  - `Plant/DataPlant.hh` name arrays (:140, :247 pattern);
  - `Plant/Component.hh` parallel arrays (isPump at :119-style entry = false; `CtrlType::CoolingOp` at :227-style entry);
  - `Plant/PlantManager.cc` factory switch (:1317-1330 pattern) and flow-control switch (:4266-4270 pattern:
    `ControlType::Active`, `TakesWhatGets`, `HowMet::PassiveCap`);
  - `DataLoopNode.hh` `ConnectionObjectType` (:287 pattern) and its name array;
  - `idd/Energy+.idd.in` (group "Condenser Equipment and Heat Exchangers");
  - CMakeLists.txt.
- **Reporting.** `SetupOutputVariable`: `Radiator Heat Transfer Rate [W]`, `Radiator Heat Transfer Energy [J]` (meter
  `EnergyTransfer`, end-use `HeatRejection`), `Radiator Sink Temperature [C]`, `Radiator Inlet/Outlet Temperature [C]`,
  `Radiator Mass Flow Rate [kg/s]`, `Radiator Bypass Fraction []`, `Radiator Mean Surface Temperature [C]`.
  `BaseSizer::reportSizerOutput` for area/flow/capacity. Add a predefined table row in the equipment summary
  (`pdchCTFC*`-style columns).
- **Sizing.** Use `PlantSizData` of the condenser loop (design exit temp and deltaT) and a user "design sink
  temperature" (or the worst-case sink over the sizing periods). Solve for the area if `Area = autosize` and capacity is
  given.
- **Prototype first** with `PlantComponent:UserDefined` + Python (H53). Its outputs become the unit-test oracle for the
  C++ component.

### 3.4 PV and storage (P1)

- **Photovoltaics.cc:1316.** Use `PVTimeStep = TimeStepZoneSec`.
- **`AbsoluteAirMass` (:1931).** Add a planetary branch before the Earth formula: vacuum gives `AMa = 0` and a flag that
  makes `SandiaF1` return the user AM0 factor (new optional field in `PhotovoltaicPerformance:Sandia`, default 1.0). On
  Mars, `AMa = (tau_column / tau_zenith) / cos z`, or F1 = 1 with a one-time warning.
- **New cell-integration mode `RadiativeEquilibrium`.**
  - Applies to `Generator:Photovoltaic`, for both TRNSYS (one-diode) and Sandia.
  - Steady form: solve `(tauAlpha - eta)*G = sigma*[eps_f*(F_sky,f(T^4-Tsky^4)+F_g,f(T^4-Tg^4)) + eps_b*(...)]`
    (Newton).
  - Dynamic form: add `C*dT/dt` using `TimeStepZoneSec`.
  - Reuse the Uhlleberg structure at :1350-1362.
  - On Earth the existing modes stay the default.
- **ElectricPowerServiceManager.cc.**
  - Introduce `Real64 dtHr = state.dataHVACGlobal->TimeStepSysSec / Constant::rSecsInHour;` and use it at :3353, 3358,
    3363, 3369, 3381, 3383, 3977-3980, 4033-4036, 4067-4072, 4150-4151.
  - On Earth `dtHr == TimeStepSys` exactly only if `TimeStepSysSec` is computed as `TimeStepSys*3600` with no rounding.
    Verify that it is bit-identical, or branch on `OffEarth`.
  - Li-ion without a zone is refused off-Earth (H43).
- **PVWatts.** Blocked (H40).

### 3.5 Ranking of equipment

**Works as-is** (indoor or closed-loop only; correct once 3.1 is in):
- Zone and air-loop equipment:
  - `ZoneHVAC:IdealLoadsAirSystem` without DSOA;
  - `ZoneHVAC:Baseboard:*` (electric, water, steam), `ZoneHVAC:HighTemperatureRadiant` (electric),
    `ZoneHVAC:LowTemperatureRadiant:*`, `ZoneHVAC:CoolingPanel:RadiantConvective:Water`;
  - `ZoneHVAC:FourPipeFanCoil`, `ZoneHVAC:UnitHeater`, `ZoneHVAC:WaterToAirHeatPump`, `ZoneHVAC:Dehumidifier:DX`;
  - `AirLoopHVAC` without an OA system (`Fan:*`, `Coil:Cooling:Water*`, `Coil:Heating:Electric/Water/Steam`,
    `Coil:*:WaterToAirHeatPump:*`, `AirTerminal:*` without OA), `Humidifier:Steam:Electric`;
  - `ZoneHVAC:*:UserDefined`.
- Plant:
  - `Pump:*`, `HeaderedPumps:*`, `Pipe:Adiabatic*`, `Pipe:Indoor`, `HeatExchanger:FluidToFluid`;
  - water-cooled `Chiller:Electric:EIR/ReformulatedEIR/Electric/ConstantCOP/ASHRAE205`, `Chiller:Absorption*`
    (water-cooled, steam/hot water driven), `CentralHeatPumpSystem`;
  - `HeatPump:WaterToWater:*`, `HeatPump:PlantLoop:EIR:*` water-source;
  - `Boiler:HotWater` (electric), `DistrictHeating/Cooling` (ideal utility);
  - `ThermalStorage:ChilledWater/HotWater` and `WaterHeater:*` with zone or schedule ambient (electric);
  - `LoadProfile:Plant`, `PlantComponent:UserDefined`, `WaterUse:*` (with scheduled mains);
  - `Refrigeration:Condenser:WaterCooled/Cascade`, water-cooled VRF.
- Electric:
  - `ElectricLoadCenter:Distribution`, `Storage:Simple`, inverters, converters, transformer.

**Works with planetary inputs or small fixes:**
- `Generator:Photovoltaic` + `PhotovoltaicPerformance:Simple` (needs planetary incident solar only).
- `:Sandia` (AM0 branch, cell temperature mode) and `:EquivalentOne-Diode` (cell temperature mode, `PVTimeStep`).
- `Storage:Battery` (dtHr) and `Storage:LiIonNMCBattery` (dtHr, zone required).
- `PlantComponent:TemperatureSource` (scheduled sink, e.g. radiator prototype).
- `GroundHeatExchanger:Vertical*/Slinky/HorizontalTrench` and `Pipe:Underground` (regolith ground model, time constants).
- `ThermalStorage:Ice:*` (hour constant).
- `GroundHeatExchanger:Surface` (h=0; better to use the radiator).
- Mars only: `Generator:WindTurbine` (CO2 density).
- New: `HeatRejection:Radiator`.

**Must be blocked (input error off-Earth):**
- Cooling towers, fluid coolers, evaporative fluid coolers, evaporative coolers, hybrid evaporative units.
- Air- or evap-cooled condensers in chillers, DX coils, VRF and refrigeration; air-source heat pumps (DX heating,
  `HeatPump:AirToWater*`, `HeatPump:PlantLoop:EIR` air-source).
- PTAC/PTHP/window AC, all outdoor-air systems, mixers and controllers, ERVs, OA units, DOAS; `OutdoorAir:Node` users in
  vacuum.
- Water heaters/HPWH with outdoor ambient or OA inlet; `Pipe:Outdoor`; `GroundHeatExchanger:Pond`; transpired/PVT
  collectors; combustion and fuel-cell generators; `Generator:PVWatts`; wind turbine on the Moon; outdoor-sensor setpoint
  managers and operation schemes; water-mains correlation.

## 4. Open questions / risks

1. **Option B semantics.** Option B redefines `OutBaroPress` off-Earth. Any module that is not blocked but really needs
   ambient pressure must read `AmbientPress` instead. The weather/convection/psychrometrics audits must confirm their
   lists. An inventory of `OutBaroPress` uses in non-HVAC files is needed: 523 total in 76 files, 169 of them outside the
   50 HVAC files counted here.
2. **Cabin gas properties.** Psychrometrics assumes dry air (R=287, cp=1004.84) and water-vapour partial pressure
   against total pressure. A 26.5 % O2 cabin at 70 kPa is within about 0.5 % for density. Moisture-saturation behaviour
   at 70 kPa is handled correctly by the existing Pb-dependent functions once they receive cabin pressure.
3. **DX/water-coil performance at reduced cabin density.** Curves are `f(T)` only. At 70 kPa a coil moves about 30 %
   less mass for the same face velocity. Users must size by mass. Is a density correction worth adding? (P2.)
4. **Chiller curves at radiator temperatures.** At lunar noon the condenser loop may need 60-100 C entering temperature
   (sink ~ 390 K regolith view). EIR curve extrapolation is unreliable, and curve limits will clamp silently. The radiator
   and heat-pump pair needs its own validated performance data, or a Carnot-fraction chiller option.
5. **Coolant freezing.** The radiator loop at lunar night freezes water and ethylene glycol. E+ does not model freezing
   or loop shutdown. We need a minimum-outlet bypass (3.3) and user-defined fluids with a low-temperature range; there is
   still a risk of nonsense if users keep "Water".
6. **Planetary hour and ssc.** ssc battery models assume `dt_hr` in physical hours (fixed by dtHr). Check that
   `lifetime_calendar_cycle_t` and the NMC calendar ageing use day counts tied to physical days (24 h). A Moon "day" in
   ssc would otherwise be 1/29.5 of a solar day.
7. **EMS limits.** EMS cannot change the sun path, the hour length, gravity, `StdRhoAir` or barometric pressure. It can
   only validate components (radiator via UserDefined plant, vacuum envelope via OSCM) at the Earth time base, so it is
   not a substitute for the core changes.
8. **Ideal loads to plant.** `ZoneHVAC:IdealLoadsAirSystem` has no plant connection. To size the radiator from ideal
   loads, use `LoadProfile:Plant` with an EMS/Python "Power" actuator (H54), or later add an optional "heat rejection
   plant connection" to ideal loads (P2).
9. **Validator coverage.** An object-type table can miss new or rare objects. The OA-node backstop (3.2) catches most,
   but air-cooled DX coils without a condenser node read `OutDryBulbTemp` directly (DXCoils.cc:9407-9411), so the
   field-level `condenser_type` check is essential.
