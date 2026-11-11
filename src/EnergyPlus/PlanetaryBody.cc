// Thermonaut planetary mode. See PlanetaryBody.hh and planetary/DESIGN.md.
//
// Thermonaut is a research fork of EnergyPlus(TM) v26.2.0. It is not EnergyPlus and is not endorsed by the
// U.S. DOE, the National Laboratory of the Rockies (formerly NREL) or the EnergyPlus developers.

#include <algorithm>
#include <array>
#include <cstdio>
#include <format>
#include <cmath>
#include <fstream>
#include <limits>
#include <map>
#include <sstream>
#include <string>

#include <EnergyPlus/Data/EnergyPlusData.hh>
#include <EnergyPlus/Construction.hh>
#include <EnergyPlus/DataEnvironment.hh>
#include <EnergyPlus/DataGlobalConstants.hh>
#include <EnergyPlus/DataGlobals.hh>
#include <EnergyPlus/DataHeatBalSurface.hh>
#include <EnergyPlus/DataHeatBalance.hh>
#include <EnergyPlus/DataStringGlobals.hh>
#include <EnergyPlus/DataSurfaces.hh>
#include <EnergyPlus/DataSystemVariables.hh>
#include <EnergyPlus/FileSystem.hh>
#include <EnergyPlus/InputProcessing/InputProcessor.hh>
#include <EnergyPlus/OutputProcessor.hh>
#include <EnergyPlus/PlanetaryBody.hh>
#include <EnergyPlus/Psychrometrics.hh>
#include <EnergyPlus/UtilityRoutines.hh>
#include <EnergyPlus/WeatherManager.hh>

namespace EnergyPlus::Planetary {

namespace {
    constexpr Real64 Sigma = 5.670374419e-8;
    constexpr Real64 RUniversal = 8.314462618;
    constexpr Real64 Deg = Constant::Pi / 180.0;
    constexpr Real64 TTminusUTC = 69.184; // s

    Real64 wrap180(Real64 a)
    {
        a = std::fmod(a + 180.0, 360.0);
        if (a < 0.0) a += 360.0;
        return a - 180.0;
    }
    Real64 mod360(Real64 a)
    {
        a = std::fmod(a, 360.0);
        return (a < 0.0) ? a + 360.0 : a;
    }
    Real64 clamp(Real64 x, Real64 lo, Real64 hi)
    {
        return std::max(lo, std::min(hi, x));
    }

    void horizontalGeometry(Real64 latDeg, Real64 decDeg, Real64 hourAngleDeg, Real64 &zenDeg, Real64 &azDeg)
    {
        Real64 const lat = latDeg * Deg, dec = decDeg * Deg, H = hourAngleDeg * Deg;
        Real64 cosz = std::sin(lat) * std::sin(dec) + std::cos(lat) * std::cos(dec) * std::cos(H);
        cosz = clamp(cosz, -1.0, 1.0);
        zenDeg = std::acos(cosz) / Deg;
        Real64 const sinAz = -std::cos(dec) * std::sin(H);
        Real64 const cosAz = std::sin(dec) * std::cos(lat) - std::cos(dec) * std::sin(lat) * std::cos(H);
        azDeg = mod360(std::atan2(sinAz, cosAz) / Deg);
    }

    // Apparent ecliptic longitude of the Sun (deg) and Earth-Sun distance (AU); Meeus low precision
    void sunEcliptic(Real64 jd, Real64 &lam, Real64 &r)
    {
        Real64 const T = (jd - 2451545.0) / 36525.0;
        Real64 const L0 = mod360(280.46646 + 36000.76983 * T + 0.0003032 * T * T);
        Real64 const M = mod360(357.52911 + 35999.05029 * T - 0.0001537 * T * T) * Deg;
        Real64 const e = 0.016708634 - 0.000042037 * T;
        Real64 const C = (1.914602 - 0.004817 * T - 0.000014 * T * T) * std::sin(M) + (0.019993 - 0.000101 * T) * std::sin(2 * M) +
                         0.000289 * std::sin(3 * M);
        Real64 const nu = M + C * Deg;
        r = 1.000001018 * (1 - e * e) / (1 + e * std::cos(nu));
        Real64 const omega = 125.04 - 1934.136 * T;
        lam = mod360(L0 + C - 0.00569 - 0.00478 * std::sin(omega * Deg));
    }

    // Lunar subsolar point (exobem/ephemeris/moon.py)
    void moonSubsolar(Real64 jd, Real64 &lonSS, Real64 &latSS, Real64 &r)
    {
        Real64 const T = (jd - 2451545.0) / 36525.0;
        Real64 const Lp = mod360(218.3164477 + 481267.88123421 * T - 0.0015786 * T * T);
        Real64 const Om = mod360(125.0445479 - 1934.1362891 * T + 0.0020754 * T * T);
        Real64 lamSun;
        sunEcliptic(jd, lamSun, r);
        lonSS = wrap180(180.0 - (Lp - lamSun));
        latSS = 1.5424 * std::sin((lamSun - Om) * Deg);
    }

    // Mars areocentric solar coordinates, Allison & McEwen (2000) / Mars24 (exobem/ephemeris/mars.py)
    struct Areocentric
    {
        Real64 Ls, eotDeg, declDeg, rAU, mstH;
    };
    Areocentric marsAreocentric(Real64 jdUTC)
    {
        static constexpr std::array<Real64, 7> A = {0.0071, 0.0057, 0.0039, 0.0037, 0.0021, 0.0020, 0.0018};
        static constexpr std::array<Real64, 7> Tau = {2.2353, 2.7543, 1.1177, 15.7866, 2.1354, 2.4694, 32.8493};
        static constexpr std::array<Real64, 7> Phi = {49.409, 168.173, 191.837, 21.736, 15.704, 95.528, 49.095};
        Real64 const jdTT = jdUTC + TTminusUTC / 86400.0;
        Real64 const dt = jdTT - 2451545.0;
        Real64 const M = mod360(19.3871 + 0.52402073 * dt) * Deg;
        Real64 const alphaFMS = mod360(270.3871 + 0.524038496 * dt);
        Real64 pbs = 0.0;
        for (int i = 0; i < 7; ++i) {
            pbs += A[i] * std::cos((0.985626 * dt / Tau[i] + Phi[i]) * Deg);
        }
        Real64 const nuM = (10.691 + 3.0e-7 * dt) * std::sin(M) + 0.623 * std::sin(2 * M) + 0.050 * std::sin(3 * M) + 0.005 * std::sin(4 * M) +
                           0.0005 * std::sin(5 * M) + pbs;
        Areocentric a{};
        a.Ls = mod360(alphaFMS + nuM);
        Real64 const Lr = a.Ls * Deg;
        a.eotDeg = 2.861 * std::sin(2 * Lr) - 0.071 * std::sin(4 * Lr) + 0.002 * std::sin(6 * Lr) - nuM;
        a.declDeg = std::asin(0.42565 * std::sin(Lr)) / Deg + 0.25 * std::sin(Lr);
        a.rAU = 1.52367934 * (1.00436 - 0.09309 * std::cos(M) - 0.004336 * std::cos(2 * M) - 0.00031 * std::cos(3 * M) -
                              0.00003 * std::cos(4 * M));
        Real64 const msd = ((jdTT - 2451549.5) / 1.0274912517) + 44796.0 - 0.0009626;
        a.mstH = std::fmod(24.0 * msd, 24.0);
        if (a.mstH < 0.0) a.mstH += 24.0;
        return a;
    }

    Real64 hayneSpecificHeat(Real64 T)
    {
        T = clamp(T, 20.0, 450.0);
        return -3.6125 + 2.7431 * T + 2.3616e-3 * T * T - 1.2340e-5 * T * T * T + 8.9093e-9 * T * T * T * T;
    }

    Real64 horizonVisibleFraction(Real64 elevDeg, Real64 horizonDeg, Real64 sunRadiusDeg)
    {
        // area of a uniform disk above a straight horizon (ExoBEM solar.horizon_visible_fraction)
        Real64 const x = clamp((elevDeg - horizonDeg) / sunRadiusDeg, -1.0, 1.0);
        return (std::acos(-x) + x * std::sqrt(1.0 - x * x)) / Constant::Pi;
    }

