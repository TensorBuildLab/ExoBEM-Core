"""Apply the Thermonaut M1 hooks to the EnergyPlus v26.2.0 sources (idempotent, asserts every anchor).

Run from the repository root:  python planetary/tools/apply_hooks_m1.py
"""
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "EnergyPlus"
MARK = "Thermonaut"
INC = "#include <EnergyPlus/PlanetaryBody.hh>\n"


def edit(rel, old, new, include=True, count=1):
    p = SRC / rel
    s = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in s
    s = s.replace("\r\n", "\n")
    if new in s:
        return
    n = s.count(old)
    assert n == count, f"{rel}: anchor found {n} times (expected {count}):\n{old}"
    s = s.replace(old, new)
    if include and INC not in s and rel.endswith(".cc"):
        lines = s.split("\n")
        last = max(i for i, l in enumerate(lines) if l.startswith("#include <EnergyPlus/"))
        lines.insert(last + 1, INC.rstrip("\n"))
        s = "\n".join(lines)
    if crlf:
        s = s.replace("\n", "\r\n")
    p.write_bytes(s.encode("utf-8"))
    print("patched", rel)


# ---------------------------------------------------------------- state registration and build
edit("Data/EnergyPlusData.hh", "struct PhotovoltaicStateData;\n", "struct PhotovoltaicStateData;\nstruct PlanetaryData;\n", include=False)
edit("Data/EnergyPlusData.hh", "    std::unique_ptr<PhotovoltaicsData> dataPhotovoltaic;\n",
     "    std::unique_ptr<PhotovoltaicsData> dataPhotovoltaic;\n    std::unique_ptr<PlanetaryData> dataPlanet; // Thermonaut\n",
     include=False)
edit("Data/EnergyPlusData.cc", "#include <EnergyPlus/Data/EnergyPlusData.hh>\n",
     "#include <EnergyPlus/Data/EnergyPlusData.hh>\n#include <EnergyPlus/PlanetaryBody.hh> // Thermonaut\n", include=False)
edit("Data/EnergyPlusData.cc", "    this->dataPhotovoltaic = std::make_unique<PhotovoltaicsData>();\n",
     "    this->dataPhotovoltaic = std::make_unique<PhotovoltaicsData>();\n    this->dataPlanet = std::make_unique<PlanetaryData>();\n",
     include=False)
edit("Data/EnergyPlusData.cc", "    this->dataPhotovoltaic->clear_state();\n",
     "    this->dataPhotovoltaic->clear_state();\n    this->dataPlanet->clear_state();\n", include=False)
edit("Data/EnergyPlusData.cc", "    this->dataPhotovoltaic->init_constant_state(state);\n",
     "    this->dataPhotovoltaic->init_constant_state(state);\n    this->dataPlanet->init_constant_state(state);\n", include=False)
edit("Data/EnergyPlusData.cc", "    this->dataPhotovoltaic->init_state(state);\n",
     "    this->dataPhotovoltaic->init_state(state);\n    this->dataPlanet->init_state(state);\n", include=False)
edit("CMakeLists.txt", "    Photovoltaics.cc\n    Photovoltaics.hh\n",
     "    Photovoltaics.cc\n    Photovoltaics.hh\n    PlanetaryBody.cc\n    PlanetaryBody.hh\n", include=False)

# ---------------------------------------------------------------- input
edit("SimulationManager.cc", '        ErrorsFound = false;\n\n        CurrentModuleObject = "Version";\n',
     '        ErrorsFound = false;\n\n'
     '        // Thermonaut: planetary body first (it changes how the rest of the input is interpreted)\n'
     '        Planetary::GetInput(state);\n        Planetary::ValidateInput(state);\n\n'
     '        CurrentModuleObject = "Version";\n')

# ---------------------------------------------------------------- weather and sun
edit("WeatherManager.cc", "        ReadEPlusWeatherForDay(state, DayToRead, Environ, BackSpaceAfterRead);\n    }\n",
     "        ReadEPlusWeatherForDay(state, DayToRead, Environ, BackSpaceAfterRead);\n"
     "        // Thermonaut: overwrite the weather-file values with the planetary environment\n"
     "        Planetary::FillTomorrow(state, state.dataGlobal->BeginEnvrnFlag ? 1 : state.dataGlobal->DayOfSim + 1);\n    }\n")
