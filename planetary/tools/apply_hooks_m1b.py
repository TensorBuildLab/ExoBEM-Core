"""ExoBEM-Core M1 second patch set: steady start-up profile for CondFD, no outdoor moisture off-Earth.

Run from the repository root:  python planetary/tools/apply_hooks_m1b.py   (idempotent)
"""
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "EnergyPlus"


def edit(rel, old, new):
    p = SRC / rel
    s = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in s
    s = s.replace("\r\n", "\n")
    if new in s:
        return
    assert s.count(old) == 1, (rel, s.count(old), old[:100])
    s = s.replace(old, new)
    if crlf:
        s = s.replace("\n", "\r\n")
    p.write_bytes(s.encode("utf-8"))
    print("patched", rel)


edit("PlanetaryBody.hh", "    Real64 groundLongwaveTempC(EnergyPlusData const &state, Real64 defaultC);\n",
     "    Real64 groundLongwaveTempC(EnergyPlusData const &state, Real64 defaultC);\n"
     "    // Mean outer-face temperature of a surface under the period-mean planetary environment (steady radiative balance);\n"
     "    // used to start conduction profiles near their steady state (regolith time constants are months to years).\n"
     "    Real64 meanOuterFaceTempC(EnergyPlusData &state, int surfNum);\n")
edit("PlanetaryBody.hh", "        downIR, zenithDeg;\n", "        downIR, zenithDeg, azimuthDeg;\n")

edit("PlanetaryBody.cc", "        std::vector<Real64> mu(n), zen(n), Ls(n, 0.0), rAU(n, 1.0), hourAngle(n, 0.0);\n",
     "        std::vector<Real64> mu(n), zen(n), Ls(n, 0.0), rAU(n, 1.0), hourAngle(n, 0.0), azim(n, 0.0);\n")
edit("PlanetaryBody.cc", "                    zen[i] = z;\n                    mu[i] = std::cos(z * Deg);\n",
     "                    zen[i] = z;\n                    azim[i] = az;\n                    mu[i] = std::cos(z * Deg);\n")
edit("PlanetaryBody.cc", "        p.zenithDeg = zen;\n", "        p.zenithDeg = zen;\n        p.azimuthDeg = azim;\n")
edit("PlanetaryBody.cc", "#include <EnergyPlus/DataEnvironment.hh>\n",
     "#include <EnergyPlus/Construction.hh>\n#include <EnergyPlus/DataEnvironment.hh>\n")

MEAN_FACE = r'''Real64 meanOuterFaceTempC(EnergyPlusData &state, int surfNum)
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
'''
edit("PlanetaryBody.cc", "// ---------------------------------------------------------------------------------------------- input\n", MEAN_FACE)

PROFILE = '''                state.dataMstBal->HSkyFD(SurfNum) = 0.0;
                state.dataMstBal->HGrndFD(SurfNum) = 0.0;
                state.dataMstBal->HAirFD(SurfNum) = 0.0;

                // ExoBEM-Core: start from the steady conduction profile (resistance-weighted between the mean outer-face
                // temperature and the initial zone temperature); a 1 m regolith cover needs months to years to settle
                if (state.dataPlanet->active && state.dataPlanet->generatedEnvrn >= 0) {
                    Real64 const tOut = Planetary::meanOuterFaceTempC(state, SurfNum);
                    auto const &cFD = s_hbfd->ConstructFD(ConstrNum);
                    auto const &con = state.dataConstruction->Construct(ConstrNum);
                    int const nT = cFD.TotNodes + 1;
                    if (tOut > -900.0 && nT > 1 && int(thisSurface.TDT.size()) >= nT) {
                        std::vector<Real64> R(nT + 1, 0.0);
                        int node = 0;
                        for (int Layer = 1; Layer <= con.TotLayers; ++Layer) {
                            auto const *mat = state.dataMaterial->materials(con.LayerPoint(Layer));
                            for (int ln = 1; ln <= cFD.NodeNumPoint(Layer); ++ln) {
                                ++node;
                                if (node < nT) R[node + 1] = R[node] + cFD.DelX(Layer) / std::max(mat->Conductivity, 1e-12);
                            }
                        }
                        Real64 const Rtot = std::max(R[nT], 1e-12);
                        for (int i = 1; i <= nT; ++i) {
                            Real64 const Ti = tOut + (TempInitValue - tOut) * R[i] / Rtot;
                            thisSurface.T(i) = thisSurface.TOld(i) = thisSurface.TT(i) = Ti;
                            thisSurface.TD(i) = thisSurface.TDT(i) = thisSurface.TDTLast(i) = Ti;
                            thisSurface.TDOld(i) = thisSurface.TDreport(i) = Ti;
                        }
                    }
                }
            }
            s_hbfd->WarmupSurfTemp = 0;
'''
edit("HeatBalFiniteDiffManager.cc",
     "                state.dataMstBal->HSkyFD(SurfNum) = 0.0;\n                state.dataMstBal->HGrndFD(SurfNum) = 0.0;\n"
     "                state.dataMstBal->HAirFD(SurfNum) = 0.0;\n            }\n            s_hbfd->WarmupSurfTemp = 0;\n", PROFILE)

edit("HeatBalanceSurfaceManager.cc",
     "                                state.dataMstBal->TempOutsideAirFD(SurfNum) = TempExt;\n"
     "                                state.dataMstBal->RhoVaporAirOut(SurfNum) = Psychrometrics::PsyRhovFnTdbWPb(\n"
     "                                    state.dataMstBal->TempOutsideAirFD(SurfNum), state.dataEnvrn->OutHumRat, state.dataEnvrn->OutBaroPress);\n"
     "                                state.dataMstBal->HConvExtFD(SurfNum) = state.dataHeatBalSurf->SurfHConvExt(SurfNum);\n",
     "                                state.dataMstBal->TempOutsideAirFD(SurfNum) = TempExt;\n"
     "                                state.dataMstBal->HConvExtFD(SurfNum) = state.dataHeatBalSurf->SurfHConvExt(SurfNum);\n"
     "                                if (state.dataPlanet->active) { // ExoBEM-Core: no outdoor moisture exchange off-Earth\n"
     "                                    state.dataMstBal->RhoVaporAirOut(SurfNum) = 0.0;\n"
     "                                    state.dataMstBal->HMassConvExtFD(SurfNum) = 0.0;\n"
     "                                } else {\n"
     "                                state.dataMstBal->RhoVaporAirOut(SurfNum) = Psychrometrics::PsyRhovFnTdbWPb(\n"
     "                                    state.dataMstBal->TempOutsideAirFD(SurfNum), state.dataEnvrn->OutHumRat, state.dataEnvrn->OutBaroPress);\n")
edit("HeatBalanceSurfaceManager.cc",
     "                                if (state.dataMstBal->RhoVaporAirOut(SurfNum) > RhoVaporSat) {\n"
     "                                    state.dataMstBal->RhoVaporAirOut(SurfNum) = RhoVaporSat;\n"
     "                                }\n"
     "                                state.dataMstBal->HSkyFD(SurfNum) = state.dataHeatBalSurf->SurfHSkyExt(SurfNum);\n",
     "                                if (state.dataMstBal->RhoVaporAirOut(SurfNum) > RhoVaporSat) {\n"
     "                                    state.dataMstBal->RhoVaporAirOut(SurfNum) = RhoVaporSat;\n"
     "                                }\n"
     "                                } // ExoBEM-Core\n"
     "                                state.dataMstBal->HSkyFD(SurfNum) = state.dataHeatBalSurf->SurfHSkyExt(SurfNum);\n")
print("done")
