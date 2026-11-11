// Thermonaut planetary mode.
//
// Thermonaut is a research fork of EnergyPlus(TM) v26.2.0. It is not EnergyPlus and is not endorsed by the
// U.S. DOE, the National Laboratory of the Rockies (formerly NREL) or the EnergyPlus developers.
//
// This module holds everything that is specific to simulating a habitat on another body (Moon, Mars):
//   * input (Site:PlanetaryBody),
//   * solar ephemerides (Mars24 after Allison & McEwen 2000; low-precision selenographic subsolar point),
//   * an environment generator that replaces the weather file values (sun, sky, ambient, regolith),
//   * exterior and interior convection for any gas, pressure and gravity,
//   * a validator that rejects objects that need Earth weather or outdoor air.
// It is a port of the verified Python reference model ExoBEM (https://github.com/TensorBuildLab/ExoBEM).
// With no Site:PlanetaryBody object (or Body = Earth) nothing in this module changes any result.

#ifndef PlanetaryBody_hh_INCLUDED
#define PlanetaryBody_hh_INCLUDED

#include <string>
#include <vector>

#include <EnergyPlus/Data/BaseData.hh>
#include <EnergyPlus/EnergyPlus.hh>

namespace EnergyPlus {

struct EnergyPlusData;

namespace Planetary {

    enum class Body
    {
        Invalid = -1,
        Earth,
        Moon,
        Mars,
        Num
    };

    enum class DustModel
    {
        Invalid = -1,
        Climatology,
        Constant,
        Num
    };

    // Constants shared with the Python reference (exobem/constants.py)
    constexpr Real64 SolarIrradiance1AU = 1361.0; // W/m2 (Kopp & Lean 2011)
    constexpr Real64 CosmicBackgroundK = 2.725;   // K
    constexpr Real64 SunAngularRadius1AU = 0.2666; // deg
    constexpr Real64 MarsSolSeconds = 88775.244147;
    constexpr Real64 SynodicMonthDays = 29.530588853;
    constexpr Real64 MoonGravity = 1.625;
    constexpr Real64 MarsGravity = 3.721;

    // Simple ideal gas with Sutherland-law transport properties (exobem/gas.py)
    struct Gas
    {
        Real64 molarMass = 0.0289647; // kg/mol
        Real64 cp = 1005.0;           // J/kg-K
        Real64 muRef = 1.716e-5;      // Pa-s at TRef
        Real64 kRef = 0.0241;         // W/m-K at TRef
        Real64 TRef = 273.15;         // K
        Real64 sMu = 110.4;           // K
        Real64 sK = 194.0;            // K

        Real64 R() const;
        Real64 density(Real64 T, Real64 P) const;
        Real64 viscosity(Real64 T) const;
        Real64 conductivity(Real64 T) const;
    };

    Gas cabinGas(Real64 o2Fraction);
    Gas marsCO2();

    // Sun position on a body (angles in degrees, hour angle positive in the afternoon)
    struct SunPosition
    {
        Real64 zenith = 90.0;
        Real64 azimuth = 0.0; // clockwise from north
        Real64 hourAngle = 0.0;
        Real64 declination = 0.0;
        Real64 distanceAU = 1.0;
        Real64 solarLongitude = 0.0; // Mars Ls (deg); 0 elsewhere
    };

    Real64 julianDate(int year, int month, int day); // JD (UTC) of 00:00 on the given date
    SunPosition sunPosition(Body body, Real64 jdUTC, Real64 latDeg, Real64 lonEastDeg);

    // Delta-Eddington two-stream: (direct fraction of the normal beam, diffuse-down fraction of TOA horizontal)
    void deltaEddingtonSurface(Real64 tau, Real64 mu0, Real64 w0, Real64 g, Real64 surfaceAlbedo, Real64 &directFrac, Real64 &diffuseFrac);
    Real64 marsDustTau(Real64 Ls, Real64 stormStart, Real64 stormEnd, Real64 stormPeak);
    Real64 marsSurfacePressure(Real64 Ls, Real64 pMean);

    // Input and set-up
    void GetInput(EnergyPlusData &state);
    void ValidateInput(EnergyPlusData &state);

    // Weather hooks (called from WeatherManager)
    void FillTomorrow(EnergyPlusData &state, int dayIndex);
    void AdvanceDay(EnergyPlusData &state);
    void SetCurrentWeather(EnergyPlusData &state);