edit("WeatherManager.cc",
     "        state.dataEnvrn->SinSolarDeclinAngle = state.dataWeather->TodayVariables.SinSolarDeclinAngle;\n    }\n",
     "        state.dataEnvrn->SinSolarDeclinAngle = state.dataWeather->TodayVariables.SinSolarDeclinAngle;\n"
     "        Planetary::AdvanceDay(state); // Thermonaut\n    }\n")
# psychrometrics of outdoor air are meaningless off-Earth (and the Moon "air" can be -180 C)
edit("WeatherManager.cc",
     "        // Humidity Ratio and Wet Bulb are derived\n        state.dataEnvrn->OutHumRat = Psychrometrics::PsyWFnTdbRhPb(",
     "        // Humidity Ratio and Wet Bulb are derived\n"
     "        if (!state.dataPlanet->active) { // Thermonaut: no outdoor moist air off-Earth\n"
     "        state.dataEnvrn->OutHumRat = Psychrometrics::PsyWFnTdbRhPb(")
edit("WeatherManager.cc",
     "        if (state.dataEnvrn->OutDewPointTemp > state.dataEnvrn->OutWetBulbTemp) {\n            state.dataEnvrn->OutDewPointTemp = state.dataEnvrn->OutWetBulbTemp;\n        }\n\n        if ((state.dataGlobal->KindOfSim == Constant::KindOfSim::DesignDay) ||",
     "        if (state.dataEnvrn->OutDewPointTemp > state.dataEnvrn->OutWetBulbTemp) {\n            state.dataEnvrn->OutDewPointTemp = state.dataEnvrn->OutWetBulbTemp;\n        }\n"
     "        } // Thermonaut\n\n        if ((state.dataGlobal->KindOfSim == Constant::KindOfSim::DesignDay) ||")
edit("WeatherManager.cc",
     "        state.dataEnvrn->OutEnthalpy = Psychrometrics::PsyHFnTdbW(state.dataEnvrn->OutDryBulbTemp, state.dataEnvrn->OutHumRat);\n"
     "        state.dataEnvrn->OutAirDensity =\n"
     "            Psychrometrics::PsyRhoAirFnPbTdbW(state, state.dataEnvrn->OutBaroPress, state.dataEnvrn->OutDryBulbTemp, state.dataEnvrn->OutHumRat);\n",
     "        if (!state.dataPlanet->active) { // Thermonaut\n"
     "        state.dataEnvrn->OutEnthalpy = Psychrometrics::PsyHFnTdbW(state.dataEnvrn->OutDryBulbTemp, state.dataEnvrn->OutHumRat);\n"
     "        state.dataEnvrn->OutAirDensity =\n"
     "            Psychrometrics::PsyRhoAirFnPbTdbW(state, state.dataEnvrn->OutBaroPress, state.dataEnvrn->OutDryBulbTemp, state.dataEnvrn->OutHumRat);\n"
     "        }\n"
     "        Planetary::SetCurrentWeather(state); // Thermonaut: ambient pressure, regolith, albedo\n")
# hour angle: 15 deg/h -> body rate (exactly 15.0 on Earth)
edit("WeatherManager.cc",
     "        Real64 H = (15.0 * (12.0 - (TimeValue + EqOfTime)) + (state.dataEnvrn->TimeZoneMeridian - state.dataEnvrn->Longitude)) * Constant::DegToRad;",
     "        Real64 H = (state.dataEnvrn->HourAngleRate * (12.0 - (TimeValue + EqOfTime)) + (state.dataEnvrn->TimeZoneMeridian - state.dataEnvrn->Longitude)) *\n"
     "                   Constant::DegToRad; // Thermonaut: rate = 15 deg/h on Earth")
edit("WeatherManager.cc",
     "            state.dataWeather->HrAngle = (15.0 * (12.0 - (state.dataGlobal->CurrentTime + state.dataWeather->TodayVariables.EquationOfTime)) +",
     "            state.dataWeather->HrAngle = (state.dataEnvrn->HourAngleRate * (12.0 - (state.dataGlobal->CurrentTime + state.dataWeather->TodayVariables.EquationOfTime)) +")
