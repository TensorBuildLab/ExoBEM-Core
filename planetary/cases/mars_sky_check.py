"""Martian sky long-wave of Thermonaut's environment generator against the observations it was calibrated to.

Targets:
  * clear-season (Ls 30-150) mean downwelling long-wave at Jezero, about 30 W/m2 (MEDA/TIRS, Martinez et al. 2023);
  * during the 2018 global dust storm the sol-mean near-surface air temperature fell by only about 4 K
    (Viudez-Moreiras et al. 2019; Guzewich et al. 2019).

Two runs of the Jezero regolith-module case over 2029-2030 (more than one Martian year), the nominal dust
climatology and the same with a global storm (optical depth 6 between Ls 190 and 270), compared over the ten sols
nearest Ls 230.

    python planetary/cases/mars_sky_check.py [energyplus.exe]   ->  planetary/cases/mars_sky_check.json
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import robustness as R

SOL = 88775.244147


def sol_means(db):
    T = R.series(db, "Site Outdoor Air Drybulb Temperature")
    L = R.series(db, "Site Planetary Downwelling Longwave Radiation")
    Ls = R.series(db, "Site Planetary Solar Longitude")
    t = 3600.0 * np.arange(1, len(T) + 1)
    i = np.floor((t - 1e-6) / SOL).astype(int)
    n = i.max()                                   # complete sols only
    cnt = np.bincount(i, None, n + 1)[:n]
    mean = lambda x: np.bincount(i, x, n + 1)[:n] / cnt
    return dict(T=mean(T), Ls=mean(Ls), L=L, Ls_h=Ls)


def main():
    base = R.set_pb((R.MARS / "mars_jezero.idf").read_text(), year=2029)
    base = R.set_runperiod(base, 1, 1, 2029, 12, 31, 2030)
    base = base.replace("Timestep,20;", "Timestep,6;")
    extra = "Output:Variable,*,Site Planetary Solar Longitude,Hourly;\n"
    jobs = {"nominal": base + extra,
            "storm": R.set_pb(base, storm_start=190, storm_end=270, storm_peak=6.0) + extra}

    def one(k):
        return k, sol_means(R.run(f"marssky_{k}", jobs[k], epw=R.MARS / "placeholder.epw"))

    with ThreadPoolExecutor(2) as ex:
        res = dict(ex.map(one, list(jobs)))
    nom, sto = res["nominal"], res["storm"]
    clear = (nom["Ls_h"] > 30) & (nom["Ls_h"] < 150)
    peak = np.argsort(np.abs(nom["Ls"] - 230.0))[:10]
    out = dict(
        L_clear_mean_W_m2=float(nom["L"][clear].mean()), L_annual_mean_W_m2=float(nom["L"].mean()),
        L_storm_max_W_m2=float(sto["L"].max()), dT_sol_mean_storm_K=float((sto["T"][peak] - nom["T"][peak]).mean()),
        peak_Ls_deg=[float(nom["Ls"][peak].min()), float(nom["Ls"][peak].max())],
        targets=dict(L_clear_mean_W_m2=30.0, dT_sol_mean_storm_K=-4.0))
    (R.HERE / "mars_sky_check.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        R.EXE = R.Path(sys.argv[1]).resolve()
    main()