    // Physics hooks
    Real64 gravity(EnergyPlusData const &state);
    Real64 exteriorConvection(EnergyPlusData &state, int surfNum, Real64 TSurfK, Real64 TAirK);
    Real64 interiorConvection(EnergyPlusData &state, int surfNum, Real64 TSurfC, Real64 TAirC);
    Real64 groundLongwaveTempC(EnergyPlusData const &state, Real64 defaultC);
    // Cell temperature [K] of a PV module on surface surfNum off-Earth: both faces radiate to sky and regolith,
    // plus convection in the Martian atmosphere; qNet = absorbed solar minus electric output [W/m2].
    Real64 pvCellTemperatureK(EnergyPlusData &state, int surfNum, Real64 qNet);
    // Mean outer-face temperature of a surface under the period-mean planetary environment (steady radiative balance);
    // used to start conduction profiles near their steady state (regolith time constants are months to years).
    Real64 meanOuterFaceTempC(EnergyPlusData &state, int surfNum);

    // Mixed natural/forced convection for any gas (exobem/convection.py, "physical" family)
    Real64 mixedConvection(
        Gas const &gas, Real64 TSurfK, Real64 TAirK, Real64 P, Real64 g, Real64 cosUp, Real64 V, Real64 Lvert, Real64 Lhoriz, Real64 Lforced);

} // namespace Planetary

struct PlanetaryData : BaseGlobalStruct
{
    bool active = false; // true for Moon or Mars
    Planetary::Body body = Planetary::Body::Earth;
    int referenceYear = 2030;
    Real64 gravity = 9.807;
    Real64 cabinPressure = 70300.0;
    Real64 cabinO2 = 0.265;
    Real64 cabinAirVelocity = 0.15;
    Real64 convLength = -1.0; // <= 0: autocalculate (sqrt of area)
    Real64 horizonDeg = 0.0;
    Real64 regolithThermalInertia = 350.0;
    Real64 regolithAlbedo = 0.14;
    Real64 regolithEmissivity = 0.97;
    int spinUpCycles = 30;
    Real64 deepDepth = 3.0;
    Real64 marsMeanPressure = 710.0;
    Planetary::DustModel dustModel = Planetary::DustModel::Climatology;
    Real64 dustTauConstant = 0.5;
    Real64 stormStartLs = 0.0;
    Real64 stormEndLs = 0.0;
    Real64 stormPeakTau = 0.0;
    Real64 windMean = 3.2;
    Real64 windAmplitude = 2.0;
    Real64 hourAngleRate = 15.0; // deg per clock hour of the apparent Sun

    Planetary::Gas cabin;
    Planetary::Gas atmosphere; // Mars only

    // Generated environment for the current run period (index ((day-1)*24 + hr-1)*N + ts-1)
    int generatedEnvrn = -1;
    int nDays = 0;
    int stepsPerHour = 1;
    Real64 jd0 = 0.0; // JD (UTC) of 00:00 on day 1
    std::vector<Real64> beamNormal, diffuseHoriz, skyTempC, airTempC, ambientPress, windSpeed, groundSurfC, albedo, solarLong, dustTau,
        downIR, zenithDeg, azimuthDeg;
    std::vector<Real64> daySinDec, dayCosDec, dayEoT, dayDistAU;
    Real64 deepGroundC = -20.0;
    int tomorrowIndex = 1;
    int todayIndex = 1;

    // Current-timestep values (for hooks and output)
    Real64 groundSurfCurrentC = 0.0;
    Real64 ambientPressCurrent = 0.0;
    Real64 solarLongCurrent = 0.0;
    Real64 dustTauCurrent = 0.0;
    Real64 downIRCurrent = 0.0;
    Real64 sunDistanceCurrent = 1.0;
    bool outputsSetUp = false;
    bool condFDCorrected = false; // CondFD start-up profile corrected after warm-up

    // Planetary weather file (PWF); empty path = generate the environment
    std::string pwfPath;
    Real64 pwfJd0 = 0.0; // JD (UTC) of the file's start_utc
    Real64 pwfDt = 0.0;  // record length [s]
    std::vector<Real64> pwfTime, pwfDni, pwfDhi, pwfTsky, pwfTair, pwfTground, pwfTdeep, pwfAlbedo, pwfPress, pwfWind, pwfLdown, pwfLs,
        pwfTau;

    void init_constant_state([[maybe_unused]] EnergyPlusData &state) override
    {
    }
    void init_state([[maybe_unused]] EnergyPlusData &state) override
    {
    }
    void clear_state() override
    {
        new (this) PlanetaryData();
    }
};

} // namespace EnergyPlus

#endif
