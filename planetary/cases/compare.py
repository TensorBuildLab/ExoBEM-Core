"""Compare an ExoBEM-Core run (eplusout.sql) with the Python ExoBEM reference (python_ref.npz).

Usage: python planetary/cases/compare.py <case> <run_dir> [--skip-days N]
Writes <run_dir>/comparison.json and comparison.png.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def sql_series(db, name, key=None):
    q = ("SELECT rd.Value FROM ReportData rd JOIN ReportDataDictionary d ON rd.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex "
         "JOIN Time t ON rd.TimeIndex=t.TimeIndex WHERE d.Name=? AND (t.WarmupFlag=0 OR t.WarmupFlag IS NULL) AND t.EnvironmentPeriodIndex=(SELECT MAX(EnvironmentPeriodIndex) FROM Time)")
    args = [name]
    if key is not None:
        q += " AND UPPER(d.KeyValue)=UPPER(?)"
        args.append(key)
    q += " ORDER BY rd.TimeIndex"
    return np.array([r[0] for r in db.execute(q, args)], float)


def hourly(x, steps_per_hour):
    n = len(x) // steps_per_hour
    return x[: n * steps_per_hour].reshape(n, steps_per_hour).mean(axis=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("run_dir")
    ap.add_argument("--skip-days", type=int, default=None)
    a = ap.parse_args()
    run = Path(a.run_dir)
    ref = np.load(HERE / a.case / "python_ref.npz")
    dt = ref["time_s"][1] - ref["time_s"][0]
    sph = int(round(3600.0 / dt))
    db = sqlite3.connect(run / "eplusout.sql")
    zone = db.execute("SELECT ZoneName FROM Zones").fetchone()[0]
    ep = dict(
        Qc=sql_series(db, "Zone Ideal Loads Zone Sensible Cooling Rate"),
        Qh=sql_series(db, "Zone Ideal Loads Zone Sensible Heating Rate"),
        Tz=sql_series(db, "Zone Mean Air Temperature", zone),
        Tg=sql_series(db, "Site Planetary Ground Surface Temperature"),
        Tdeep=sql_series(db, "Site Planetary Deep Ground Temperature"),
        Tsky=sql_series(db, "Site Sky Temperature"),
        beam=sql_series(db, "Site Direct Solar Radiation Rate per Area"),
        dif=sql_series(db, "Site Diffuse Solar Radiation Rate per Area"),
        Tair=sql_series(db, "Site Outdoor Air Drybulb Temperature"),
        top=sql_series(db, "Surface Outside Face Temperature", "SHELL_00"),
        tin_top=sql_series(db, "Surface Inside Face Temperature", "SHELL_00"),
        hin_top=sql_series(db, "Surface Inside Face Convection Heat Transfer Coefficient", "SHELL_00"),
        hout_top=sql_series(db, "Surface Outside Face Convection Heat Transfer Coefficient", "SHELL_00"),
    )
    names = [str(n) for n in ref["names"]]
    i_top = names.index("shell_00")
    py = dict(
        Qc=hourly(ref["Q_cooling_W"], sph), Qh=hourly(ref["Q_heating_W"], sph), Tz=hourly(ref["T_zone_C"], sph),
        Tg=hourly(ref["T_ground"] - 273.15, sph), Tdeep=hourly(ref["T_deep"] - 273.15, sph), Tsky=hourly(ref["T_sky"] - 273.15, sph),
        beam=hourly(ref["dni"], sph), dif=hourly(ref["dhi"], sph),
        top=hourly(ref["T_outside_C"][:, i_top], sph), tin_top=hourly(ref["T_inside_C"][:, i_top], sph),
        hin_top=hourly(ref["h_conv_in"][:, i_top], sph), hout_top=hourly(ref["h_conv_out"][:, i_top], sph),
    )
    n = min(len(ep["Qc"]), len(py["Qc"]))
    skip = (a.skip_days if a.skip_days is not None else n // 48) * 24  # default: compare the second half
    out = {}
    for k in py:
        if k not in ep or len(ep[k]) < n:
            continue
        e, p = ep[k][skip:n], py[k][skip:n]
        out[k] = dict(ep_mean=float(np.mean(e)), py_mean=float(np.mean(p)), ep_min=float(e.min()), ep_max=float(e.max()),
                      py_min=float(p.min()), py_max=float(p.max()), rmse=float(np.sqrt(np.mean((e - p) ** 2))),
                      r2=float(np.corrcoef(e, p)[0, 1] ** 2) if np.std(e) > 0 and np.std(p) > 0 else None)
    hours = n - skip
    out["energy"] = dict(hours=hours, ep_cooling_kWh=float(np.sum(ep["Qc"][skip:n]) / 1000), py_cooling_kWh=float(np.sum(py["Qc"][skip:n]) / 1000),
                         ep_heating_kWh=float(np.sum(ep["Qh"][skip:n]) / 1000), py_heating_kWh=float(np.sum(py["Qh"][skip:n]) / 1000))
    (run / "comparison.json").write_text(json.dumps(out, indent=1))
    for k, v in out.items():
        if k == "energy":
            print(k, {kk: round(vv, 1) for kk, vv in v.items()})
        else:
            print(f"{k:9s} EP mean {v['ep_mean']:9.2f} [{v['ep_min']:8.2f},{v['ep_max']:8.2f}]  PY mean {v['py_mean']:9.2f} "
                  f"[{v['py_min']:8.2f},{v['py_max']:8.2f}]  RMSE {v['rmse']:8.3f}  R2 {v['r2'] if v['r2'] is None else round(v['r2'], 4)}")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        t = np.arange(n) / 24.0
        fig, ax = plt.subplots(4, 1, figsize=(9, 9), sharex=True)
        for axi, k, lab in [(ax[0], "Qc", "Sensible cooling [W]"), (ax[1], "Tg", "Regolith surface [C]"),
                            (ax[2], "top", "Top facet outside face [C]"), (ax[3], "tin_top", "Top facet inside face [C]")]:
            axi.plot(t, py[k][:n], color="#2a6fbb", lw=1.4, label="ExoBEM (Python)")
            axi.plot(t, ep[k][:n], color="#d9822b", lw=1.0, ls="--", label="ExoBEM-Core (C++)")
            axi.set_ylabel(lab)
            axi.grid(alpha=0.3)
        ax[0].legend(frameon=True)
        ax[-1].set_xlabel("Day")
        fig.tight_layout()
        fig.savefig(run / "comparison.png", dpi=130)
    except Exception as exc:  # pragma: no cover
        print("plot skipped:", exc)


if __name__ == "__main__":
    main()
