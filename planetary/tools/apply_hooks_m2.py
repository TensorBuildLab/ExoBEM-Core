"""ExoBEM-Core M2a patch set: planetary weather files (PWF), PV cell temperature in vacuum, more input checks.

Run from the repository root:  python planetary/tools/apply_hooks_m2.py   (idempotent)

* Site:PlanetaryBody gets an optional field "Planetary Weather File Name" (PWF, docs: ExoBEM
  docs/weather_format.md). When given, sun, sky, ambient and regolith values are read from it instead of
  being generated, and the user does not need an EPW: a calendar-only EPW is written to the output folder.
* The equivalent one-diode PV model (Decoupled mode) computes the cell temperature from a radiative (Moon) or
  radiative + convective (Mars) energy balance instead of the NOCT relation for Earth air.
* The validator refuses PV temperature models that are fitted to Earth air (Sandia Decoupled, Ulleberg
  dynamic) and Li-ion batteries without a zone (they would use the outdoor air temperature).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "EnergyPlus"


def edit(path, old, new, marker=None):
    p = Path(path)
    s = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in s
    s = s.replace("\r\n", "\n")
    if (marker or new) in s:
        return
    assert s.count(old) == 1, (str(p), s.count(old), old[:120])
    s = s.replace(old, new)
    if crlf:
        s = s.replace("\n", "\r\n")
    p.write_bytes(s.encode("utf-8"))
    print("patched", p.name)


# ------------------------------------------------------------------------------------------------ IDD
edit(ROOT / "idd" / "Energy+.idd.in",
     '''  N19; \\field Mars Diurnal Wind Speed Amplitude
       \\units m/s
       \\type real
       \\minimum 0.0
       \\default 2.0
''',
     '''  N19, \\field Mars Diurnal Wind Speed Amplitude
       \\units m/s
       \\type real
       \\minimum 0.0
       \\default 2.0
  A5; \\field Planetary Weather File Name
       \\type alpha
       \\retaincase
       \\note Optional planetary weather file in the PWF format (written by ExoBEM: exobem weather ...).
       \\note When given, solar, sky, ambient and regolith values are read from it instead of being generated,
       \\note and no EPW is needed: a calendar-only EPW is written to the output folder and used for the dates.
       \\note The file must cover the run period. Relative paths are searched like other input files.
''', marker="Planetary Weather File Name")

# ------------------------------------------------------------------------------------------------ header
H = SRC / "PlanetaryBody.hh"
edit(H, "#include <vector>\n", "#include <string>\n#include <vector>\n", marker="#include <string>\n#include <vector>")
edit(H, "    Real64 groundLongwaveTempC(EnergyPlusData const &state, Real64 defaultC);\n",
     "    Real64 groundLongwaveTempC(EnergyPlusData const &state, Real64 defaultC);\n"
     "    // Cell temperature [K] of a PV module on surface surfNum off-Earth: both faces radiate to sky and regolith,\n"
     "    // plus convection in the Martian atmosphere; qNet = absorbed solar minus electric output [W/m2].\n"
     "    Real64 pvCellTemperatureK(EnergyPlusData &state, int surfNum, Real64 qNet);\n", marker="pvCellTemperatureK")
edit(H, "    bool condFDCorrected = false; // CondFD start-up profile corrected after warm-up\n",
     "    bool condFDCorrected = false; // CondFD start-up profile corrected after warm-up\n"
     "\n"
     "    // Planetary weather file (PWF); empty path = generate the environment\n"
     "    std::string pwfPath;\n"
     "    Real64 pwfJd0 = 0.0; // JD (UTC) of the file's start_utc\n"
     "    Real64 pwfDt = 0.0;  // record length [s]\n"
     "    std::vector<Real64> pwfTime, pwfDni, pwfDhi, pwfTsky, pwfTair, pwfTground, pwfTdeep, pwfAlbedo, pwfPress, pwfWind, pwfLdown, pwfLs,\n"
     "        pwfTau;\n", marker="std::string pwfPath;")

# ------------------------------------------------------------------------------------------------ module
C = SRC / "PlanetaryBody.cc"
edit(C, "#include <algorithm>\n#include <array>\n#include <format>\n#include <cmath>\n#include <string>\n",
     "#include <algorithm>\n#include <array>\n#include <cstdio>\n#include <format>\n#include <cmath>\n#include <fstream>\n#include <limits>\n#include <map>\n"
     "#include <sstream>\n#include <string>\n", marker="#include <fstream>")
edit(C, "#include <EnergyPlus/DataSurfaces.hh>\n",
     "#include <EnergyPlus/DataStringGlobals.hh>\n#include <EnergyPlus/DataSurfaces.hh>\n#include <EnergyPlus/DataSystemVariables.hh>\n"
     "#include <EnergyPlus/FileSystem.hh>\n", marker="#include <EnergyPlus/DataSystemVariables.hh>")

# read the file name in GetInput
edit(C, '''        p.windAmplitude = ip->getRealFieldValue(f, props, "mars_diurnal_wind_speed_amplitude");
''', '''        p.windAmplitude = ip->getRealFieldValue(f, props, "mars_diurnal_wind_speed_amplitude");
        auto const wf = f.find("planetary_weather_file_name");
        if (wf != f.end() && wf.value().is_string()) p.pwfPath = wf.value().get<std::string>();
''', marker='f.find("planetary_weather_file_name")')
edit(C, '''    state.dataEnvrn->HourAngleRate = p.hourAngleRate;
    if (p.horizonDeg < 0.0) {''', '''    state.dataEnvrn->HourAngleRate = p.hourAngleRate;
    if (!p.pwfPath.empty()) readPlanetaryWeatherFile(state);
    if (p.horizonDeg < 0.0) {''', marker="if (!p.pwfPath.empty()) readPlanetaryWeatherFile(state);")

READER = r'''// ---------------------------------------------------------------------------------------------- planetary weather file
namespace {
    std::vector<std::string> splitCsv(std::string const &line)
    {
        std::vector<std::string> out;
        std::stringstream ss(line);
        std::string item;
        while (std::getline(ss, item, ',')) {
            while (!item.empty() && (item.back() == '\r' || item.back() == ' ')) item.pop_back();
            out.push_back(item);
        }
        return out;
    }

    // Write a calendar-only EPW (every weather value is replaced) so that the engine's run-period machinery works
    void writeCalendarEpw(EnergyPlusData &state, fs::path const &path, Real64 lat, Real64 lon, int year)
    {
        std::ofstream o(path);
        o << std::format("LOCATION,ExoBEM-Core planetary site,-,-,PWF calendar,000000,{:.4f},{:.4f},{:.1f},0.0\n", lat, lon,
                         std::round(lon / 15.0));
        o << "DESIGN CONDITIONS,0\nTYPICAL/EXTREME PERIODS,0\nGROUND TEMPERATURES,0\nHOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0\n";
        o << "COMMENTS 1,Calendar only: ExoBEM-Core reads every weather value from the planetary weather file\nCOMMENTS 2,\n";
        o << "DATA PERIODS,1,1,Data,Sunday, 1/ 1,12/31\n";
        static constexpr std::array<int, 12> mdays = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
        for (int m = 1; m <= 12; ++m) {
            for (int d = 1; d <= mdays[m - 1]; ++d) {
                for (int h = 1; h <= 24; ++h) {
                    o << std::format("{},{},{},{},60,-,20.0,5.0,40,101325,0,0,300,0,0,0,0,0,0,0,180,0.0,0,0,9999,77777,9,999999999,0,0.0,0,88,"
                                     "0.000,0.0,0.0\n",
                                     year, m, d, h);
                }
            }
        }
        if (!o.good()) ShowFatalError(state, std::format("Site:PlanetaryBody: could not write the calendar EPW {}", path.string()));
    }

    void readPlanetaryWeatherFile(EnergyPlusData &state)
    {
        auto &p = *state.dataPlanet;
        fs::path const full = DataSystemVariables::CheckForActualFilePath(state, fs::path(p.pwfPath), "Site:PlanetaryBody");
        if (full.empty()) ShowFatalError(state, std::format("Site:PlanetaryBody: planetary weather file not found: {}", p.pwfPath));
        std::ifstream in(full);
        std::string line;
        std::getline(in, line);
        if (line.rfind("# PWF", 0) != 0) {
            ShowFatalError(state, std::format("Site:PlanetaryBody: {} is not a PWF planetary weather file (first line must start with '# PWF')",
                                              full.string()));
        }
        std::map<std::string, std::string> head;
        std::vector<std::string> cols;
        while (std::getline(in, line)) {
            if (line.empty()) continue;
            if (line[0] == '#') {
                auto const c = line.find(':');
                if (c == std::string::npos) continue;
                std::string k = line.substr(1, c - 1), v = line.substr(c + 1);
                auto trim = [](std::string &x) {
                    x.erase(0, x.find_first_not_of(" \t\r"));
                    x.erase(x.find_last_not_of(" \t\r") + 1);
                };
                trim(k);
                trim(v);
                head[k] = v;
            } else {
                cols = splitCsv(line);
                break;
            }
        }
        std::map<std::string, std::vector<Real64>> data;
        for (auto const &c : cols) data[c];
        while (std::getline(in, line)) {
            if (line.empty() || line[0] == '#') continue;
            auto const v = splitCsv(line);
            if (v.size() != cols.size()) ShowFatalError(state, std::format("Site:PlanetaryBody: malformed record in {}: {}", full.string(), line));
            for (size_t j = 0; j < cols.size(); ++j) {
                data[cols[j]].push_back((v[j] == "nan" || v[j] == "NaN") ? std::numeric_limits<Real64>::quiet_NaN() : std::stod(v[j]));
            }
        }
        std::string const body = Util::makeUPPER(head["body"]);
        if ((p.body == Body::Moon && body != "MOON") || (p.body == Body::Mars && body != "MARS")) {
            ShowFatalError(state, std::format("Site:PlanetaryBody: the weather file {} is for body '{}', not the Body of this object", full.string(),
                                              head["body"]));
        }
        static constexpr std::array<std::string_view, 11> required = {"time_s", "dni_W_m2", "dhi_W_m2", "T_sky_K", "T_air_K", "T_ground_K",
                                                                      "T_deep_K", "ground_albedo", "pressure_Pa", "wind_m_s", "zenith_deg"};
        for (auto const &r : required) {
            if (data.find(std::string(r)) == data.end() || data[std::string(r)].empty()) {
                ShowFatalError(state, std::format("Site:PlanetaryBody: weather file {} lacks the required column {}", full.string(), r));
            }
        }
        int Y = 0, M = 0, D = 0, h = 0, mi = 0, se = 0;
        if (std::sscanf(head["start_utc"].c_str(), "%d-%d-%dT%d:%d:%d", &Y, &M, &D, &h, &mi, &se) < 3) {
            ShowFatalError(state, std::format("Site:PlanetaryBody: bad start_utc '{}' in {}", head["start_utc"], full.string()));
        }
        p.pwfJd0 = julianDate(Y, M, D) + (h + mi / 60.0 + se / 3600.0) / 24.0;
        p.pwfDt = std::stod(head["timestep_s"]);
        p.pwfTime = data["time_s"];
        p.pwfDni = data["dni_W_m2"];
        p.pwfDhi = data["dhi_W_m2"];
        p.pwfTsky = data["T_sky_K"];
        p.pwfTair = data["T_air_K"];
        p.pwfTground = data["T_ground_K"];
        p.pwfTdeep = data["T_deep_K"];
        p.pwfAlbedo = data["ground_albedo"];
        p.pwfPress = data["pressure_Pa"];
        p.pwfWind = data["wind_m_s"];
        if (data.count("L_down_W_m2")) p.pwfLdown = data["L_down_W_m2"];
        if (data.count("Ls_deg")) p.pwfLs = data["Ls_deg"];
        if (data.count("dust_tau")) p.pwfTau = data["dust_tau"];
        for (size_t i = 1; i < p.pwfTime.size(); ++i) {
            if (std::abs(p.pwfTime[i] - p.pwfTime[i - 1] - p.pwfDt) > 1e-6 * p.pwfDt) {
                ShowFatalError(state, std::format("Site:PlanetaryBody: records in {} are not equally spaced by timestep_s", full.string()));
            }
        }
        // the engine takes the dates from a calendar-only EPW at the weather file's site
        fs::path const epw = state.dataStrGlobals->outDirPath / "planetary_calendar.epw";
        writeCalendarEpw(state, epw, std::stod(head["latitude_deg"]), std::stod(head["longitude_deg"]), p.referenceYear);
        state.files.inputWeatherFilePath.filePath = epw;
        ShowMessage(state,
                    std::format("ExoBEM-Core: planetary weather file {} ({} records of {:g} s from {}); calendar EPW written to {}",
                                full.string(),
                                p.pwfTime.size(),
                                p.pwfDt,
                                head["start_utc"],
                                epw.string()));
    }

    // linear interpolation of a PWF column at time t [s since start_utc]; solar columns are sampled at mid-interval
    Real64 pwfAt(EnergyPlusData &state, std::vector<Real64> const &col, Real64 t, bool solar)
    {
        auto const &p = *state.dataPlanet;
        Real64 const t0 = p.pwfTime.front() - (solar ? 0.5 * p.pwfDt : 0.0);
        Real64 const x = (t - t0) / p.pwfDt;
        Real64 const last = Real64(col.size() - 1);
        if (x < -1.0 || x > last + 86400.0 / p.pwfDt + 1.0) {
            ShowFatalError(state,
                           std::format("Site:PlanetaryBody: the planetary weather file does not cover the run period (needed t = {:.0f} s after its "
                                       "start)",
                                       t));
        }
        if (x <= 0.0) return col.front();
        if (x >= last) return col.back(); // the engine's extra trailing day may extend beyond the file
        size_t const k = size_t(std::floor(x));
        Real64 const f = x - Real64(k);
        Real64 const a = col[k], b = col[k + 1];
        if (std::isnan(a) || std::isnan(b)) return std::isnan(a) ? b : a;
        return a + f * (b - a);
    }
} // namespace

void GetInput(EnergyPlusData &state)
'''
edit(C, "void GetInput(EnergyPlusData &state)\n", READER, marker="void readPlanetaryWeatherFile(EnergyPlusData &state)")

FILL = '''        p.zenithDeg = zen;
        p.azimuthDeg = azim;

        if (!p.pwfPath.empty()) {
            // values from the planetary weather file at the end of each engine time step (the sun is still the engine's)
            Real64 deep = 0.0;
            for (Real64 const v : p.pwfTdeep) deep += v;
            p.deepGroundC = deep / Real64(p.pwfTdeep.size()) - Constant::Kelvin;
            for (int d = 1; d <= nDays; ++d) {
                for (int hr = 1; hr <= 24; ++hr) {
                    for (int ts = 1; ts <= N; ++ts) {
                        size_t const i = (size_t(d - 1) * 24 + (hr - 1)) * N + (ts - 1);
                        Real64 const tClock = (hr - 1) + Real64(ts) / N;
                        Real64 const t = (p.jd0 + (d - 1) + tClock / 24.0 - p.pwfJd0) * 86400.0;
                        p.beamNormal[i] = std::max(0.0, pwfAt(state, p.pwfDni, t, true));
                        p.diffuseHoriz[i] = std::max(0.0, pwfAt(state, p.pwfDhi, t, true));
                        Real64 const Tsky = pwfAt(state, p.pwfTsky, t, false);
                        p.skyTempC[i] = Tsky - Constant::Kelvin;
                        p.groundSurfC[i] = pwfAt(state, p.pwfTground, t, false) - Constant::Kelvin;
                        Real64 const Ta = pwfAt(state, p.pwfTair, t, false);
                        p.airTempC[i] = std::isnan(Ta) ? p.groundSurfC[i] : Ta - Constant::Kelvin; // no air: ground (see DESIGN.md)
                        p.albedo[i] = pwfAt(state, p.pwfAlbedo, t, false);
                        p.ambientPress[i] = std::max(0.0, pwfAt(state, p.pwfPress, t, false));
                        p.windSpeed[i] = std::max(0.0, pwfAt(state, p.pwfWind, t, false));
                        p.downIR[i] = p.pwfLdown.empty() ? Sigma * std::pow(Tsky, 4) : pwfAt(state, p.pwfLdown, t, false);
                        if (!p.pwfLs.empty()) p.solarLong[i] = pwfAt(state, p.pwfLs, t, true);
                        if (!p.pwfTau.empty()) p.dustTau[i] = pwfAt(state, p.pwfTau, t, true);
                    }
                }
            }
            p.generatedEnvrn = state.dataWeather->Envrn;
            ShowMessage(state, std::format("ExoBEM-Core: environment for {} days read from the planetary weather file, deep regolith {:.1f} C",
                                           nDays, p.deepGroundC));
            return;
        }
'''
edit(C, "        p.zenithDeg = zen;\n        p.azimuthDeg = azim;\n", FILL, marker="read from the planetary weather file, deep regolith")

PV = '''Real64 pvCellTemperatureK(EnergyPlusData &state, int surfNum, Real64 qNet)
{
    // thin module, both faces emit (emissivity 0.85); front sees sky and ground by its tilt, back the complement
    auto &p = *state.dataPlanet;
    auto const &s = state.dataSurface->Surface(surfNum);
    constexpr Real64 epsF = 0.85, epsB = 0.85;
    Real64 const ct = s.CosTilt;
    Real64 const Tsky4 = std::pow(state.dataEnvrn->SkyTempKelvin, 4);
    Real64 const Tg4 = std::pow(p.groundSurfCurrentC + Constant::Kelvin, 4);
    Real64 const Tf4 = 0.5 * (1.0 + ct) * Tsky4 + 0.5 * (1.0 - ct) * Tg4;
    Real64 const Tb4 = 0.5 * (1.0 - ct) * Tsky4 + 0.5 * (1.0 + ct) * Tg4;
    bool const mars = (p.body == Body::Mars);
    Real64 const Ta = state.dataEnvrn->OutDryBulbTemp + Constant::Kelvin;
    Real64 T = 300.0;
    for (int it = 0; it < 50; ++it) {
        Real64 h = 0.0;
        if (mars) {
            h = mixedConvection(p.atmosphere, T, Ta, p.ambientPressCurrent, p.gravity, ct, state.dataEnvrn->WindSpeed, 1.0, 0.5, 1.0);
        }
        Real64 const f = epsF * Sigma * (std::pow(T, 4) - Tf4) + epsB * Sigma * (std::pow(T, 4) - Tb4) + 2.0 * h * (T - Ta) - qNet;
        Real64 const df = 4.0 * (epsF + epsB) * Sigma * std::pow(T, 3) + 2.0 * h;
        Real64 const dT = f / df;
        T = std::max(T - dT, 3.0);
        if (std::abs(dT) < 1e-5) break;
    }
    return T;
}

Real64 groundLongwaveTempC(EnergyPlusData const &state, Real64 defaultC)
'''
edit(C, "Real64 groundLongwaveTempC(EnergyPlusData const &state, Real64 defaultC)\n", PV, marker="Real64 pvCellTemperatureK(EnergyPlusData &state, int surfNum, Real64 qNet)")

VAL = '''    // PV cell-temperature models fitted to Earth air, and Li-ion batteries that would sit in outdoor air
    auto const pvs = ip->epJSON.find("Generator:Photovoltaic");
    if (pvs != ip->epJSON.end()) {
        for (auto const &inst : pvs.value().items()) {
            auto const &o = inst.value();
            std::string const perf = o.count("photovoltaic_performance_object_type") ? Util::makeUPPER(o.at("photovoltaic_performance_object_type").get<std::string>()) : "";
            std::string const mode = o.count("heat_transfer_integration_mode") ? Util::makeUPPER(o.at("heat_transfer_integration_mode").get<std::string>()) : "DECOUPLED";
            if (mode == "DECOUPLEDULLEBERGDYNAMIC" || (perf == "PHOTOVOLTAICPERFORMANCE:SANDIA" && mode == "DECOUPLED")) {
                ShowSevereError(state, std::format("Site:PlanetaryBody: Generator:Photovoltaic {}: this cell-temperature model is fitted to Earth air; "
                                                   "use PhotovoltaicPerformance:Simple, the EquivalentOne-Diode model in Decoupled mode (planetary "
                                                   "energy balance) or IntegratedSurfaceOutsideFace.", inst.key()));
                errors = true;
            }
        }
    }
    auto const lib = ip->epJSON.find("ElectricLoadCenter:Storage:LiIonNMCBattery");
    if (lib != ip->epJSON.end()) {
        for (auto const &inst : lib.value().items()) {
            if (!inst.value().count("zone_name")) {
                ShowSevereError(state, std::format("Site:PlanetaryBody: ElectricLoadCenter:Storage:LiIonNMCBattery {} needs a Zone Name off-Earth "
                                                   "(without a zone its thermal model uses the outdoor air temperature).", inst.key()));
                errors = true;
            }
        }
    }
    if (errors) ShowFatalError(state, "Site:PlanetaryBody: unsupported objects for a planetary simulation; program terminates.");
}
'''
edit(C, '''    if (errors) ShowFatalError(state, "Site:PlanetaryBody: unsupported objects for a planetary simulation; program terminates.");
}
''', VAL, marker='"Generator:Photovoltaic"')

# ------------------------------------------------------------------------------------------------ PV hook
PVC = SRC / "Photovoltaics.cc"
edit(PVC, "#include <EnergyPlus/OutputProcessor.hh>\n", "#include <EnergyPlus/OutputProcessor.hh>\n#include <EnergyPlus/PlanetaryBody.hh>\n",
     marker="#include <EnergyPlus/PlanetaryBody.hh>")
edit(PVC, '''                case CellIntegration::Decoupled: {
                    //  cell temperature based on energy balance
                    state.dataPhotovoltaic->PVarray(PVnum).TRNSYSPVModule.HeatLossCoef =''',
     '''                case CellIntegration::Decoupled: {
                    if (state.dataPlanet->active) { // ExoBEM-Core: radiative (+ Mars convective) cell energy balance
                        CellTemp = Planetary::pvCellTemperatureK(state,
                                                                 state.dataPhotovoltaic->PVarray(PVnum).SurfacePtr,
                                                                 (state.dataPhotovoltaic->PVarray(PVnum).TRNSYSPVModule.TauAlpha - ETA) *
                                                                     state.dataPhotovoltaic->PVarray(PVnum).TRNSYSPVcalc.Insolation);
                        break;
                    }
                    //  cell temperature based on energy balance
                    state.dataPhotovoltaic->PVarray(PVnum).TRNSYSPVModule.HeatLossCoef =''',
     marker="ExoBEM-Core: radiative (+ Mars convective) cell energy balance")
edit(PVC, '''            switch (state.dataPhotovoltaic->PVarray(PVnum).CellIntegrationMode) {
            case CellIntegration::Decoupled: {
                CellTemp = Tambient;
            } break;''', '''            switch (state.dataPhotovoltaic->PVarray(PVnum).CellIntegrationMode) {
            case CellIntegration::Decoupled: {
                CellTemp = state.dataPlanet->active ? Planetary::pvCellTemperatureK(state, state.dataPhotovoltaic->PVarray(PVnum).SurfacePtr, 0.0)
                                                    : Tambient; // ExoBEM-Core: dark cell radiates to sky and regolith
            } break;''', marker="dark cell radiates to sky and regolith")
print("done")