    // ------------------------------------------------------------------------------------ regolith column
    // One-dimensional implicit model of the planetary ground (exobem/environment/regolith.py)
    struct RegolithColumn
    {
        Real64 depth = 3.0;
        int n = 60;
        Real64 dz0 = 2.0e-3;
        Real64 rhoS = 1100.0, rhoD = 1800.0, H = 0.06;
        Real64 kS = 7.4e-4, kD = 3.4e-3, chi = 2.7;
        Real64 cpConst = -1.0; // < 0: Hayne cp(T)
        Real64 emissivity = 0.95;
        Real64 albedo0 = 0.12, albedoA = 0.06, albedoB = 0.25;
        Real64 qGeo = 0.018;

        std::vector<Real64> z, dz, rhoN, kcSeg;

        static RegolithColumn mars(Real64 thermalInertia, Real64 albedo, Real64 emissivity)
        {
            RegolithColumn c;
            Real64 const rho = 1500.0, cp = 800.0;
            Real64 const k = thermalInertia * thermalInertia / (rho * cp);
            c.depth = 4.0;
            c.rhoS = c.rhoD = rho;
            c.H = 1.0;
            c.kS = c.kD = k;
            c.chi = 0.0;
            c.cpConst = cp;
            c.emissivity = emissivity;
            c.albedo0 = albedo;
            c.albedoA = c.albedoB = 0.0;
            c.qGeo = 0.02;
            return c;
        }

        void build()
        {
            Real64 lo = 1.0 + 1e-6, hi = 2.0, r = 1.0;
            for (int it = 0; it < 100; ++it) {
                r = 0.5 * (lo + hi);
                Real64 const L = dz0 * (std::pow(r, n - 1) - 1.0) / (r - 1.0);
                if (L > depth) {
                    hi = r;
                } else {
                    lo = r;
                }
            }
            z.assign(n, 0.0);
            dz.assign(n - 1, 0.0);
            for (int i = 0; i < n - 1; ++i) {
                dz[i] = dz0 * std::pow(r, i);
                z[i + 1] = z[i] + dz[i];
            }
            rhoN.assign(n, 0.0);
            kcSeg.assign(n - 1, 0.0);
            for (int i = 0; i < n; ++i) {
                rhoN[i] = rhoD - (rhoD - rhoS) * std::exp(-z[i] / H);
            }
            for (int i = 0; i < n - 1; ++i) {
                Real64 const zc = 0.5 * (z[i] + z[i + 1]);
                kcSeg[i] = kD - (kD - kS) * std::exp(-zc / H);
            }
        }

        Real64 albedo(Real64 incidenceDeg) const
        {
            Real64 const i = clamp(incidenceDeg, 0.0, 90.0);
            return albedo0 + albedoA * std::pow(i / 45.0, 3) + albedoB * std::pow(i / 90.0, 8);
        }

        int nodeNearest(Real64 d) const
        {
            int best = 0;
            for (int i = 1; i < n; ++i) {
                if (std::abs(z[i] - d) < std::abs(z[best] - d)) best = i;
            }
            return best;
        }

        // One implicit step with Newton-linearised surface emission
        void step(std::vector<Real64> &T, Real64 dt, Real64 qAbs, Real64 Ld) const
        {
            std::vector<Real64> C(n, 0.0), K(n - 1), diag(n), lower(n, 0.0), upper(n, 0.0), rhs(n), Tn(n);
            for (int i = 0; i < n - 1; ++i) {
                Real64 const Tseg = 0.5 * (T[i] + T[i + 1]);
                Real64 const k = kcSeg[i] * (1.0 + chi * std::pow(Tseg / 350.0, 3));
                K[i] = k / dz[i];
                Real64 const cpI = (cpConst < 0.0) ? hayneSpecificHeat(T[i]) : cpConst;
                Real64 const cpJ = (cpConst < 0.0) ? hayneSpecificHeat(T[i + 1]) : cpConst;
                C[i] += 0.5 * rhoN[i] * cpI * dz[i];
                C[i + 1] += 0.5 * rhoN[i + 1] * cpJ * dz[i];
            }
            Real64 Ts = T[0];
            for (int it = 0; it < 3; ++it) {
                for (int i = 0; i < n; ++i) {
                    diag[i] = C[i] / dt;
                    rhs[i] = C[i] / dt * T[i];
                }
                for (int i = 0; i < n - 1; ++i) {
                    diag[i] += K[i];
                    diag[i + 1] += K[i];
                    upper[i] = -K[i];
                    lower[i + 1] = -K[i];
                }
                Real64 const hr = 4.0 * emissivity * Sigma * Ts * Ts * Ts;
                diag[0] += hr;
                rhs[0] += qAbs + emissivity * Ld + 3.0 * emissivity * Sigma * Ts * Ts * Ts * Ts;
                rhs[n - 1] += qGeo;
                // Thomas algorithm
                std::vector<Real64> c2(n), d2(n);
                c2[0] = upper[0] / diag[0];
                d2[0] = rhs[0] / diag[0];
                for (int i = 1; i < n; ++i) {
                    Real64 const m = diag[i] - lower[i] * c2[i - 1];
                    c2[i] = (i < n - 1) ? upper[i] / m : 0.0;
                    d2[i] = (rhs[i] - lower[i] * d2[i - 1]) / m;
                }
                Tn[n - 1] = d2[n - 1];
                for (int i = n - 2; i >= 0; --i) {
                    Tn[i] = d2[i] - c2[i] * Tn[i + 1];
                }
                if (std::abs(Tn[0] - Ts) < 1e-3) break;
                Ts = Tn[0];
            }
            T = Tn;
        }

        // Integrate a series. Spin-up cycles over the first cycleSteps entries first (if requested).
        void run(Real64 dt,
                 std::vector<Real64> const &qAbs,
                 std::vector<Real64> const &Ld,
                 std::vector<Real64> &T,
                 bool initFromEquilibrium,
                 int spinUpCycles,
                 int cycleSteps,
                 std::vector<Real64> *surface,
                 std::vector<Real64> *meanProfile) const
        {
            size_t const ns = qAbs.size();
            if (initFromEquilibrium) {
                Real64 s = 0.0;
                for (size_t i = 0; i < ns; ++i) {
                    s += qAbs[i] + Ld[i];
                }
                Real64 const Teq = std::pow((s / std::max<size_t>(ns, 1)) / (emissivity * Sigma), 0.25);
                T.assign(n, 0.9 * Teq);
            }
            if (spinUpCycles > 0 && cycleSteps > 0) {
                int const m = std::min<int>(cycleSteps, int(ns));
                for (int c = 0; c < spinUpCycles; ++c) {
                    for (int i = 0; i < m; ++i) {
                        step(T, dt, qAbs[i], Ld[i]);
                    }
                }
            }
            if (surface) surface->assign(ns, 0.0);
            if (meanProfile) meanProfile->assign(n, 0.0);
            for (size_t i = 0; i < ns; ++i) {
                step(T, dt, qAbs[i], Ld[i]);
                if (surface) (*surface)[i] = T[0];
                if (meanProfile) {
                    for (int j = 0; j < n; ++j) {
                        (*meanProfile)[j] += T[j];
                    }
                }
            }
            if (meanProfile && ns > 0) {
                for (int j = 0; j < n; ++j) {
                    (*meanProfile)[j] /= Real64(ns);
                }
            }
        }
    };

    // Periodic equilibrium for a forcing that repeats with its own length (ExoBEM RegolithColumn.equilibrate):
    // run one period, rebuild the profile below zSkin from the period-mean temperature there so that it carries
    // the geothermal flux, repeat until the deep temperature changes by less than tol.
    void equilibrateColumn(RegolithColumn const &col, Real64 dt, std::vector<Real64> const &qAbs, std::vector<Real64> const &Ld,
                           Real64 zSkin, std::vector<Real64> &T)
    {
        int const iS = col.nodeNearest(zSkin);
        std::vector<Real64> mean, prof;
        Real64 prev = -1.0;
        bool first = true;
        for (int it = 0; it < 6; ++it) {
            col.run(dt, qAbs, Ld, T, first, 0, 0, nullptr, &mean);
            first = false;
            prof = mean;
            for (int j = iS; j < col.n - 1; ++j) {
                Real64 const k = col.kcSeg[j] * (1.0 + col.chi * std::pow(prof[j] / 350.0, 3));
                prof[j + 1] = prof[j] + col.qGeo * col.dz[j] / k;
            }
            for (int j = iS; j < col.n; ++j) {
                T[j] += prof[j] - mean[j];
            }
            if (prev > 0.0 && std::abs(prof[col.n - 1] - prev) < 0.02) break;
            prev = prof[col.n - 1];
        }
        col.run(dt, qAbs, Ld, T, false, 0, 0, nullptr, &mean);
    }