edit("WeatherManager.cc",
     "            state.dataWeather->HrAngle =\n                (15.0 *\n",
     "            state.dataWeather->HrAngle =\n                (state.dataEnvrn->HourAngleRate *\n")
edit("WeatherManager.cc",
     "        Real64 H = state.dataWeather->HrAngle * Constant::DegToRad;\n\n        // Compute the Cosine of the Solar Zenith (Altitude) Angle.",
     "        if (state.dataPlanet->active) { // Thermonaut: keep the hour angle in (-180, 180] for the azimuth sign\n"
     "            state.dataWeather->HrAngle = std::remainder(state.dataWeather->HrAngle, 360.0);\n        }\n"
     "        Real64 H = state.dataWeather->HrAngle * Constant::DegToRad;\n\n        // Compute the Cosine of the Solar Zenith (Altitude) Angle.")
edit("WeatherManager.cc",
     "            state.dataEnvrn->StdRhoAir = Psychrometrics::PsyRhoAirFnPbTdbW(\n"
     "                state, state.dataEnvrn->StdBaroPress, DataPrecisionGlobals::constant_twenty, DataPrecisionGlobals::constant_zero);\n",
     "            state.dataEnvrn->StdRhoAir = Psychrometrics::PsyRhoAirFnPbTdbW(\n"
     "                state, state.dataEnvrn->StdBaroPress, DataPrecisionGlobals::constant_twenty, DataPrecisionGlobals::constant_zero);\n"
     "            if (state.dataPlanet->active) { // Thermonaut: standard conditions are cabin conditions\n"
     "                state.dataEnvrn->StdBaroPress = state.dataPlanet->cabinPressure;\n"
     "                state.dataEnvrn->StdRhoAir = Psychrometrics::PsyRhoAirFnPbTdbW(\n"
     "                    state, state.dataEnvrn->StdBaroPress, DataPrecisionGlobals::constant_twenty, DataPrecisionGlobals::constant_zero);\n"
     "            }\n")

edit("SolarShading.cc",
     "    HrAngle = (15.0 * (12.0 - (CurrentTime + EqOfTime)) + (state.dataEnvrn->TimeZoneMeridian - state.dataEnvrn->Longitude));",
     "    HrAngle = (state.dataEnvrn->HourAngleRate * (12.0 - (CurrentTime + EqOfTime)) +\n"
     "               (state.dataEnvrn->TimeZoneMeridian - state.dataEnvrn->Longitude)); // Thermonaut: 15 deg/h on Earth")
edit("SolarShading.cc",
     "    if (state.dataSolarShading->ShadowingCalcFrequency <= 0) {\n        //  Set to default value\n        state.dataSolarShading->ShadowingCalcFrequency = 20;\n    }\n",
     "    if (state.dataSolarShading->ShadowingCalcFrequency <= 0) {\n        //  Set to default value\n        state.dataSolarShading->ShadowingCalcFrequency = 20;\n    }\n"
     "    if (state.dataPlanet->active) { // Thermonaut: the Earth-year shading average is meaningless off-Earth\n"
     "        state.dataSolarShading->ShadowingCalcFrequency = 1;\n    }\n")
edit("SolarShading.cc",
     "            //  Compute Period Values\n            AvgSinSolarDeclin = SumDec / double(state.dataSolarShading->ShadowingDaysLeft);\n"
     "            AvgCosSolarDeclin = std::sqrt(1.0 - pow_2(AvgSinSolarDeclin));\n"
     "            AvgEqOfTime = SumET / double(state.dataSolarShading->ShadowingDaysLeft);\n",
     "            //  Compute Period Values\n            AvgSinSolarDeclin = SumDec / double(state.dataSolarShading->ShadowingDaysLeft);\n"
     "            AvgCosSolarDeclin = std::sqrt(1.0 - pow_2(AvgSinSolarDeclin));\n"
     "            AvgEqOfTime = SumET / double(state.dataSolarShading->ShadowingDaysLeft);\n"
     "            if (state.dataPlanet->active) { // Thermonaut: today's planetary sun (daily update)\n"
     "                AvgSinSolarDeclin = state.dataWeather->TodayVariables.SinSolarDeclinAngle;\n"
     "                AvgCosSolarDeclin = state.dataWeather->TodayVariables.CosSolarDeclinAngle;\n"
     "                AvgEqOfTime = state.dataWeather->TodayVariables.EquationOfTime;\n            }\n")
