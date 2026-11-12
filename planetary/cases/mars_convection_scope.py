"""Applicability of the Mars exterior-convection correlations: dimensionless numbers over the verification run,
continuum check (Knudsen number) and sensitivity of h to pressure, wind, temperature difference and length scale.

Uses the 3-minute Mars run written by check_boundary.py (../exo-runs/boundary/mars_boundary) and CO2 properties from
the NIST Chemistry WebBook at 700 Pa (horizons/nist_co2_700Pa.tsv).

    python planetary/cases/mars_convection_scope.py   ->  planetary/cases/mars_convection_scope.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from check_boundary import h_mars_hand, nist_props, series  # noqa: E402

KB, D_CO2 = 1.380649e-23, 3.3e-10  # Boltzmann constant; CO2 kinetic diameter (m)


def props(Tf, P):
    Tn, cpn, mun, kn = nist_props()
    cp, mu, k = np.interp(Tf, Tn, cpn), np.interp(Tf, Tn, mun), np.interp(Tf, Tn, kn)
    rho = P / (8.314462618 / 0.0440095 * Tf)
    return cp, mu, k, rho


def main():
    db = sqlite3.connect(HERE.parents[1].parent / "exo-runs" / "boundary" / "mars_boundary" / "out" / "eplusout.sql")
    Ts = series(db, "Surface Outside Face Temperature", "SHELL_00") + 273.15
    Ta = series(db, "Site Outdoor Air Drybulb Temperature") + 273.15
    V = series(db, "Site Wind Speed")
    P = series(db, "Site Planetary Ambient Pressure")
    A = db.execute("SELECT Area FROM Surfaces WHERE UPPER(SurfaceName)='SHELL_00'").fetchone()[0]
    per = 2 * (10.0 + 1.1705)  # 10 m x 1.17 m facet
    Lh, Lf = A / per, np.sqrt(A)
    Tf = 0.5 * (Ts + Ta)
    ok = Tf >= 216.6
    cp, mu, k, rho = props(Tf[ok], P[ok])
    nu, alpha = mu / rho, k / (rho * cp)
    Ra = 3.721 / Tf[ok] * np.abs(Ts[ok] - Ta[ok]) * Lh ** 3 / (nu * alpha)
    Re = np.maximum(V[ok], 1e-6) * Lf / nu
    Pr = nu / alpha
    mfp = KB * Tf / (np.sqrt(2) * np.pi * D_CO2 ** 2 * P)
    out = dict(
        steps=int(ok.sum()), L_horizontal_m=float(Lh), L_forced_m=float(Lf),
        Ra_range=[float(np.percentile(Ra, 1)), float(np.percentile(Ra, 99))],
        Re_range=[float(np.percentile(Re, 1)), float(np.percentile(Re, 99))],
        Pr_range=[float(Pr.min()), float(Pr.max())],
        mean_free_path_um=[float(1e6 * mfp.min()), float(1e6 * mfp.max())],
        Knudsen_max=float(mfp.max() / min(Lh, Lf)),
        note="Churchill-Chu vertical (all Ra), McAdams/Lloyd-Moran horizontal (laminar range 1e4-1e7, turbulent 1e7-1e11), "
             "laminar flat plate Re < 5e5; Kn < 1e-3 means continuum, no slip correction",
    )
    # sensitivity of h (horizontal facet, hot surface facing up) to one factor at a time around a reference point
    ref = dict(P=700.0, V=3.2, dT=20.0, L=Lh, Tair=220.0)

    def h_at(P=ref["P"], V=ref["V"], dT=ref["dT"], L=ref["L"]):
        Ts_, Ta_ = np.array([ref["Tair"] + dT]), np.array([ref["Tair"]])
        h, _ = h_mars_hand(Ts_, Ta_, np.array([P]), np.array([V]), 3.721, 1.0, L, np.sqrt(A))
        return float(h[0])

    h0 = h_at()
    sens = dict(reference_W_m2K=h0,
                pressure=[[p, h_at(P=p)] for p in (600, 700, 800)],
                wind=[[v, h_at(V=v)] for v in (0.0, 1.0, 3.2, 6.0, 10.0)],
                dT=[[d, h_at(dT=d)] for d in (5, 20, 40, 60)],
                L_horizontal=[[l, h_at(L=l)] for l in (0.25, Lh, 1.0, 2.0)])
    out["sensitivity"] = sens
    (HERE / "mars_convection_scope.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
