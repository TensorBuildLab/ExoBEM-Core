"""Thermonaut M2d patch set: post-warm-up correction of CondFD start-up profiles applied only where warm-up could not
reach.

Run from the repository root:  python planetary/tools/apply_hooks_m2d.py   (idempotent)

CondFD walls start from the steady conduction profile between the period-mean outer-face temperature and the initial
zone temperature (M1).  After warm-up the profile is corrected for the real inside-face temperature.  Until M2c the
full correction pNew - pOld was added to every node; but the nodes near the inside face had already relaxed to the
real inside temperature during warm-up, so they were pushed past it by the same amount (the 2-7 K warm inner face and
the 0.4-2.4 kW cooling transient after warm-up).

The correction is now weighted by the part that warm-up could not deliver.  The construction's own node network
(conductance k/dx between nodes, capacity rho*c*dx shared by adjacent nodes, exactly as CondFD discretizes it,
including the near-zero capacity CondFD gives no-mass layers) is integrated implicitly over the warm-up duration for a
unit step of the inside-face temperature, with the outer node held fixed.  The resulting response g(i) is the fraction
of the inside change already present at node i, and node i receives (1 - g(i)) of the correction.  A diffusion-depth
(erf) weighting was tried first and rejected: it treats high-resistance, no-mass MLI as transparent and so
under-corrected the regolith behind it.  Earth runs are unaffected (planetary-only code path).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
F = ROOT / "src" / "EnergyPlus" / "HeatBalFiniteDiffManager.cc"


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


OLD = """                std::vector<Real64> pOld, pNew;
                if (!planetarySteadyProfile(state, SurfNum, TempInitValue, pOld)) continue;
                if (!planetarySteadyProfile(state, SurfNum, sfd.TDT(nT), pNew)) continue;
                for (int i = 1; i <= nT; ++i) {
                    Real64 const d = pNew[i - 1] - pOld[i - 1];
"""
NEW = """                std::vector<Real64> pOld, pNew;
                if (!planetarySteadyProfile(state, SurfNum, TempInitValue, pOld)) continue;
                if (!planetarySteadyProfile(state, SurfNum, sfd.TDT(nT), pNew)) continue;
                // Thermonaut M2d: warm-up has already carried part of the inside-temperature change into the wall. Integrate
                // the construction's node network (CondFD conductances and capacities) for a unit step at the inside face
                // over the warm-up period; g(i) is the fraction already present at node i, which receives (1 - g(i)).
                auto const &conW = state.dataConstruction->Construct(surf.Construction);
                auto const &cFDW = s_hbfd->ConstructFD(surf.Construction);
                std::vector<int> layerOfW(nT + 1, conW.TotLayers);
                {
                    int nodeW = 0;
                    for (int Layer = 1; Layer <= conW.TotLayers; ++Layer) {
                        for (int ln = 1; ln <= cFDW.NodeNumPoint(Layer); ++ln) {
                            ++nodeW;
                            if (nodeW <= nT) layerOfW[nodeW] = Layer;
                        }
                    }
                }
                std::vector<Real64> gW(nT + 1, 0.0), capW(nT + 1, 0.0), condW(nT + 1, 0.0);
                for (int j = 1; j < nT; ++j) { // segment j joins nodes j and j+1 and lies in the layer of node j
                    int const Layer = layerOfW[j];
                    auto const *mat = state.dataMaterial->materials(conW.LayerPoint(Layer));
                    Real64 const dx = std::max(cFDW.DelX(Layer), 1e-9);
                    condW[j] = mat->Conductivity / dx;
                    Real64 const c = std::max(mat->Density * mat->SpecHeat * dx, 0.0);
                    capW[j] += 0.5 * c;
                    capW[j + 1] += 0.5 * c;
                }
                gW[nT] = 1.0; // inside face stepped to the real inside temperature; outside node held fixed
                if (nT >= 3) {
                    Real64 const tWarm = std::max(1, state.dataReportFlag->NumOfWarmupDays) * Constant::rSecsInDay;
                    int const nStepW = std::max(1, int(tWarm / 3600.0));
                    Real64 const dtW = tWarm / nStepW;
                    std::vector<Real64> cpW(nT + 1, 0.0), dpW(nT + 1, 0.0);
                    for (int s = 0; s < nStepW; ++s) { // implicit Euler, Thomas algorithm on interior nodes 2..nT-1
                        for (int i = 2; i <= nT - 1; ++i) {
                            Real64 const lo = -condW[i - 1], up = -condW[i];
                            Real64 const di = capW[i] / dtW + condW[i - 1] + condW[i];
                            Real64 rhs = capW[i] / dtW * gW[i];
                            if (i == nT - 1) rhs += condW[i] * gW[nT];
                            if (i == 2) rhs += condW[1] * gW[1];
                            Real64 const lw = (i == 2) ? 0.0 : lo;
                            Real64 const den = di - lw * ((i == 2) ? 0.0 : cpW[i - 1]);
                            cpW[i] = (i == nT - 1) ? 0.0 : up / den;
                            dpW[i] = (rhs - lw * ((i == 2) ? 0.0 : dpW[i - 1])) / den;
                        }
                        for (int i = nT - 1; i >= 2; --i) {
                            gW[i] = dpW[i] - ((i == nT - 1) ? 0.0 : cpW[i] * gW[i + 1]);
                        }
                    }
                }
                for (int i = 1; i <= nT; ++i) {
                    Real64 const d = (pNew[i - 1] - pOld[i - 1]) * (1.0 - std::clamp(gW[i], 0.0, 1.0));
"""
edit(F, "#include <EnergyPlus/PlanetaryBody.hh>\n",
     "#include <EnergyPlus/PlanetaryBody.hh>\n#include <EnergyPlus/DataReportingFlags.hh>\n",
     "#include <EnergyPlus/DataReportingFlags.hh>")
edit(F, OLD, NEW, "Thermonaut M2d")
print("M2d applied")
