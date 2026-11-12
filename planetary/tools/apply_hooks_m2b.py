"""Thermonaut M2b patch set: physics corrections from an independent review of the planetary equations.

Run from the repository root:  python planetary/tools/apply_hooks_m2b.py   (idempotent)

* visible fraction of the solar disk above the horizon by area, not linearly in elevation;
* Mars direct beam from Beer's law with the true optical depth (the delta-Eddington forward peak is diffuse);
* Mars seasonal pressure cycle with its minimum near Ls 157 and maximum near Ls 269 (sign of the fit fixed);
* cabin gas specific heat weighted by the N2 and O2 mass fractions;
* deep-regolith temperature from a periodic equilibrium of the column over the preceding (Earth or Mars)
  year instead of a short spin-up from a guessed profile.
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
    print("patched", p.name, "|", marker[:60])


edit(C, '''    Real64 horizonVisibleFraction(Real64 elevDeg, Real64 horizonDeg, Real64 sunRadiusDeg)
    {
        return clamp((elevDeg - horizonDeg + sunRadiusDeg) / (2.0 * sunRadiusDeg), 0.0, 1.0);
    }''', '''    Real64 horizonVisibleFraction(Real64 elevDeg, Real64 horizonDeg, Real64 sunRadiusDeg)
    {
        // area of a uniform disk above a straight horizon
        Real64 const x = clamp((elevDeg - horizonDeg) / sunRadiusDeg, -1.0, 1.0);
        return (std::acos(-x) + x * std::sqrt(1.0 - x * x)) / Constant::Pi;
    }''', "area of a uniform disk above a straight horizon")

edit(C, '''    g.cp = 1005.0 - 120.0 * (x - 0.21);''', '''    Real64 const yO2 = x * 0.031999 / g.molarMass; // O2 mass fraction
    g.cp = yO2 * 918.0 + (1.0 - yO2) * 1040.0;      // cp of O2 and N2 at 300 K, mass weighted''', "Real64 const yO2 = x * 0.031999")

edit(C, '''    return pMean * (1.0 + 0.074 * std::sin(L - 26.0 * Deg) + 0.055 * std::sin(2.0 * L + 110.0 * Deg));''',
     '''    // minimum near Ls 157 (southern cap growth), maximum near Ls 269, secondary maximum near Ls 64
    return pMean * (1.0 + 0.074 * std::sin(L + 154.0 * Deg) + 0.055 * std::sin(2.0 * L + 290.0 * Deg));''',
     "minimum near Ls 157 (southern cap growth)")

# periodic equilibrium of the regolith column
edit(C, '''    // trailing running mean over k samples (current included), padded with the mean of the first k''',
     '''    // Periodic equilibrium for a forcing that repeats with its own length:
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

    // trailing running mean over k samples (current included), padded with the mean of the first k''',
     "void equilibrateColumn(RegolithColumn const &col")

# Moon: equilibrium over the preceding year, then one synodic-month spin-up; deep temperature from the run
edit(C, '''            std::vector<Real64> T, meanSpin, surf;
            col.run(dt, qS, LdS, T, true, p.spinUpCycles, nCyc, nullptr, &meanSpin);
            col.run(dt, qAbs, Ld, T, false, 0, 0, &surf, nullptr);
            Real64 deep = 0.0;
            for (int j = col.n - 5; j < col.n; ++j) {
                deep += meanSpin[j];
            }
            p.deepGroundC = deep / 5.0 - Constant::Kelvin;''',
     '''            // periodic equilibrium of the column over the preceding Earth year (1 h steps)
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
            p.deepGroundC = meanRun[col.nodeNearest(p.deepDepth)] - Constant::Kelvin;''',
     "periodic equilibrium of the column over the preceding Earth year")

# Mars: Beer-law beam; delta-Eddington total; the rest diffuse
edit(C, '''                gTop[i] = S * m0;
                Real64 const directH = up ? gTop[i] * dfrac * vis : 0.0;
                Real64 const diffuseH = up ? S * m0 * sfrac : 0.0;''',
     '''                gTop[i] = S * m0;
                // beam from the solar disk: Beer's law with the true optical depth; the forward-scattering peak
                // of the delta-Eddington "direct" flux is counted as diffuse
                Real64 const beer = std::exp(-tau * am);
                Real64 const directH = up ? gTop[i] * beer * vis : 0.0;
                Real64 const diffuseH = up ? std::max(gTop[i] * (dfrac + sfrac) - gTop[i] * beer, 0.0) : 0.0;''',
     "beam from the solar disk: Beer's law with the true optical depth")

# Mars: equilibrium over the preceding Mars year before the first-sol spin-up; deep temperature at deepDepth
edit(C, '''            std::vector<Real64> Tspin, surf, meanProf, Tair(n);
            col.run(dt, qSol, LdSol, Tspin, true, p.spinUpCycles, nSol, nullptr, nullptr);''',
     '''            std::vector<Real64> Tspin, surf, meanProf, Tair(n);
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
            col.run(dt, qSol, LdSol, Tspin, false, std::min(p.spinUpCycles, 5), nSol, nullptr, nullptr);''',
     "periodic equilibrium of the column over the preceding Mars year")
edit(C, '''            p.deepGroundC = meanProf.back() - Constant::Kelvin;''',
     '''            p.deepGroundC = meanProf[col.nodeNearest(p.deepDepth)] - Constant::Kelvin;''',
     "p.deepGroundC = meanProf[col.nodeNearest(p.deepDepth)]")
print("done")