    // trailing running mean over k samples (current included), padded with the mean of the first k
    std::vector<Real64> trailingMean(std::vector<Real64> const &x, int k)
    {
        size_t const n = x.size();
        k = std::max(1, std::min<int>(k, int(n)));
        Real64 pad = 0.0;
        for (int i = 0; i < k; ++i) {
            pad += x[i];
        }
        pad /= k;
        std::vector<Real64> out(n);
        Real64 s = pad * k; // window sum
        for (size_t i = 0; i < n; ++i) {
            Real64 const leaving = (int(i) - k >= 0) ? x[i - k] : pad;
            s += x[i] - leaving;
            out[i] = s / k;
        }
        return out;
    }
} // namespace

// ---------------------------------------------------------------------------------------------- gases
Real64 Gas::R() const
{
    return RUniversal / molarMass;
}
Real64 Gas::density(Real64 T, Real64 P) const
{
    return P / (R() * T);
}
Real64 Gas::viscosity(Real64 T) const
{
    return muRef * std::pow(T / TRef, 1.5) * (TRef + sMu) / (T + sMu);
}
Real64 Gas::conductivity(Real64 T) const
{
    return kRef * std::pow(T / TRef, 1.5) * (TRef + sK) / (T + sK);
}

Gas cabinGas(Real64 x)
{
    Gas g;
    g.molarMass = x * 0.031999 + (1.0 - x) * 0.028014;
    g.muRef = 1.716e-5 * (1.0 + 0.12 * (x - 0.21));
    g.kRef = 0.0241 * (1.0 + 0.02 * (x - 0.21));
    Real64 const yO2 = x * 0.031999 / g.molarMass; // O2 mass fraction
    g.cp = yO2 * 918.0 + (1.0 - yO2) * 1040.0;      // cp of O2 and N2 at 300 K, mass weighted
    return g;
}

Gas marsCO2()
{
    Gas g;
    g.molarMass = 0.04334;
    g.cp = 760.0;
    g.muRef = 1.370e-5;
    g.kRef = 0.01465;
    g.TRef = 273.15;
    g.sMu = 222.0;
    g.sK = 1800.0;
    return g;
}

// ---------------------------------------------------------------------------------------------- ephemerides
Real64 julianDate(int year, int month, int day)
{
    // Fliegel & Van Flandern algorithm for the Julian day number at noon, minus 0.5 for 00:00 UTC
    int const a = (14 - month) / 12;
    int const y = year + 4800 - a;
    int const m = month + 12 * a - 3;
    long const jdn = day + (153 * m + 2) / 5 + 365L * y + y / 4 - y / 100 + y / 400 - 32045;
    return Real64(jdn) - 0.5;
}

SunPosition sunPosition(Body body, Real64 jd, Real64 lat, Real64 lon)
{
    SunPosition sp;
    if (body == Body::Mars) {
        Areocentric const a = marsAreocentric(jd);
        Real64 lmst = std::fmod(a.mstH + lon / 15.0, 24.0);
        if (lmst < 0.0) lmst += 24.0;
        Real64 ltst = std::fmod(lmst + a.eotDeg / 15.0, 24.0);
        if (ltst < 0.0) ltst += 24.0;
        sp.hourAngle = (ltst - 12.0) * 15.0;
        sp.declination = a.declDeg;
        sp.distanceAU = a.rAU;
        sp.solarLongitude = a.Ls;
    } else if (body == Body::Moon) {
        Real64 lonSS, latSS, r;
        moonSubsolar(jd, lonSS, latSS, r);
        sp.hourAngle = wrap180(lon - lonSS);
        sp.declination = latSS;
        sp.distanceAU = r;
    } else {
        // Earth (NOAA): used only for testing
        Real64 lam, r;
        sunEcliptic(jd, lam, r);
        Real64 const T = (jd - 2451545.0) / 36525.0;
        Real64 const eps = 23.439291 - 0.0130042 * T;
        sp.declination = std::asin(std::sin(eps * Deg) * std::sin(lam * Deg)) / Deg;
        Real64 const ra = mod360(std::atan2(std::cos(eps * Deg) * std::sin(lam * Deg), std::cos(lam * Deg)) / Deg);
        Real64 const gmst = mod360(280.46061837 + 360.98564736629 * (jd - 2451545.0));
        sp.hourAngle = wrap180(gmst + lon - ra);
        sp.distanceAU = r;
    }
    horizontalGeometry(lat, sp.declination, sp.hourAngle, sp.zenith, sp.azimuth);
    return sp;
}

// ---------------------------------------------------------------------------------------------- Mars atmosphere
void deltaEddingtonSurface(Real64 tau, Real64 mu0, Real64 w0, Real64 g, Real64 As, Real64 &directFrac, Real64 &diffuseFrac)
{
    mu0 = clamp(mu0, 1e-3, 1.0);
    Real64 const f = g * g;
    Real64 const tauS = (1.0 - w0 * f) * tau;
    Real64 w = (1.0 - f) * w0 / (1.0 - w0 * f);
    Real64 const gs = (g - f) / (1.0 - f);
    w = std::min(w, 1.0 - 1e-9);
    Real64 const g1 = (7.0 - w * (4.0 + 3.0 * gs)) / 4.0;
    Real64 const g2 = -(1.0 - w * (4.0 - 3.0 * gs)) / 4.0;
    Real64 const g3 = (2.0 - 3.0 * gs * mu0) / 4.0;
    Real64 const g4 = 1.0 - g3;
    Real64 const lam = std::sqrt(std::max(g1 * g1 - g2 * g2, 1e-12));
    Real64 const a11 = g1 + 1.0 / mu0, a12 = -g2, a21 = g2, a22 = -(g1 - 1.0 / mu0);
    Real64 const b1 = g3 * w, b2 = -g4 * w;
    Real64 det = a11 * a22 - a12 * a21;
    if (std::abs(det) < 1e-10) det = 1e-10;
    Real64 const Cp = (b1 * a22 - a12 * b2) / det;
    Real64 const Cm = (a11 * b2 - a21 * b1) / det;
    Real64 const r1 = (g1 + lam) / g2, r2 = (g1 - lam) / g2;
    Real64 const E = std::exp(-lam * tauS);
    Real64 const eT = std::exp(-tauS / mu0);
    Real64 const m11 = r1, m12 = r2 * E, c1 = -Cm;
    Real64 const m21 = E - As * r1 * E, m22 = 1.0 - As * r2;
    Real64 const c2 = As * mu0 * eT - (Cp - As * Cm) * eT;
    Real64 const d = m11 * m22 - m12 * m21;
    Real64 const a = (c1 * m22 - m12 * c2) / d;
    Real64 const b = (m11 * c2 - m21 * c1) / d;
    Real64 const FdnBottom = a * r1 * E + b * r2 + Cm * eT;
    directFrac = eT;
    diffuseFrac = FdnBottom / mu0;
}

Real64 marsDustTau(Real64 Ls, Real64 stormStart, Real64 stormEnd, Real64 stormPeak)
{
    constexpr Real64 tauA = 0.45, tauP = 0.85, LsPeak = 245.0, width = 55.0;
    Real64 const d = std::fmod(Ls - LsPeak + 180.0 + 3600.0, 360.0) - 180.0;
    Real64 tau = tauA + (tauP - tauA) * std::exp(-0.5 * (d / width) * (d / width));
    if (stormPeak > 0.0 && stormEnd > stormStart) {
        Real64 const mid = 0.5 * (stormStart + stormEnd), half = 0.5 * (stormEnd - stormStart);
        Real64 const ds = std::fmod(Ls - mid + 180.0 + 3600.0, 360.0) - 180.0;
        if (std::abs(ds) < half) {
            tau = std::max(tau, stormPeak * std::sqrt(clamp(std::cos(0.5 * Constant::Pi * ds / half), 0.0, 1.0)));
        }
    }
    return tau;
}

Real64 marsSurfacePressure(Real64 Ls, Real64 pMean)
{
    Real64 const L = Ls * Deg;
    // minimum near Ls 157 (southern cap growth), maximum near Ls 269, secondary maximum near Ls 64
    return pMean * (1.0 + 0.074 * std::sin(L + 154.0 * Deg) + 0.055 * std::sin(2.0 * L + 290.0 * Deg));
}

// ---------------------------------------------------------------------------------------------- convection
Real64 mixedConvection(
    Gas const &gas, Real64 TSurf, Real64 TAir, Real64 P, Real64 g, Real64 cosUp, Real64 V, Real64 Lv, Real64 Lh, Real64 Lf)
{
    if (P <= 0.0) return 0.0;
    Real64 const Tf = std::max(0.5 * (TSurf + TAir), 50.0);
    Real64 const dT = TSurf - TAir;
    Real64 const k = gas.conductivity(Tf);
    Real64 const rho = gas.density(Tf, P);
    Real64 const nu = gas.viscosity(Tf) / rho;
    Real64 const alpha = k / (rho * gas.cp);
    Real64 const Pr = nu / alpha;
    // natural
    Real64 const gb = g * (1.0 / Tf) * std::abs(dT) / (nu * alpha);
    Real64 const RaV = gb * Lv * Lv * Lv;
    Real64 const psi = std::pow(1.0 + std::pow(0.492 / Pr, 9.0 / 16.0), 8.0 / 27.0);
    Real64 const NuV = std::pow(0.825 + 0.387 * std::pow(RaV, 1.0 / 6.0) / psi, 2);
    Real64 const hV = NuV * k / Lv;
    Real64 const RaH = gb * Lh * Lh * Lh;
    bool const enhanced = (dT > 0.0 && cosUp > 0.0) || (dT < 0.0 && cosUp < 0.0);
    Real64 NuH = enhanced ? ((RaH < 1e7) ? 0.54 * std::pow(RaH, 0.25) : 0.15 * std::pow(RaH, 1.0 / 3.0)) : 0.27 * std::pow(RaH, 0.25);
    NuH = std::max(NuH, 1.0);
    Real64 const hH = NuH * k / Lh;
    Real64 const wt = std::abs(cosUp);
    Real64 const hn = (1.0 - wt) * hV + wt * hH;
    // forced
    Real64 const Re = std::max(V, 1e-6) * Lf / nu;
    Real64 const NuLam = 0.664 * std::sqrt(Re) * std::cbrt(Pr);
    Real64 Nu = NuLam;
    if (Re >= 5e5) Nu = std::max((0.037 * std::pow(Re, 0.8) - 871.0) * std::cbrt(Pr), NuLam);
    Real64 const hf = Nu * k / Lf;
    return std::cbrt(hn * hn * hn + hf * hf * hf);
}

Real64 gravity(EnergyPlusData const &state)
{
    return state.dataPlanet->gravity;
}

namespace {
    void surfaceLengths(EnergyPlusData const &state, int surfNum, Real64 &Lv, Real64 &Lh, Real64 &Lf)
    {
        auto const &s = state.dataSurface->Surface(surfNum);
        Real64 const A = std::max(s.Area, 1e-6);
        Real64 const per = (s.Perimeter > 0.0) ? s.Perimeter : 4.0 * std::sqrt(A);
        Lv = (state.dataPlanet->convLength > 0.0) ? state.dataPlanet->convLength : std::sqrt(A);
        Lh = A / per;
        Lf = std::sqrt(A);
    }
} // namespace

Real64 exteriorConvection(EnergyPlusData &state, int surfNum, Real64 TSurfK, Real64 TAirK)
{
    auto &p = *state.dataPlanet;
    if (p.body != Body::Mars) return 0.0; // vacuum
    Real64 Lv, Lh, Lf;
    surfaceLengths(state, surfNum, Lv, Lh, Lf);
    auto const &s = state.dataSurface->Surface(surfNum);
    Real64 const V = s.ExtWind ? state.dataEnvrn->WindSpeed : 0.0;
    return mixedConvection(p.atmosphere, TSurfK, TAirK, p.ambientPressCurrent, p.gravity, s.CosTilt, V, Lv, Lh, Lf);
}

Real64 interiorConvection(EnergyPlusData &state, int surfNum, Real64 TSurfC, Real64 TAirC)
{
    auto &p = *state.dataPlanet;
    Real64 Lv, Lh, Lf;
    surfaceLengths(state, surfNum, Lv, Lh, Lf);
    // inside face: its outward normal points into the zone, opposite to the surface normal
    Real64 const cosUpIn = -state.dataSurface->Surface(surfNum).CosTilt;
    Real64 const h = mixedConvection(
        p.cabin, TSurfC + Constant::Kelvin, TAirC + Constant::Kelvin, p.cabinPressure, p.gravity, cosUpIn, p.cabinAirVelocity, Lv, Lh, Lf);
    return std::max(h, 0.05);
}

Real64 pvCellTemperatureK(EnergyPlusData &state, int surfNum, Real64 qNet)
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
{
    return state.dataPlanet->active ? state.dataPlanet->groundSurfCurrentC : defaultC;
}

Real64 meanOuterFaceTempC(EnergyPlusData &state, int surfNum)
{
    auto &p = *state.dataPlanet;
    auto const &s = state.dataSurface->Surface(surfNum);
    if (s.ExtBoundCond == DataSurfaces::Ground) return p.deepGroundC;
    if (s.ExtBoundCond != DataSurfaces::ExternalEnvironment || p.groundSurfC.empty()) return -999.0;
    auto const &c = state.dataConstruction->Construct(s.Construction);
    Real64 const alpha = c.OutsideAbsorpSolar, eps = c.OutsideAbsorpThermal;
    Real64 const ct = s.CosTilt, st = std::sqrt(std::max(0.0, 1.0 - ct * ct));
    Real64 const fSky = 0.5 * (1.0 + ct), fGnd = 0.5 * (1.0 - ct);
    size_t const n = p.groundSurfC.size();
    Real64 q = 0.0, sky4 = 0.0, gnd4 = 0.0, tAir = 0.0, wind = 0.0, pAmb = 0.0;
    for (size_t i = 0; i < n; ++i) {
        Real64 const z = p.zenithDeg[i] * Deg;
        Real64 const cosInc = std::cos(z) * ct + std::sin(z) * st * std::cos((p.azimuthDeg[i] - s.Azimuth) * Deg);
        Real64 const ghi = p.beamNormal[i] * std::max(std::cos(z), 0.0) + p.diffuseHoriz[i];
        q += alpha * (p.beamNormal[i] * std::max(cosInc, 0.0) + p.diffuseHoriz[i] * fSky + p.albedo[i] * ghi * fGnd);
        sky4 += std::pow(p.skyTempC[i] + Constant::Kelvin, 4);
        gnd4 += std::pow(p.groundSurfC[i] + Constant::Kelvin, 4);
        tAir += p.airTempC[i] + Constant::Kelvin;
        wind += p.windSpeed[i];
        pAmb += p.ambientPress[i];
    }
    q /= n;
    sky4 /= n;
    gnd4 /= n;
    tAir /= n;
    wind /= n;
    pAmb /= n;
    Real64 const lwIn = eps * Sigma * (fSky * sky4 + fGnd * gnd4);
    Real64 Lv, Lh, Lf;
    surfaceLengths(state, surfNum, Lv, Lh, Lf);
    auto balance = [&](Real64 T) {
        Real64 h = 0.0;
        if (p.body == Body::Mars) h = mixedConvection(p.atmosphere, T, tAir, pAmb, p.gravity, ct, s.ExtWind ? wind : 0.0, Lv, Lh, Lf);
        return q + lwIn + h * (tAir - T) - eps * (fSky + fGnd) * Sigma * T * T * T * T;
    };
    Real64 lo = 30.0, hi = 450.0;
    for (int it = 0; it < 80; ++it) {
        Real64 const mid = 0.5 * (lo + hi);
        if (balance(mid) > 0.0) {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    return 0.5 * (lo + hi) - Constant::Kelvin;
}

// ---------------------------------------------------------------------------------------------- input
// ---------------------------------------------------------------------------------------------- planetary weather file
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
        o << std::format("LOCATION,Thermonaut planetary site,-,-,PWF calendar,000000,{:.4f},{:.4f},{:.1f},0.0\n", lat, lon,
                         std::round(lon / 15.0));
        o << "DESIGN CONDITIONS,0\nTYPICAL/EXTREME PERIODS,0\nGROUND TEMPERATURES,0\nHOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0\n";
        o << "COMMENTS 1,Calendar only: Thermonaut reads every weather value from the planetary weather file\nCOMMENTS 2,\n";
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
                    std::format("Thermonaut: planetary weather file {} ({} records of {:g} s from {}); calendar EPW written to {}",
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
{
    auto &p = *state.dataPlanet;
    auto &ip = state.dataInputProcessing->inputProcessor;
    std::string const objName = "Site:PlanetaryBody";
    auto const instances = ip->epJSON.find(objName);
    if (instances == ip->epJSON.end()) return;
    auto const &props = ip->getObjectSchemaProps(state, objName);
    for (auto const &inst : instances.value().items()) {
        auto const &f = inst.value();
        ip->markObjectAsUsed(objName, inst.key());
        std::string const body = Util::makeUPPER(ip->getAlphaFieldValue(f, props, "body"));
        if (body == "MOON") {
            p.body = Body::Moon;
        } else if (body == "MARS") {
            p.body = Body::Mars;
        } else {
            p.body = Body::Earth;
        }
        p.active = (p.body != Body::Earth);
        p.referenceYear = int(ip->getRealFieldValue(f, props, "reference_year"));
        Real64 const g = ip->getRealFieldValue(f, props, "gravity");
        p.gravity = (g == Constant::AutoCalculate || g <= 0.0)
                        ? (p.body == Body::Moon ? MoonGravity : (p.body == Body::Mars ? MarsGravity : Constant::Gravity))
                        : g;
        p.cabinPressure = ip->getRealFieldValue(f, props, "cabin_pressure");
        p.cabinO2 = ip->getRealFieldValue(f, props, "cabin_oxygen_mole_fraction");
        p.cabinAirVelocity = ip->getRealFieldValue(f, props, "cabin_air_velocity");
        Real64 const L = ip->getRealFieldValue(f, props, "convection_vertical_length_scale");
        p.convLength = (L == Constant::AutoCalculate) ? -1.0 : L;
        p.horizonDeg = ip->getRealFieldValue(f, props, "horizon_elevation_angle");
        Real64 const ti = ip->getRealFieldValue(f, props, "regolith_thermal_inertia");
        p.regolithThermalInertia = (ti == Constant::AutoCalculate) ? 350.0 : ti;
        Real64 const alb = ip->getRealFieldValue(f, props, "regolith_albedo");
        p.regolithAlbedo = (alb == Constant::AutoCalculate) ? (p.body == Body::Moon ? 0.12 : 0.14) : alb;
        Real64 const em = ip->getRealFieldValue(f, props, "regolith_emissivity");
        p.regolithEmissivity = (em == Constant::AutoCalculate) ? (p.body == Body::Moon ? 0.95 : 0.97) : em;
        Real64 const su = ip->getRealFieldValue(f, props, "regolith_spin_up_cycles");
        p.spinUpCycles = (su == Constant::AutoCalculate) ? (p.body == Body::Moon ? 6 : 30) : int(su);
        p.deepDepth = ip->getRealFieldValue(f, props, "deep_regolith_depth");
        p.marsMeanPressure = ip->getRealFieldValue(f, props, "mars_mean_surface_pressure");
        std::string const dm = Util::makeUPPER(ip->getAlphaFieldValue(f, props, "mars_dust_optical_depth_model"));
        p.dustModel = (dm == "CONSTANT") ? DustModel::Constant : DustModel::Climatology;
        p.dustTauConstant = ip->getRealFieldValue(f, props, "mars_constant_dust_optical_depth");
        p.stormStartLs = ip->getRealFieldValue(f, props, "mars_dust_storm_start_solar_longitude");
        p.stormEndLs = ip->getRealFieldValue(f, props, "mars_dust_storm_end_solar_longitude");
        p.stormPeakTau = ip->getRealFieldValue(f, props, "mars_dust_storm_peak_optical_depth");
        p.windMean = ip->getRealFieldValue(f, props, "mars_mean_wind_speed");
        p.windAmplitude = ip->getRealFieldValue(f, props, "mars_diurnal_wind_speed_amplitude");
        auto const wf = f.find("planetary_weather_file_name");
        if (wf != f.end() && wf.value().is_string()) p.pwfPath = wf.value().get<std::string>();
    }
    if (!p.active) return;
    p.cabin = cabinGas(p.cabinO2);
    p.atmosphere = marsCO2();
    // apparent solar motion in degrees per clock hour (Earth clock)
    p.hourAngleRate = (p.body == Body::Moon) ? 360.0 / (SynodicMonthDays * 24.0) : 360.0 / (MarsSolSeconds / 3600.0);
    state.dataEnvrn->HourAngleRate = p.hourAngleRate;
    if (!p.pwfPath.empty()) readPlanetaryWeatherFile(state);
    if (p.horizonDeg < 0.0) {
        ShowSevereError(state, "Site:PlanetaryBody: a negative Horizon Elevation Angle is not supported in this version (use 0 or more).");
        ShowFatalError(state, "Program terminates due to the previous condition.");
    }
    ShowMessage(state,
                std::format("Thermonaut planetary mode: Body={}, gravity={:.3f} m/s2, cabin pressure={:.0f} Pa (zone air uses cabin pressure)",
                            p.body == Body::Moon ? "Moon" : "Mars",
                            p.gravity,
                            p.cabinPressure));
}

void ValidateInput(EnergyPlusData &state)
{
    auto &p = *state.dataPlanet;
    if (!p.active) return;
    auto &ip = state.dataInputProcessing->inputProcessor;
    // Objects that need outdoor air, Earth weather or an Earth-only model
    static constexpr std::array<std::string_view, 58> blocked = {"ZoneInfiltration:DesignFlowRate",
                                                                 "ZoneInfiltration:EffectiveLeakageArea",
                                                                 "ZoneInfiltration:FlowCoefficient",
                                                                 "SpaceInfiltration:DesignFlowRate",
                                                                 "SpaceInfiltration:EffectiveLeakageArea",
                                                                 "SpaceInfiltration:FlowCoefficient",
                                                                 "ZoneVentilation:DesignFlowRate",
                                                                 "ZoneVentilation:WindandStackOpenArea",
                                                                 "ZoneAirBalance:OutdoorAir",
                                                                 "ZoneEarthtube",
                                                                 "ZoneCoolTower:Shower",
                                                                 "ZoneThermalChimney",
                                                                 "AvailabilityManager:HybridVentilation",
                                                                 "SurfaceProperty:ExteriorNaturalVentedCavity",
                                                                 "AirflowNetwork:SimulationControl",
                                                                 "DesignSpecification:OutdoorAir",
                                                                 "OutdoorAir:Node",
                                                                 "OutdoorAir:NodeList",
                                                                 "OutdoorAir:Mixer",
                                                                 "Controller:OutdoorAir",
                                                                 "CoolingTower:SingleSpeed",
                                                                 "CoolingTower:TwoSpeed",
                                                                 "CoolingTower:VariableSpeed",
                                                                 "CoolingTower:VariableSpeed:Merkel",
                                                                 "FluidCooler:SingleSpeed",
                                                                 "FluidCooler:TwoSpeed",
                                                                 "EvaporativeFluidCooler:SingleSpeed",
                                                                 "EvaporativeFluidCooler:TwoSpeed",
                                                                 "EvaporativeCooler:Direct:CelDekPad",
                                                                 "EvaporativeCooler:Indirect:CelDekPad",
                                                                 "EvaporativeCooler:Indirect:WetCoil",
                                                                 "EvaporativeCooler:Indirect:ResearchSpecial",
                                                                 "EvaporativeCooler:Direct:ResearchSpecial",
                                                                 "Chiller:Electric:EIR",
                                                                 "Coil:Cooling:DX:SingleSpeed",
                                                                 "Coil:Cooling:DX:TwoSpeed",
                                                                 "Coil:Cooling:DX:MultiSpeed",
                                                                 "Coil:Cooling:DX:VariableSpeed",
                                                                 "Coil:Cooling:DX",
                                                                 "Coil:Heating:DX:SingleSpeed",
                                                                 "Coil:Heating:DX:MultiSpeed",
                                                                 "Coil:Heating:DX:VariableSpeed",
                                                                 "AirConditioner:VariableRefrigerantFlow",
                                                                 "ZoneHVAC:PackagedTerminalAirConditioner",
                                                                 "ZoneHVAC:PackagedTerminalHeatPump",
                                                                 "ZoneHVAC:WindowAirConditioner",
                                                                 "Generator:PVWatts",
                                                                 "Generator:WindTurbine",
                                                                 "Generator:CombustionTurbine",
                                                                 "Generator:InternalCombustionEngine",
                                                                 "Generator:MicroTurbine",
                                                                 "Generator:FuelCell",
                                                                 "Pipe:Outdoor",
                                                                 "Foundation:Kiva",
                                                                 "GroundHeatTransfer:Control",
                                                                 "SurfaceProperty:HeatTransferAlgorithm:MultipleSurface",
                                                                 "Daylighting:DELight:ComplexFenestration",
                                                                 "RoofIrrigation"};
    bool errors = false;
    for (auto const &obj : blocked) {
        if (ip->getNumObjectsFound(state, std::string(obj)) > 0) {
            ShowSevereError(state, std::format("Site:PlanetaryBody: {} objects are not supported off-Earth (they need outdoor air, Earth weather or an "
                                               "Earth-only model).",
                                               obj));
            errors = true;
        }
    }
    static constexpr std::array<std::string_view, 5> dd = {
        "SizingPeriod:DesignDay", "SizingPeriod:WeatherFileDays", "SizingPeriod:WeatherFileConditionType", "Sizing:Zone", "Sizing:System"};
    for (auto const &obj : dd) {
        if (ip->getNumObjectsFound(state, std::string(obj)) > 0) {
            ShowSevereError(state,
                            std::format("Site:PlanetaryBody: {} is not supported off-Earth in this version (design days use the Earth sun); "
                                        "use RunPeriod with ideal loads.",
                                        obj));
            errors = true;
        }
    }
    // HeatBalanceAlgorithm: only CTF and CondFD
    auto const hba = ip->epJSON.find("HeatBalanceAlgorithm");
    if (hba != ip->epJSON.end()) {
        for (auto const &inst : hba.value().items()) {
            auto const it = inst.value().find("algorithm");
            if (it != inst.value().end()) {
                std::string const a = Util::makeUPPER(it.value().get<std::string>());
                if (a != "CONDUCTIONTRANSFERFUNCTION" && a != "CONDUCTIONFINITEDIFFERENCE") {
                    ShowSevereError(state, "Site:PlanetaryBody: HeatBalanceAlgorithm must be ConductionTransferFunction or ConductionFiniteDifference.");
                    errors = true;
                }
            }
        }
    }
    // PV cell-temperature models fitted to Earth air, and Li-ion batteries that would sit in outdoor air
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

// ---------------------------------------------------------------------------------------------- environment
namespace {
    void setUpOutputs(EnergyPlusData &state)
    {
        auto &p = *state.dataPlanet;
        if (p.outputsSetUp) return;
        p.outputsSetUp = true;
        SetupOutputVariable(state,
                            "Site Planetary Ground Surface Temperature",
                            Constant::Units::C,
                            p.groundSurfCurrentC,
                            OutputProcessor::TimeStepType::Zone,
                            OutputProcessor::StoreType::Average,
                            "Environment");
        SetupOutputVariable(state,
                            "Site Planetary Deep Ground Temperature",
                            Constant::Units::C,
                            p.deepGroundC,
                            OutputProcessor::TimeStepType::Zone,
                            OutputProcessor::StoreType::Average,
                            "Environment");
        SetupOutputVariable(state,
                            "Site Planetary Ambient Pressure",
                            Constant::Units::Pa,
                            p.ambientPressCurrent,
                            OutputProcessor::TimeStepType::Zone,
                            OutputProcessor::StoreType::Average,
                            "Environment");
        SetupOutputVariable(state,
                            "Site Planetary Downwelling Longwave Radiation",
                            Constant::Units::W_m2,
                            p.downIRCurrent,
                            OutputProcessor::TimeStepType::Zone,
                            OutputProcessor::StoreType::Average,
                            "Environment");
        SetupOutputVariable(state,
                            "Site Planetary Sun Distance",
                            Constant::Units::None,
                            p.sunDistanceCurrent,
                            OutputProcessor::TimeStepType::Zone,
                            OutputProcessor::StoreType::Average,
                            "Environment");
        if (p.body == Body::Mars) {
            SetupOutputVariable(state,
                                "Site Planetary Solar Longitude",
                                Constant::Units::deg,
                                p.solarLongCurrent,
                                OutputProcessor::TimeStepType::Zone,
                                OutputProcessor::StoreType::Average,
                                "Environment");
            SetupOutputVariable(state,
                                "Site Planetary Dust Optical Depth",
                                Constant::Units::None,
                                p.dustTauCurrent,
                                OutputProcessor::TimeStepType::Zone,
                                OutputProcessor::StoreType::Average,
                                "Environment");
        }
    }

    // Build the whole environment of the current run period (mirrors exobem.environment.sites)
    void generateEnvironment(EnergyPlusData &state)
    {
        auto &p = *state.dataPlanet;
        auto const &envCurr = state.dataWeather->Environment(state.dataWeather->Envrn);
        int const N = state.dataGlobal->TimeStepsInHour;
        int const nDays = std::max(1, state.dataGlobal->NumOfDayInEnvrn) + 1;
        p.nDays = nDays;
        p.stepsPerHour = N;
        p.jd0 = julianDate(p.referenceYear, envCurr.StartMonth, envCurr.StartDay);
        Real64 const dt = 3600.0 / N;
        Real64 const lat = state.dataEnvrn->Latitude, lon = state.dataEnvrn->Longitude;
        Real64 const tzm = state.dataEnvrn->TimeZoneMeridian;
        size_t const n = size_t(nDays) * 24 * N;

        // 1. per-day solar fit: declination and an equation of time such that the engine's hour angle
        //    rate*(12-(t+EoT)) + (TZM-Lon) equals minus the true hour angle at 12:00 UTC
        p.daySinDec.assign(nDays + 1, 0.0);
        p.dayCosDec.assign(nDays + 1, 1.0);
        p.dayEoT.assign(nDays + 1, 0.0);
        p.dayDistAU.assign(nDays + 1, 1.0);
        std::vector<Real64> dayH12(nDays + 1, 0.0), dayDec(nDays + 1, 0.0);
        for (int d = 1; d <= nDays; ++d) {
            SunPosition const sp = sunPosition(p.body, p.jd0 + (d - 1) + 0.5, lat, lon);
            dayH12[d] = sp.hourAngle;
            dayDec[d] = sp.declination;
            p.daySinDec[d] = std::sin(sp.declination * Deg);
            p.dayCosDec[d] = std::cos(sp.declination * Deg);
            p.dayEoT[d] = (sp.hourAngle + (tzm - lon)) / p.hourAngleRate;
            p.dayDistAU[d] = sp.distanceAU;
        }

        // 2. per-step sun (end of timestep, the engine's convention) from the same daily fit
        std::vector<Real64> mu(n), zen(n), Ls(n, 0.0), rAU(n, 1.0), hourAngle(n, 0.0), azim(n, 0.0);
        for (int d = 1; d <= nDays; ++d) {
            for (int hr = 1; hr <= 24; ++hr) {
                for (int ts = 1; ts <= N; ++ts) {
                    size_t const i = (size_t(d - 1) * 24 + (hr - 1)) * N + (ts - 1);
                    Real64 const tClock = (hr - 1) + Real64(ts) / N;
                    Real64 const H = wrap180(dayH12[d] + p.hourAngleRate * (tClock - 12.0));
                    Real64 z, az;
                    horizontalGeometry(lat, dayDec[d], H, z, az);
                    zen[i] = z;
                    azim[i] = az;
                    mu[i] = std::cos(z * Deg);
                    hourAngle[i] = H;
                    SunPosition const sp = sunPosition(p.body, p.jd0 + (d - 1) + tClock / 24.0, lat, lon);
                    Ls[i] = sp.solarLongitude;
                    rAU[i] = sp.distanceAU;
                }
            }
        }

        p.beamNormal.assign(n, 0.0);
        p.diffuseHoriz.assign(n, 0.0);
        p.skyTempC.assign(n, CosmicBackgroundK - Constant::Kelvin);
        p.airTempC.assign(n, 0.0);
        p.ambientPress.assign(n, 0.0);
        p.windSpeed.assign(n, 0.0);
        p.groundSurfC.assign(n, 0.0);
        p.albedo.assign(n, p.regolithAlbedo);
        p.solarLong = Ls;
        p.dustTau.assign(n, 0.0);
        p.downIR.assign(n, Sigma * std::pow(CosmicBackgroundK, 4));
        p.zenithDeg = zen;
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
            ShowMessage(state, std::format("Thermonaut: environment for {} days read from the planetary weather file, deep regolith {:.1f} C",
                                           nDays, p.deepGroundC));
            return;
        }

        if (p.body == Body::Moon) {
            RegolithColumn col;
            col.albedo0 = p.regolithAlbedo;
            col.emissivity = p.regolithEmissivity;
            col.build();
            std::vector<Real64> qAbs(n), Ld(n, 0.0);
            for (size_t i = 0; i < n; ++i) {
                Real64 const elev = 90.0 - zen[i];
                Real64 const vis = (mu[i] > DataEnvironment::SunIsUpValue)
                                       ? horizonVisibleFraction(elev, p.horizonDeg, SunAngularRadius1AU / rAU[i])
                                       : 0.0;
                p.beamNormal[i] = SolarIrradiance1AU / (rAU[i] * rAU[i]) * vis;
                p.albedo[i] = col.albedo(zen[i]);
                qAbs[i] = (1.0 - p.albedo[i]) * p.beamNormal[i] * std::max(mu[i], 0.0);
            }
            // spin up on the synodic month before the start (true ephemeris, step mid-points)
            int const nCyc = int(std::lround(SynodicMonthDays * 86400.0 / dt));
            std::vector<Real64> qS(nCyc), LdS(nCyc, 0.0);
            for (int i = 0; i < nCyc; ++i) {
                Real64 const jd = p.jd0 - SynodicMonthDays + (i + 0.5) * dt / 86400.0;
                SunPosition const sp = sunPosition(p.body, jd, lat, lon);
                Real64 const vis = horizonVisibleFraction(90.0 - sp.zenith, p.horizonDeg, SunAngularRadius1AU);
                Real64 const g = SolarIrradiance1AU / (sp.distanceAU * sp.distanceAU) * vis * std::max(std::cos(sp.zenith * Deg), 0.0);
                qS[i] = (1.0 - col.albedo(sp.zenith)) * g;
            }
            // periodic equilibrium of the column over the preceding Earth year (1 h steps)
            std::vector<Real64> T, meanSpin, surf, meanRun;
            {
                constexpr Real64 dty = 3600.0;
                int const ny = int(std::lround(365.25 * 86400.0 / dty));
                std::vector<Real64> qY(ny), LdY(ny, 0.0);
                for (int i = 0; i < ny; ++i) {
                    Real64 const jd = p.jd0 - 365.25 + (i + 0.5) * dty / 86400.0;
                    SunPosition const sp = sunPosition(p.body, jd, lat, lon);
                    Real64 const vis = horizonVisibleFraction(90.0 - sp.zenith, p.horizonDeg, SunAngularRadius1AU);
                    Real64 const g = SolarIrradiance1AU / (sp.distanceAU * sp.distanceAU) * vis * std::max(std::cos(sp.zenith * Deg), 0.0);
                    qY[i] = (1.0 - col.albedo(sp.zenith)) * g;
                }
                equilibrateColumn(col, dty, qY, LdY, 0.15, T);
            }
            col.run(dt, qS, LdS, T, false, 1, nCyc, nullptr, &meanSpin);
            col.run(dt, qAbs, Ld, T, false, 0, 0, &surf, &meanRun);
            p.deepGroundC = meanRun[col.nodeNearest(p.deepDepth)] - Constant::Kelvin;
            for (size_t i = 0; i < n; ++i) {
                p.groundSurfC[i] = surf[i] - Constant::Kelvin;
                p.airTempC[i] = p.groundSurfC[i]; // no air: carries the ground temperature (see DESIGN.md)
            }
        } else {
            // Mars
            constexpr Real64 w0 = 0.885, gAsym = 0.74, Rh = 3390.0 / 11.0;
            // sky emissivity e0 + e1*tau (cap 0.6) and dust re-emission fRe, calibrated to the MEDA/TIRS clear-season
            // mean (~30 W/m2) and the 2018 storm (sol-mean air -4 K): ExoBEM studies/calibrate_mars_storm_ir.py
            constexpr Real64 kappa = 0.6, lagH = 0.5, e0 = 0.12, e1 = 0.10, fRe = 0.20;
            RegolithColumn col = RegolithColumn::mars(p.regolithThermalInertia, p.regolithAlbedo, p.regolithEmissivity);
            col.build();
            std::vector<Real64> ghi(n), gTop(n), epsSky(n);
            for (size_t i = 0; i < n; ++i) {
                Real64 const tau = (p.dustModel == DustModel::Constant) ? p.dustTauConstant
                                                                        : marsDustTau(Ls[i], p.stormStartLs, p.stormEndLs, p.stormPeakTau);
                p.dustTau[i] = tau;
                Real64 const S = SolarIrradiance1AU / (rAU[i] * rAU[i]);
                Real64 const m0 = std::max(mu[i], 0.0);
                Real64 const am = std::sqrt((Rh * m0) * (Rh * m0) + 2.0 * Rh + 1.0) - Rh * m0;
                Real64 const muEff = 1.0 / am;
                Real64 dfrac, sfrac;
                deltaEddingtonSurface(tau, muEff, w0, gAsym, p.regolithAlbedo, dfrac, sfrac);
                bool const up = mu[i] > DataEnvironment::SunIsUpValue;
                Real64 const vis = horizonVisibleFraction(90.0 - zen[i], p.horizonDeg, SunAngularRadius1AU / rAU[i]);
                gTop[i] = S * m0;
                // beam from the solar disk: Beer's law with the true optical depth; the forward-scattering peak
                // of the delta-Eddington "direct" flux is counted as diffuse
                Real64 const beer = std::exp(-tau * am);
                Real64 const directH = up ? gTop[i] * beer * vis : 0.0;
                Real64 const diffuseH = up ? std::max(gTop[i] * (dfrac + sfrac) - gTop[i] * beer, 0.0) : 0.0;
                p.beamNormal[i] = up ? directH / std::max(mu[i], 1e-6) : 0.0;
                p.diffuseHoriz[i] = diffuseH;
                ghi[i] = directH + diffuseH;
                p.ambientPress[i] = marsSurfacePressure(Ls[i], p.marsMeanPressure);
                epsSky[i] = clamp(e0 + e1 * tau, 0.05, 0.6);
            }
            int const nSol = int(std::lround(MarsSolSeconds / dt));
            int const k = std::max(1, nSol);
            int const lag = int(std::lround(lagH * 3600.0 / dt));
            std::vector<Real64> deficit(n), qAbs(n);
            for (size_t i = 0; i < n; ++i) {
                deficit[i] = gTop[i] - ghi[i];
                qAbs[i] = (1.0 - p.regolithAlbedo) * ghi[i];
            }
            std::vector<Real64> Ldust = trailingMean(deficit, k);
            std::vector<Real64> Ldown(n);
            for (size_t i = 0; i < n; ++i) {
                Ldust[i] *= fRe;
                Ldown[i] = epsSky[i] * Sigma * std::pow(210.0, 4) + Ldust[i];
            }
            int const m = std::min<int>(nSol, int(n));
            std::vector<Real64> qSol(qAbs.begin(), qAbs.begin() + m), LdSol(Ldown.begin(), Ldown.begin() + m);
            std::vector<Real64> Tspin, surf, meanProf, Tair(n);
            {
                // periodic equilibrium of the column over the preceding Mars year (1 h steps)
                constexpr Real64 dty = 3600.0;
                int const ny = int(std::lround(668.6 * MarsSolSeconds / dty));
                std::vector<Real64> qY(ny), dY(ny), LdY(ny), eY(ny);
                for (int i = 0; i < ny; ++i) {
                    Real64 const jd = p.jd0 - ny * dty / 86400.0 + (i + 0.5) * dty / 86400.0;
                    SunPosition const sp = sunPosition(p.body, jd, lat, lon);
                    Real64 const tau = (p.dustModel == DustModel::Constant) ? p.dustTauConstant
                                                                            : marsDustTau(sp.solarLongitude, p.stormStartLs, p.stormEndLs,
                                                                                          p.stormPeakTau);
                    Real64 const S = SolarIrradiance1AU / (sp.distanceAU * sp.distanceAU);
                    Real64 const mu0 = std::cos(sp.zenith * Deg);
                    Real64 const m0 = std::max(mu0, 0.0);
                    Real64 const am = std::sqrt((Rh * m0) * (Rh * m0) + 2.0 * Rh + 1.0) - Rh * m0;
                    Real64 df, sf;
                    deltaEddingtonSurface(tau, 1.0 / am, w0, gAsym, p.regolithAlbedo, df, sf);
                    bool const upY = mu0 > DataEnvironment::SunIsUpValue;
                    Real64 const visY = horizonVisibleFraction(90.0 - sp.zenith, p.horizonDeg, SunAngularRadius1AU / sp.distanceAU);
                    Real64 const gt = S * m0;
                    Real64 const beer = std::exp(-tau * am);
                    Real64 const ghiY = upY ? gt * beer * visY + std::max(gt * (df + sf) - gt * beer, 0.0) : 0.0;
                    qY[i] = (1.0 - p.regolithAlbedo) * ghiY;
                    dY[i] = gt - ghiY;
                    eY[i] = clamp(e0 + e1 * tau, 0.05, 0.6);
                }
                std::vector<Real64> const LdustY = trailingMean(dY, std::max(1, int(std::lround(MarsSolSeconds / dty))));
                for (int i = 0; i < ny; ++i) {
                    LdY[i] = fRe * LdustY[i] + eY[i] * Sigma * std::pow(210.0, 4);
                }
                equilibrateColumn(col, dty, qY, LdY, 0.25, Tspin);
            }
            col.run(dt, qSol, LdSol, Tspin, false, std::min(p.spinUpCycles, 5), nSol, nullptr, nullptr);
            for (int iter = 0; iter < 4; ++iter) {
                std::vector<Real64> T = Tspin;
                col.run(dt, qAbs, Ldown, T, false, 0, 0, &surf, &meanProf);
                std::vector<Real64> const Tmean = trailingMean(surf, k);
                Real64 maxChange = 0.0;
                std::vector<Real64> Lnew(n);
                for (size_t i = 0; i < n; ++i) {
                    Real64 const Tlag = (int(i) - lag >= 0) ? surf[i - lag] : surf[0];
                    Tair[i] = Tmean[i] + kappa * (Tlag - Tmean[i]);
                    Lnew[i] = epsSky[i] * Sigma * std::pow(Tair[i], 4) + Ldust[i];
                    maxChange = std::max(maxChange, std::abs(Lnew[i] - Ldown[i]));
                }
                Ldown = Lnew;
                if (maxChange < 0.05) break;
                std::vector<Real64> LdSol2(Ldown.begin(), Ldown.begin() + m);
                col.run(dt, qSol, LdSol2, Tspin, false, p.spinUpCycles, nSol, nullptr, nullptr);
            }
            p.deepGroundC = meanProf[col.nodeNearest(p.deepDepth)] - Constant::Kelvin;
            for (size_t i = 0; i < n; ++i) {
                p.groundSurfC[i] = surf[i] - Constant::Kelvin;
                p.airTempC[i] = Tair[i] - Constant::Kelvin;
                p.downIR[i] = Ldown[i];
                p.skyTempC[i] = std::pow(Ldown[i] / Sigma, 0.25) - Constant::Kelvin;
                Real64 const ltst = 12.0 + hourAngle[i] / 15.0;
                p.windSpeed[i] = std::max(0.3, p.windMean + p.windAmplitude * std::sin(2.0 * Constant::Pi * (ltst - 9.0) / 24.0));
            }
        }
        p.generatedEnvrn = state.dataWeather->Envrn;
        ShowMessage(state,
                    std::format("Thermonaut: generated {} environment for {} days ({} steps), deep regolith temperature {:.1f} C",
                                p.body == Body::Moon ? "lunar" : "Martian",
                                nDays,
                                n,
                                p.deepGroundC));
    }
} // namespace

void FillTomorrow(EnergyPlusData &state, int dayIndex)
{
    auto &p = *state.dataPlanet;
    if (!p.active) return;
    setUpOutputs(state);
    if (p.generatedEnvrn != state.dataWeather->Envrn || p.stepsPerHour != state.dataGlobal->TimeStepsInHour) {
        generateEnvironment(state);
    }
    int const d = std::max(1, std::min(dayIndex, p.nDays));
    p.tomorrowIndex = d;
    auto &tv = state.dataWeather->TomorrowVariables;
    tv.SinSolarDeclinAngle = p.daySinDec[d];
    tv.CosSolarDeclinAngle = p.dayCosDec[d];
    tv.EquationOfTime = p.dayEoT[d];
    int const N = p.stepsPerHour;
    for (int hr = 1; hr <= 24; ++hr) {
        for (int ts = 1; ts <= N; ++ts) {
            size_t const i = (size_t(d - 1) * 24 + (hr - 1)) * N + (ts - 1);
            auto &w = state.dataWeather->wvarsHrTsTomorrow(ts, hr);
            w.OutDryBulbTemp = p.airTempC[i];
            w.OutDewPointTemp = p.airTempC[i];
            w.OutRelHum = 0.0;
            w.OutBaroPress = p.cabinPressure; // option B: zone/HVAC air at cabin pressure
            w.WindSpeed = p.windSpeed[i];
            w.WindDir = 180.0;
            w.SkyTemp = p.skyTempC[i];
            w.HorizIRSky = p.downIR[i];
            w.BeamSolarRad = p.beamNormal[i];
            w.DifSolarRad = p.diffuseHoriz[i];
            w.Albedo = p.albedo[i];
            w.IsRain = false;
            w.IsSnow = false;
            w.LiquidPrecip = 0.0;
            w.WaterPrecip = 0.0;
            w.TotalSkyCover = 0.0;
            w.OpaqueSkyCover = 0.0;
        }
    }
}

void AdvanceDay(EnergyPlusData &state)
{
    auto &p = *state.dataPlanet;
    if (!p.active) return;
    p.todayIndex = p.tomorrowIndex;
}

void SetCurrentWeather(EnergyPlusData &state)
{
    auto &p = *state.dataPlanet;
    if (!p.active || p.generatedEnvrn < 0) return;
    int const N = p.stepsPerHour;
    int const d = std::max(1, std::min(p.todayIndex, p.nDays));
    size_t const i = (size_t(d - 1) * 24 + (state.dataGlobal->HourOfDay - 1)) * N + (state.dataGlobal->TimeStep - 1);
    if (i >= p.groundSurfC.size()) return;
    p.groundSurfCurrentC = p.groundSurfC[i];
    p.ambientPressCurrent = p.ambientPress[i];
    p.solarLongCurrent = p.solarLong[i];
    p.dustTauCurrent = p.dustTau[i];
    p.downIRCurrent = p.downIR[i];
    p.sunDistanceCurrent = p.dayDistAU[d];
    auto &env = *state.dataEnvrn;
    env.AmbientBaroPress = p.ambientPressCurrent;
    env.OutHumRat = 0.0;
    env.OutWetBulbTemp = env.OutDryBulbTemp;
    env.OutDewPointTemp = env.OutDryBulbTemp;
    env.OutEnthalpy = Psychrometrics::PsyHFnTdbW(env.OutDryBulbTemp, 0.0);
    env.OutAirDensity = p.cabinPressure / (287.0 * (env.OutDryBulbTemp + Constant::Kelvin));
    Real64 const deep = p.deepGroundC;
    for (auto &gt : env.GroundTemp) {
        gt = deep;
    }
    env.GroundTempKelvin = deep + Constant::Kelvin;
    env.GndReflectance = p.albedo[i];
    env.GndReflectanceForDayltg = p.albedo[i];
    env.IsRain = false;
    env.IsSnow = false;
    env.GndSolarRad = std::max((env.BeamSolarRad * env.SOLCOS.z + env.DifSolarRad) * env.GndReflectance, 0.0);
    if (!env.SunIsUp) env.GndSolarRad = 0.0;
}

} // namespace EnergyPlus::Planetary