edit("SolarShading.cc",
     "            SUN3(state.dataEnvrn->DayOfYear, AvgSinSolarDeclin, AvgEqOfTime);\n            AvgCosSolarDeclin = std::sqrt(1.0 - pow_2(AvgSinSolarDeclin));\n",
     "            SUN3(state.dataEnvrn->DayOfYear, AvgSinSolarDeclin, AvgEqOfTime);\n            AvgCosSolarDeclin = std::sqrt(1.0 - pow_2(AvgSinSolarDeclin));\n"
     "            if (state.dataPlanet->active) { // Thermonaut\n"
     "                AvgSinSolarDeclin = state.dataWeather->TodayVariables.SinSolarDeclinAngle;\n"
     "                AvgCosSolarDeclin = state.dataWeather->TodayVariables.CosSolarDeclinAngle;\n"
     "                AvgEqOfTime = state.dataWeather->TodayVariables.EquationOfTime;\n            }\n")
# isotropic sky off-Earth (exobem default); the Perez model is an Earth fit
edit("SolarShading.cc",
     "    F1 = max(0.0, F11R[i] + F12R[i] * Delta + F13R[i] * ZenithAng);\n    F2 = F21R[i] + F22R[i] * Delta + F23R[i] * ZenithAng;\n",
     "    F1 = max(0.0, F11R[i] + F12R[i] * Delta + F13R[i] * ZenithAng);\n    F2 = F21R[i] + F22R[i] * Delta + F23R[i] * ZenithAng;\n"
     "    if (state.dataPlanet->active) { // Thermonaut: isotropic diffuse sky off-Earth\n        F1 = 0.0;\n        F2 = 0.0;\n    }\n")

# ---------------------------------------------------------------- surfaces
edit("SurfaceGeometry.cc",
     "            state.dataSurface->SurfAirSkyRadSplit(SurfNum) = std::sqrt(0.5 * (1.0 + thisSurface.CosTilt));\n",
     "            state.dataSurface->SurfAirSkyRadSplit(SurfNum) = std::sqrt(0.5 * (1.0 + thisSurface.CosTilt));\n"
     "            if (state.dataPlanet->active) { // Thermonaut: no atmospheric long-wave split off-Earth\n"
     "                state.dataSurface->SurfAirSkyRadSplit(SurfNum) = 1.0;\n            }\n")
edit("ConvectionCoefficients.cc",
     "    Real64 TSky = state.dataEnvrn->SkyTempKelvin;\n    Real64 TGround = TAir;\n    HSrdSurf = 0.0;\n",
     "    Real64 TSky = state.dataEnvrn->SkyTempKelvin;\n    Real64 TGround = TAir;\n"
     "    if (state.dataPlanet->active) { // Thermonaut: ground long-wave from the regolith surface\n"
     "        TGround = state.dataPlanet->groundSurfCurrentC + Constant::Kelvin;\n    }\n    HSrdSurf = 0.0;\n")
edit("ConvectionCoefficients.cc",
     "    if (state.dataSurface->SurfEMSOverrideExtConvCoef(SurfNum)) {\n        HExt = state.dataSurface->SurfEMSValueForExtConvCoef(SurfNum);\n",
     "    if (state.dataPlanet->active) { // Thermonaut: vacuum (Moon) or thin CO2 (Mars) exterior convection\n"
     "        HExt = Planetary::exteriorConvection(state, SurfNum, TSurf, TAir);\n    }\n\n"
     "    if (state.dataSurface->SurfEMSOverrideExtConvCoef(SurfNum)) {\n        HExt = state.dataSurface->SurfEMSValueForExtConvCoef(SurfNum);\n")
