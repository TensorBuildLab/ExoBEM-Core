"""Analytical checks of Thermonaut's exterior boundary.

1. Moon (vacuum), NASA-informed lunar habitat on legs, every outer face, every 3-minute step:
   * the convective heat gain must be exactly zero;
   * the net long-wave gain reported by the engine must equal eps*sigma*[F_sky (T_sky^4 - T^4) + F_g (T_g^4 - T^4)],
     with F_sky = (1 + cos tilt)/2, F_g = (1 - cos tilt)/2 (no sky view to air off-Earth), the sky at the reported
     sky temperature (2.725 K) and the ground at the reported regolith surface temperature;
   * the outer-face balance (solar + long-wave + convection - conduction into the wall) must close.
2. Mars (Jezero, regolith-shielded module, PWF mode), top facet: the engine's exterior convection coefficient is
   recomputed by hand from textbook correlations (horizontal plate: McAdams/Lloyd-Moran; laminar flat plate; cubic
   blending) with CO2 properties from the NIST Chemistry WebBook at 700 Pa (planetary/cases/horizons/
   nist_co2_700Pa.tsv), not from the engine's property fits.  Only steps with a film temperature inside the NIST
   table (>= 216.6 K, the CO2 triple point) are used.

    python planetary/cases/check_boundary.py <energyplus.exe> <work_dir>   ->  planetary/cases/boundary_check.json
"""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SIGMA = 5.670374419e-8
TS_VARS = ["Surface Outside Face Temperature", "Surface Outside Face Net Thermal Radiation Heat Gain Rate per Area",
           "Surface Outside Face Convection Heat Gain Rate per Area", "Surface Outside Face Solar Radiation Heat Gain Rate per Area",
           "Surface Outside Face Conduction Heat Transfer Rate per Area", "Surface Outside Face Convection Heat Transfer Coefficient",
           "Site Sky Temperature", "Site Planetary Ground Surface Temperature", "Site Outdoor Air Drybulb Temperature",
           "Site Wind Speed", "Site Planetary Ambient Pressure"]


