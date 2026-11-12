"""Thermonaut M2e patch set: physical checks of planetary weather (PWF) files, and validator gaps closed after every
audit finding was traced to the code (planetary/audit/inventory): windows, SimpleCombined outside convection,
air-cooled and outdoor-air equipment, ground models, collectors, per-surface HAMT, CO2 balance, one step per hour,
unscheduled water mains, and a backstop that stops a planetary run if any outdoor-air node exists.

Run from the repository root:  python planetary/tools/apply_hooks_m2e.py   (idempotent)

The PWF reader already checks the body, the required columns, equal record spacing and coverage of the run period.
M2e adds physical range checks on every record (no Earth ranges): irradiance 0-2000 W/m2, temperatures 2.7-1000 K,
albedo 0-1, pressure 0-200 kPa, wind 0-100 m/s, a positive record length, and no missing values except the air
temperature, which is "nan" in vacuum.  A violation stops the run with the record number.  Earth runs never reach
this code.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
C = ROOT / "src" / "EnergyPlus" / "PlanetaryBody.cc"


def edit(path, old, new, marker):
    p = Path(path)
    s = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in s
    s = s.replace("\r\n", "\n")
    if marker in s:
        return
    assert s.count(old) == 1, (p.name, s.count(old), old[:120])
    s = s.replace(old, new)
    if crlf:
        s = s.replace("\n", "\r\n")
    p.write_bytes(s.encode("utf-8"))


OLD = """        for (size_t i = 1; i < p.pwfTime.size(); ++i) {
            if (std::abs(p.pwfTime[i] - p.pwfTime[i - 1] - p.pwfDt) > 1e-6 * p.pwfDt) {
"""
NEW = """        // Thermonaut M2e: physical checks only (no Earth ranges); "nan" is allowed only for the air temperature (vacuum)
        if (!(p.pwfDt > 0.0)) {
            ShowFatalError(state, std::format("Site:PlanetaryBody: weather file {} has a non-positive timestep_s", full.string()));
        }
        auto checkColumn = [&](std::vector<Real64> const &c, std::string_view name, Real64 lo, Real64 hi, bool nanAllowed) {
            for (size_t i = 0; i < c.size(); ++i) {
                Real64 const v = c[i];
                if (std::isnan(v)) {
                    if (!nanAllowed) {
                        ShowFatalError(state,
                                       std::format("Site:PlanetaryBody: weather file {}: {} is missing (nan) in record {}", full.string(), name, i + 1));
                    }
                    continue;
                }
                if (v < lo || v > hi) {
                    ShowFatalError(state,
                                   std::format("Site:PlanetaryBody: weather file {}: {} = {:g} in record {} is outside the physical range [{:g}, {:g}]",
                                               full.string(),
                                               name,
                                               v,
                                               i + 1,
                                               lo,
                                               hi));
                }
            }
        };
        checkColumn(p.pwfDni, "dni_W_m2", 0.0, 2000.0, false);
        checkColumn(p.pwfDhi, "dhi_W_m2", 0.0, 2000.0, false);
        checkColumn(p.pwfTsky, "T_sky_K", 2.7, 1000.0, false);
        checkColumn(p.pwfTair, "T_air_K", 2.7, 1000.0, true);
        checkColumn(p.pwfTground, "T_ground_K", 2.7, 1000.0, false);
        checkColumn(p.pwfTdeep, "T_deep_K", 2.7, 1000.0, false);
        checkColumn(p.pwfAlbedo, "ground_albedo", 0.0, 1.0, false);
        checkColumn(p.pwfPress, "pressure_Pa", 0.0, 2.0e5, false);
        checkColumn(p.pwfWind, "wind_m_s", 0.0, 100.0, false);
        for (size_t i = 1; i < p.pwfTime.size(); ++i) {
            if (std::abs(p.pwfTime[i] - p.pwfTime[i - 1] - p.pwfDt) > 1e-6 * p.pwfDt) {
"""
edit(C, OLD, NEW, "Thermonaut M2e:")

# Validator gaps found when every audit finding was traced to the code (planetary/audit/inventory):
#  - outside convection SimpleCombined folds radiation into h and zeroes the sky/ground/air split (S32)
#  - DElight via Daylighting:Controls, EcoRoof, ground heat exchangers, solar collectors, Sandia PV in any mode,
#    and water mains from the Earth air-temperature correlation (S18, S33, S37, T25, T30)
#  - one time step per hour: the engine evaluates the sun at mid-hour, the generator at the end of the step (T23/S09)
OLD2 = """    if (errors) ShowFatalError(state, "Site:PlanetaryBody: unsupported objects for a planetary simulation; program terminates.");
"""
NEW2 = """    // Thermonaut M2e validator: gaps found by the audit traceability pass
    static constexpr std::array<std::pair<std::string_view, std::string_view>, 28> blocked2 = {{
        {"ZoneHVAC:OutdoorAirUnit", "it draws outdoor air"},
        {"ZoneHVAC:UnitVentilator", "it draws outdoor air"},
        {"ZoneHVAC:VentilatedSlab", "it draws outdoor air"},
        {"ZoneHVAC:EnergyRecoveryVentilator", "it exchanges air with the outdoors"},
        {"ZoneHVAC:HybridUnitaryHVAC", "its performance tables use outdoor air"},
        {"Coil:Cooling:DX:TwoStageWithHumidityControlMode", "the condenser rejects heat to outdoor air"},
        {"Coil:Cooling:DX:SingleSpeed:ThermalStorage", "the condenser rejects heat to outdoor air"},
        {"AirConditioner:VariableRefrigerantFlow:FluidTemperatureControl", "the outdoor unit rejects heat to outdoor air"},
        {"AirConditioner:VariableRefrigerantFlow:FluidTemperatureControl:HR", "the outdoor unit rejects heat to outdoor air"},
        {"Generator:MicroCHP", "it needs combustion air"},
        {"Pipe:Underground", "it uses Earth ground-temperature models"},
        {"FenestrationSurface:Detailed", "windows are not supported in this version (the window solvers assume air at 1 g)"},
        {"Window", "windows are not supported in this version (the window solvers assume air at 1 g)"},
        {"GlazedDoor", "windows are not supported in this version (the window solvers assume air at 1 g)"},
        {"Window:Interzone", "windows are not supported in this version (the window solvers assume air at 1 g)"},
        {"GlazedDoor:Interzone", "windows are not supported in this version (the window solvers assume air at 1 g)"},
        {"Material:RoofVegetation", "the EcoRoof model needs outdoor air and Earth weather"},
        {"GroundHeatExchanger:System", "ground heat exchangers use Earth ground-temperature models"},
        {"GroundHeatExchanger:Pond", "pond heat exchangers need outdoor air and water"},
        {"GroundHeatExchanger:Surface", "ground heat exchangers use Earth ground-temperature models"},
        {"GroundHeatExchanger:HorizontalTrench", "ground heat exchangers use Earth ground-temperature models"},
        {"GroundHeatExchanger:Slinky", "ground heat exchangers use Earth ground-temperature models"},
        {"PipingSystem:Underground:Domain", "the ground domain uses Earth ground-temperature models and outdoor air"},
        {"SolarCollector:FlatPlate:Water", "the collector loss model is fitted to Earth air"},
        {"SolarCollector:FlatPlate:PhotovoltaicThermal", "the collector loss model is fitted to Earth air"},
        {"SolarCollector:UnglazedTranspired", "the transpired collector draws outdoor air"},
        {"SolarCollector:IntegralCollectorStorage", "the collector loss model is fitted to Earth air"},
        {"PhotovoltaicPerformance:Sandia", "the Sandia model uses the Earth air-mass spectral correction in every mode"},
    }};
    for (auto const &[obj, why] : blocked2) {
        if (ip->getNumObjectsFound(state, std::string(obj)) > 0) {
            ShowSevereError(state, std::format("Site:PlanetaryBody: {} objects are not supported off-Earth ({}).", obj, why));
            errors = true;
        }
    }
    auto const upper = [](auto const &v) { return v.is_string() ? Util::makeUPPER(v.get<std::string>()) : std::string(); };
    for (std::string const obj : {"Chiller:Electric:EIR", "Chiller:Electric", "Chiller:ConstantCOP", "Chiller:EngineDriven", "Chiller:CombustionTurbine"}) {
        auto const ch = ip->epJSON.find(obj);
        if (ch == ip->epJSON.end()) continue;
        bool const defaultAir = obj != "Chiller:Electric:EIR";
        for (auto const &inst : ch.value().items()) {
            std::string const ct = inst.value().count("condenser_type") ? upper(inst.value().at("condenser_type")) : (defaultAir ? "AIRCOOLED" : "WATERCOOLED");
            if (ct != "WATERCOOLED") {
                ShowSevereError(state, std::format("Site:PlanetaryBody: {} {}: air- and evaporatively cooled condensers are not supported off-Earth; "
                                                   "use Condenser Type = WaterCooled on a plant loop.", obj, inst.key()));
                errors = true;
            }
        }
    }
    for (std::string const obj : {"WaterHeater:HeatPump:PumpedCondenser", "WaterHeater:HeatPump:WrappedCondenser"}) {
        auto const hp = ip->epJSON.find(obj);
        if (hp == ip->epJSON.end()) continue;
        for (auto const &inst : hp.value().items()) {
            if (!inst.value().count("inlet_air_configuration") || upper(inst.value().at("inlet_air_configuration")) != "ZONEAIRONLY") {
                ShowSevereError(state, std::format("Site:PlanetaryBody: {} {}: only Inlet Air Configuration = ZoneAirOnly is supported off-Earth.", obj, inst.key()));
                errors = true;
            }
        }
    }
    auto const sca = ip->epJSON.find("SurfaceConvectionAlgorithm:Outside");
    if (sca != ip->epJSON.end()) {
        for (auto const &inst : sca.value().items()) {
            if (inst.value().count("algorithm") && upper(inst.value().at("algorithm")) == "SIMPLECOMBINED") {
                ShowSevereError(state, "Site:PlanetaryBody: SurfaceConvectionAlgorithm:Outside SimpleCombined is not supported off-Earth (it folds "
                                       "sky and ground radiation into an Earth convection coefficient); use DOE-2, TARP or MoWiTT, which the "
                                       "planetary exterior model replaces.");
                errors = true;
            }
        }
    }
    for (std::string const obj : {"SurfaceProperty:ConvectionCoefficients", "SurfaceProperty:ConvectionCoefficients:MultipleSurface"}) {
        auto const cc = ip->epJSON.find(obj);
        if (cc == ip->epJSON.end()) continue;
        for (auto const &inst : cc.value().items()) {
            for (auto const &f : inst.value().items()) {
                if (upper(f.value()) == "SIMPLECOMBINED") {
                    ShowSevereError(state, std::format("Site:PlanetaryBody: {} {}: SimpleCombined coefficients are not supported off-Earth.", obj, inst.key()));
                    errors = true;
                }
            }
        }
    }
    auto const dl = ip->epJSON.find("Daylighting:Controls");
    if (dl != ip->epJSON.end()) {
        for (auto const &inst : dl.value().items()) {
            if (inst.value().count("daylighting_method") && upper(inst.value().at("daylighting_method")) == "DELIGHT") {
                ShowSevereError(state, std::format("Site:PlanetaryBody: Daylighting:Controls {}: the DElight method uses an Earth sky model; use SplitFlux.",
                                                   inst.key()));
                errors = true;
            }
        }
    }
    bool hasWater = false;
    for (std::string const obj : {"WaterUse:Equipment", "WaterHeater:Mixed", "WaterHeater:Stratified"}) {
        if (ip->getNumObjectsFound(state, obj) > 0) hasWater = true;
    }
    if (hasWater) {
        bool scheduled = false;
        auto const wm = ip->epJSON.find("Site:WaterMainsTemperature");
        if (wm != ip->epJSON.end()) {
            for (auto const &inst : wm.value().items()) {
                if (inst.value().count("calculation_method") && upper(inst.value().at("calculation_method")) == "SCHEDULE") scheduled = true;
            }
        }
        if (!scheduled) {
            ShowSevereError(state, "Site:PlanetaryBody: water-use and water-heater objects need Site:WaterMainsTemperature with Calculation Method = "
                                   "Schedule off-Earth (the default correlation uses the Earth outdoor air temperature).");
            errors = true;
        }
    }
    auto const ts = ip->epJSON.find("Timestep");
    if (ts != ip->epJSON.end()) {
        for (auto const &inst : ts.value().items()) {
            auto const n = inst.value().find("number_of_timesteps_per_hour");
            if (n != inst.value().end() && n.value().is_number() && n.value().get<double>() < 1.5) {
                ShowSevereError(state, "Site:PlanetaryBody: one time step per hour is not supported off-Earth (EnergyPlus then evaluates the sun at "
                                       "mid-hour while the planetary environment is evaluated at the end of the step); use at least 2.");
                errors = true;
            }
        }
    }
    if (errors) ShowFatalError(state, "Site:PlanetaryBody: unsupported objects for a planetary simulation; program terminates.");
"""
NL = "\n"
src = C.read_bytes().decode("utf-8").replace("\r\n", NL)
line = '                                                                 "Chiller:Electric:EIR",' + NL
if line in src:
    # water-cooled EIR chillers stay allowed (the condenser-type check below refuses air- and evaporatively cooled ones)
    edit(C, line, "", "@@never@@")
    edit(C, "std::array<std::string_view, 58> blocked =", "std::array<std::string_view, 57> blocked =", "std::array<std::string_view, 57> blocked =")
edit(C, OLD2, NEW2, "Thermonaut M2e validator")

# Backstop: an outdoor-air node that any component registers by itself stops the run at the start of the next day
OLD3 = """void AdvanceDay(EnergyPlusData &state)
{
    auto &p = *state.dataPlanet;
    if (!p.active) return;
"""
NEW3 = OLD3 + """    // Thermonaut M2e backstop: no component may use outdoor air off-Earth, whether or not its object type is listed
    if (state.dataOutAirNodeMgr->NumOutsideAirNodes > 0) {
        ShowSevereError(state, std::format("Site:PlanetaryBody: {} outdoor-air node(s) were created, first {}; components that draw or reject "
                                           "heat to outdoor air are not supported off-Earth.",
                                           state.dataOutAirNodeMgr->NumOutsideAirNodes,
                                           state.dataLoopNodes->NodeID(state.dataOutAirNodeMgr->OutsideAirNodeList(1))));
        ShowFatalError(state, "Site:PlanetaryBody: outdoor air is not available on this body; program terminates.");
    }
"""
edit(C, OLD3, NEW3, "Thermonaut M2e backstop")
inc_old = "#include <EnergyPlus/DataSurfaces.hh>" + NL
inc_new = inc_old + "#include <EnergyPlus/DataLoopNode.hh>" + NL + "#include <EnergyPlus/OutAirNodeManager.hh>" + NL
edit(C, inc_old, inc_new, "#include <EnergyPlus/OutAirNodeManager.hh>")

# Further gaps from areas 03-04 of the traceability pass (G02, G04, M03, PRS-07, S15, ZHB-04)
NEW4 = """    // Thermonaut M2e validator 2: ground models, per-surface HAMT, air-source plant heat pumps, movable insulation, CO2
    static constexpr std::array<std::pair<std::string_view, std::string_view>, 12> blocked3 = {{
        {"HeatPump:AirToWater", "the source side is outdoor air"},
        {"HeatPump:AirToWater:FuelFired:Heating", "the source side is outdoor air and it needs combustion air"},
        {"HeatPump:AirToWater:FuelFired:Cooling", "the source side is outdoor air and it needs combustion air"},
        {"Refrigeration:Condenser:AirCooled", "the condenser rejects heat to outdoor air"},
        {"Refrigeration:Condenser:EvaporativeCooled", "the condenser rejects heat to outdoor air"},
        {"Refrigeration:GasCooler:AirCooled", "the gas cooler rejects heat to outdoor air"},
        {"Generator:MicroCHP", "it needs combustion air"},
        {"Construction:FfactorGroundFloor", "F-factor constructions assume Earth ground temperatures"},
        {"Construction:CfactorUndergroundWall", "C-factor constructions assume Earth ground temperatures"},
        {"Site:GroundDomain:Slab", "the ground domain uses Earth ground-temperature models"},
        {"Site:GroundDomain:Basement", "the ground domain uses Earth ground-temperature models"},
        {"SurfaceControl:MovableInsulation", "movable insulation keeps the Earth long-wave treatment"},
    }};
    for (auto const &[obj, why] : blocked3) {
        if (ip->getNumObjectsFound(state, std::string(obj)) > 0) {
            ShowSevereError(state, std::format("Site:PlanetaryBody: {} objects are not supported off-Earth ({}).", obj, why));
            errors = true;
        }
    }
    for (std::string const obj : {"SurfaceProperty:HeatTransferAlgorithm", "SurfaceProperty:HeatTransferAlgorithm:Construction",
                                  "SurfaceProperty:HeatTransferAlgorithm:SurfaceList"}) {
        auto const ha = ip->epJSON.find(obj);
        if (ha == ip->epJSON.end()) continue;
        for (auto const &inst : ha.value().items()) {
            if (inst.value().count("algorithm")) {
                std::string const a = upper(inst.value().at("algorithm"));
                if (a != "CONDUCTIONTRANSFERFUNCTION" && a != "CONDUCTIONFINITEDIFFERENCE") {
                    ShowSevereError(state, std::format("Site:PlanetaryBody: {} {}: only ConductionTransferFunction and ConductionFiniteDifference are "
                                                       "supported off-Earth.", obj, inst.key()));
                    errors = true;
                }
            }
        }
    }
    for (std::string const obj : {"HeatPump:PlantLoop:EIR:Cooling", "HeatPump:PlantLoop:EIR:Heating"}) {
        auto const hp = ip->epJSON.find(obj);
        if (hp == ip->epJSON.end()) continue;
        for (auto const &inst : hp.value().items()) {
            if (inst.value().count("condenser_type") && upper(inst.value().at("condenser_type")) == "AIRSOURCE") {
                ShowSevereError(state, std::format("Site:PlanetaryBody: {} {}: air-source heat pumps are not supported off-Earth.", obj, inst.key()));
                errors = true;
            }
        }
    }
    auto const zcb = ip->epJSON.find("ZoneAirContaminantBalance");
    if (zcb != ip->epJSON.end()) {
        for (auto const &inst : zcb.value().items()) {
            if (inst.value().count("carbon_dioxide_concentration") && upper(inst.value().at("carbon_dioxide_concentration")) == "YES") {
                ShowSevereError(state, "Site:PlanetaryBody: ZoneAirContaminantBalance with Carbon Dioxide Concentration = Yes is not supported "
                                       "off-Earth (the CO2 balance assumes standard-pressure air).");
                errors = true;
            }
        }
    }
"""
edit(C, OLD2, NEW4 + OLD2, "Thermonaut M2e validator 2")
print("M2e applied")