edit("ConvectionCoefficients.cc",
     "                if (state.dataSurface->SurfEMSOverrideIntConvCoef(SurfNum)) {\n"
     "                    state.dataHeatBalSurf->SurfHConvInt(SurfNum) = state.dataSurface->SurfEMSValueForIntConvCoef(SurfNum);\n"
     "                    if (Surface(SurfNum).ExtBoundCond == DataSurfaces::KivaFoundation) {\n"
     "                        Real64 hConst = state.dataSurface->SurfEMSValueForIntConvCoef(SurfNum);\n"
     "                        state.dataSurfaceGeometry->kivaManager.surfaceConvMap[SurfNum].in = KIVA_CONST_CONV(hConst);\n"
     "                    }\n                }\n\n            } // for (surface)\n",
     "                if (state.dataPlanet->active) { // Thermonaut: cabin gas, cabin pressure, body gravity\n"
     "                    state.dataHeatBalSurf->SurfHConvInt(SurfNum) =\n"
     "                        Planetary::interiorConvection(state, SurfNum, SurfaceTemperatures(SurfNum), spaceMAT);\n                }\n\n"
     "                if (state.dataSurface->SurfEMSOverrideIntConvCoef(SurfNum)) {\n"
     "                    state.dataHeatBalSurf->SurfHConvInt(SurfNum) = state.dataSurface->SurfEMSValueForIntConvCoef(SurfNum);\n"
     "                    if (Surface(SurfNum).ExtBoundCond == DataSurfaces::KivaFoundation) {\n"
     "                        Real64 hConst = state.dataSurface->SurfEMSValueForIntConvCoef(SurfNum);\n"
     "                        state.dataSurfaceGeometry->kivaManager.surfaceConvMap[SurfNum].in = KIVA_CONST_CONV(hConst);\n"
     "                    }\n                }\n\n            } // for (surface)\n")
edit("HeatBalanceSurfaceManager.cc",
     "    Real64 TSky = state.dataEnvrn->SkyTemp;\n    Real64 TGround = state.dataEnvrn->OutDryBulbTemp;\n    Real64 TSrdSurfs = 0.0;\n",
     "    Real64 TSky = state.dataEnvrn->SkyTemp;\n"
     "    Real64 TGround = Planetary::groundLongwaveTempC(state, state.dataEnvrn->OutDryBulbTemp); // Thermonaut\n    Real64 TSrdSurfs = 0.0;\n")
edit("HeatBalFiniteDiffManager.cc",
     "            } else {\n                Tgndsurface = state.dataMstBal->TempOutsideAirFD(Surf);\n            }\n",
     "            } else {\n                Tgndsurface = Planetary::groundLongwaveTempC(state, state.dataMstBal->TempOutsideAirFD(Surf)); // Thermonaut\n            }\n")
edit("HeatBalFiniteDiffManager.cc",
     "        auto &minTempLimit = DataHeatBalSurface::MinSurfaceTempLimit;\n",
     "        // Thermonaut: lunar night surfaces reach -180 C; keep only a physical floor off-Earth\n"
     "        Real64 const minTempLimit = state.dataPlanet->active ? -270.0 : DataHeatBalSurface::MinSurfaceTempLimit;\n")

# ---------------------------------------------------------------- Earth-only sanity checks
edit("DataHeatBalance.cc", "        if (minBulb < -100.0) {\n            SetOutBulbTempAt_error(state, \"Zone\",",
     "        if (minBulb < -100.0 && !state.dataPlanet->active) { // Thermonaut\n            SetOutBulbTempAt_error(state, \"Zone\",")
edit("DataSurfaces.cc", "        if (minBulb < -100.0) {\n            SetOutBulbTempAt_error(state, \"Surface\",",
     "        if (minBulb < -100.0 && !state.dataPlanet->active) { // Thermonaut\n            SetOutBulbTempAt_error(state, \"Surface\",")
edit("DataEnvironment.cc", "    if (LocalOutDryBulbTemp < -100.0) {",
     "    if (LocalOutDryBulbTemp < -100.0 && !state.dataPlanet->active) { // Thermonaut")
edit("DataEnvironment.cc", "    if (LocalOutWetBulbTemp < -100.0) {",
     "    if (LocalOutWetBulbTemp < -100.0 && !state.dataPlanet->active) { // Thermonaut")
print("done")