def make_run(exe, src_idf, extra_files, work):
    work.mkdir(parents=True, exist_ok=True)
    s = src_idf.read_text()
    s = re.sub(r"Output:Variable,[^;]*;\s*", "", s)
    s += "\n" + "\n".join(f"Output:Variable,*,{v},Timestep;" for v in TS_VARS) + "\n"
    (work / src_idf.name).write_text(s)
    for f in extra_files:
        (work / f.name).write_bytes(f.read_bytes())
    subprocess.run([str(exe), "-d", str(work / "out"), str(work / src_idf.name)], cwd=work, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return sqlite3.connect(work / "out" / "eplusout.sql")


def series(db, name, key=None):
    q = ("SELECT rd.Value FROM ReportData rd JOIN ReportDataDictionary d ON rd.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex "
         "JOIN Time t ON rd.TimeIndex=t.TimeIndex WHERE d.Name=? AND (t.WarmupFlag=0 OR t.WarmupFlag IS NULL) "
         "AND t.EnvironmentPeriodIndex=(SELECT MAX(EnvironmentPeriodIndex) FROM Time)")
    a = [name]
    if key:
        q += " AND UPPER(d.KeyValue)=UPPER(?)"
        a.append(key)
    return np.array([r[0] for r in db.execute(q + " ORDER BY rd.TimeIndex", a)], float)


def moon_check(db):
    surf = db.execute("SELECT SurfaceName, Tilt, ExtBoundCond FROM Surfaces WHERE ClassName NOT LIKE 'Internal%'").fetchall()
    eps = 0.90  # beta-cloth outer layer (thermal absorptance in the input)
    Tsky = series(db, "Site Sky Temperature") + 273.15
    Tg = series(db, "Site Planetary Ground Surface Temperature") + 273.15
    res_lw, res_bal, conv, scale = [], [], [], []
    for name, tilt, ebc in surf:
        if ebc != 0:  # outdoor surfaces only
            continue
        T = series(db, "Surface Outside Face Temperature", name) + 273.15
        lw = series(db, "Surface Outside Face Net Thermal Radiation Heat Gain Rate per Area", name)
        cv = series(db, "Surface Outside Face Convection Heat Gain Rate per Area", name)
        so = series(db, "Surface Outside Face Solar Radiation Heat Gain Rate per Area", name)
        cd = series(db, "Surface Outside Face Conduction Heat Transfer Rate per Area", name)
        ct = np.cos(np.radians(tilt))
        lw_hand = eps * SIGMA * (0.5 * (1 + ct) * (Tsky ** 4 - T ** 4) + 0.5 * (1 - ct) * (Tg ** 4 - T ** 4))
        res_lw.append(lw - lw_hand)
        res_bal.append(so + lw + cv + cd)  # conduction is reported positive out of the wall at the outer face
        conv.append(np.abs(cv))
        scale.append(np.abs(lw_hand))
    r = np.concatenate(res_lw)
    b = np.concatenate(res_bal)
    return dict(steps=int(r.size), lw_residual_rmse_W_m2=float(np.sqrt(np.mean(r ** 2))),
                lw_residual_p99_W_m2=float(np.percentile(np.abs(r), 99)), lw_mean_abs_W_m2=float(np.mean(np.concatenate(scale))),
                balance_residual_rmse_W_m2=float(np.sqrt(np.mean(b ** 2))), max_abs_convection_W_m2=float(np.max(np.concatenate(conv))))


def nist_props():
    rows = [l.split("\t") for l in (HERE / "horizons" / "nist_co2_700Pa.tsv").read_text().splitlines()[1:] if l.strip()]
    T = np.array([float(r[0]) for r in rows])
    return T, np.array([float(r[8]) for r in rows]) * 1000.0, np.array([float(r[11]) for r in rows]), np.array([float(r[12]) for r in rows])


def h_mars_hand(Ts, Ta, P, V, g, cos_up, Lh, Lf):
    Tn, cpn, mun, kn = nist_props()
    Tf = 0.5 * (Ts + Ta)
    cp, mu, k = np.interp(Tf, Tn, cpn), np.interp(Tf, Tn, mun), np.interp(Tf, Tn, kn)
    rho = P / (8.314462618 / 0.0440095 * Tf)
    nu, alpha = mu / rho, k / (rho * cp)
    Pr = nu / alpha
    dT = Ts - Ta
    Ra = g / Tf * np.abs(dT) * Lh ** 3 / (nu * alpha)
    hot_up = ((dT > 0) & (cos_up > 0)) | ((dT < 0) & (cos_up < 0))
    Nu_h = np.where(hot_up, np.where(Ra < 1e7, 0.54 * Ra ** 0.25, 0.15 * Ra ** (1 / 3)), 0.27 * Ra ** 0.25)
    Nu_h = np.maximum(Nu_h, 1.0)
    hn = Nu_h * k / Lh
    Re = np.maximum(V, 1e-6) * Lf / nu
    hf = 0.664 * np.sqrt(Re) * Pr ** (1 / 3) * k / Lf
    return np.cbrt(hn ** 3 + hf ** 3), Tf


def mars_check(db, idf_text):
    Ts = series(db, "Surface Outside Face Temperature", "SHELL_00") + 273.15
    h = series(db, "Surface Outside Face Convection Heat Transfer Coefficient", "SHELL_00")
    Ta = series(db, "Site Outdoor Air Drybulb Temperature") + 273.15
    V = series(db, "Site Wind Speed")
    P = series(db, "Site Planetary Ambient Pressure")
    tilt = db.execute("SELECT Tilt, Area FROM Surfaces WHERE UPPER(SurfaceName)='SHELL_00'").fetchone()
    # facet geometry from the input vertices (rectangle): perimeter for the horizontal length scale A/P
    m = re.search(r"BuildingSurface:Detailed,\s*shell_00,.*?;", idf_text, re.S | re.I)
    nums = [float(x) for x in re.findall(r"-?\d+\.\d+", m.group(0).split("!- Number of Vertices")[-1])] if m else []
    pts = np.array(nums).reshape(-1, 3) if nums else None
    per = float(np.sum(np.linalg.norm(np.roll(pts, -1, 0) - pts, axis=1))) if pts is not None else 4 * np.sqrt(tilt[1])
    A = tilt[1]
    hh, Tf = h_mars_hand(Ts, Ta, P, V, 3.721, np.cos(np.radians(tilt[0])), A / per, np.sqrt(A))
    ok = Tf >= 216.6
    d = (h - hh)[ok] / hh[ok]
    return dict(steps_used=int(ok.sum()), steps_total=int(ok.size), h_engine_mean=float(h[ok].mean()), h_hand_mean=float(hh[ok].mean()),
                rel_diff_mean_pct=float(100 * d.mean()), rel_diff_rmse_pct=float(100 * np.sqrt(np.mean(d ** 2))))


def main():
    exe, work = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    hab = HERE / "lunar_habitat"
    dbm = make_run(exe, hab / "lunar_habitat.idf", [hab / "lunar_habitat.pwf"], work / "moon_boundary")
    out = dict(moon_vacuum=moon_check(dbm))
    mj = HERE / "mars_jezero"
    dbs = make_run(exe, mj / "mars_jezero_pwf.idf", [mj / "mars_jezero.pwf"], work / "mars_boundary")
    out["mars_convection"] = mars_check(dbs, (mj / "mars_jezero_pwf.idf").read_text())
    for k, v in out.items():
        print(k, {a: (round(b, 4) if isinstance(b, float) else b) for a, b in v.items()})
    (HERE / "boundary_check.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
