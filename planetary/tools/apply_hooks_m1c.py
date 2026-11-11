"""Thermonaut M1 third patch set: CondFD steady start-up profile with k(T) and a post-warm-up correction.

Run from the repository root:  python planetary/tools/apply_hooks_m1c.py   (idempotent)
"""
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "EnergyPlus"
F = SRC / "HeatBalFiniteDiffManager.cc"
s = F.read_bytes().decode("utf-8")
crlf = "\r\n" in s
s = s.replace("\r\n", "\n")

if "planetarySteadyProfile" not in s:
    # 1. replace the inline profile block by a call to the helper
    a = s.index("                // Thermonaut: start from the steady conduction profile")
    b = s.index("            s_hbfd->WarmupSurfTemp = 0;\n", a)
    block = '''                // Thermonaut: start from the steady conduction profile between the mean outer-face temperature and the
                // initial zone temperature; a 1 m regolith cover needs months to years to settle (corrected after warm-up)
                if (state.dataPlanet->active && state.dataPlanet->generatedEnvrn >= 0) {
                    std::vector<Real64> prof;
                    if (planetarySteadyProfile(state, SurfNum, TempInitValue, prof)) {
                        for (int i = 1; i <= int(prof.size()); ++i) {
                            Real64 const Ti = prof[i - 1];
                            thisSurface.T(i) = thisSurface.TOld(i) = thisSurface.TT(i) = Ti;
                            thisSurface.TD(i) = thisSurface.TDT(i) = thisSurface.TDTLast(i) = Ti;
                            thisSurface.TDOld(i) = thisSurface.TDreport(i) = Ti;
                        }
                    }
                }
            }
            state.dataPlanet->condFDCorrected = false;
'''
    s = s[:a] + block + s[b:]

    # 2. correction at the first time step after warm-up
    anchor = "        // now do every timestep inits\n"
    assert s.count(anchor) == 1
    corr = '''        // Thermonaut: after warm-up the inside faces sit at their real temperature; shift the deep part of each start-up
        // profile accordingly (the correction is zero at the outer face, so the converged day/night structure is kept)
        if (state.dataPlanet->active && !state.dataGlobal->WarmupFlag && !state.dataPlanet->condFDCorrected) {
            state.dataPlanet->condFDCorrected = true;
            for (int SurfNum = 1; SurfNum <= state.dataSurface->TotSurfaces; ++SurfNum) {
                auto const &surf = state.dataSurface->Surface(SurfNum);
                if (surf.HeatTransferAlgorithm != DataSurfaces::HeatTransferModel::CondFD || surf.Construction <= 0 ||
                    state.dataConstruction->Construct(surf.Construction).TypeIsWindow) {
                    continue;
                }
                auto &sfd = SurfaceFD(SurfNum);
                int const nT = s_hbfd->ConstructFD(surf.Construction).TotNodes + 1;
                std::vector<Real64> pOld, pNew;
                if (!planetarySteadyProfile(state, SurfNum, TempInitValue, pOld)) continue;
                if (!planetarySteadyProfile(state, SurfNum, sfd.TDT(nT), pNew)) continue;
                for (int i = 1; i <= nT; ++i) {
                    Real64 const d = pNew[i - 1] - pOld[i - 1];
                    sfd.T(i) += d;
                    sfd.TOld(i) += d;
                    sfd.TT(i) += d;
                    sfd.TD(i) += d;
                    sfd.TDT(i) += d;
                    sfd.TDTLast(i) += d;
                    sfd.TDOld(i) += d;
                    sfd.TDreport(i) += d;
                }
            }
        }

'''
    s = s.replace(anchor, corr + anchor)

    # 3. the helper (before InitHeatBalFiniteDiff)
    fn = "    void InitHeatBalFiniteDiff(EnergyPlusData &state)\n"
    assert s.count(fn) == 1
    helper = '''    // Thermonaut: steady conduction profile through a CondFD construction between the mean outer-face temperature
    // (planetary environment) and an inside-face temperature tIn; conductivity follows each layer's k(T) table.
    static bool planetarySteadyProfile(EnergyPlusData &state, int SurfNum, Real64 tIn, std::vector<Real64> &prof)
    {
        auto &s_hbfd = state.dataHeatBalFiniteDiffMgr;
        int const ConstrNum = state.dataSurface->Surface(SurfNum).Construction;
        Real64 const tOut = Planetary::meanOuterFaceTempC(state, SurfNum);
        auto const &cFD = s_hbfd->ConstructFD(ConstrNum);
        auto const &con = state.dataConstruction->Construct(ConstrNum);
        int const nT = cFD.TotNodes + 1;
        if (tOut <= -900.0 || nT < 2) return false;
        std::vector<int> layerOf(nT + 1, con.TotLayers);
        int node = 0;
        for (int Layer = 1; Layer <= con.TotLayers; ++Layer) {
            for (int ln = 1; ln <= cFD.NodeNumPoint(Layer); ++ln) {
                ++node;
                if (node <= nT) layerOf[node] = Layer;
            }
        }
        prof.assign(nT, 0.0);
        for (int i = 0; i < nT; ++i) {
            prof[i] = tOut + (tIn - tOut) * Real64(i) / Real64(nT - 1);
        }
        std::vector<Real64> R(nT + 1, 0.0);
        for (int iter = 0; iter < 6; ++iter) {
            for (int i = 1; i < nT; ++i) { // segment between node i and i+1 lies in the layer of node i
                int const Layer = layerOf[i];
                auto const *mat = state.dataMaterial->materials(con.LayerPoint(Layer));
                auto const &matFD = s_hbfd->MaterialFD(con.LayerPoint(Layer));
                Real64 k = mat->Conductivity;
                auto const &tc = matFD.TempCond;
                if (!mat->ROnly && tc.size() >= 6) {
                    Real64 const l = tc.index(2, 1);
                    if (tc[l] + tc[l + 1] + tc[l + 2] >= 0.0) k = terpld(tc, 0.5 * (prof[i - 1] + prof[i]), 1, 2);
                }
                R[i + 1] = R[i] + cFD.DelX(Layer) / std::max(k, 1e-12);
            }
            Real64 const Rtot = std::max(R[nT], 1e-12);
            for (int i = 1; i <= nT; ++i) {
                prof[i - 1] = tOut + (tIn - tOut) * R[i] / Rtot;
            }
        }
        return true;
    }

'''
    s = s.replace(fn, helper + fn)
    if crlf:
        s = s.replace("\n", "\r\n")
    F.write_bytes(s.encode("utf-8"))
    print("patched HeatBalFiniteDiffManager.cc")

H = SRC / "PlanetaryBody.hh"
h = H.read_bytes().decode("utf-8")
if "condFDCorrected" not in h:
    h = h.replace("    bool outputsSetUp = false;\n", "    bool outputsSetUp = false;\n    bool condFDCorrected = false; // CondFD start-up profile corrected after warm-up\n")
    H.write_bytes(h.encode("utf-8"))
    print("patched PlanetaryBody.hh")
print("done")
