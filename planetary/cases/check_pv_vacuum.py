"""Numerical closure of the PV cell-temperature balance in vacuum (lunar regolith module with two one-diode modules).

At every time step the engine's cell temperature T must satisfy the steady two-face balance
    (tau_alpha - eta) G = eps sigma (T^4 - Tf^4) + eps sigma (T^4 - Tb^4)          (Moon: no convection)
with Tf^4, Tb^4 the view-weighted fourth powers of sky and regolith seen by the front (sky view (1 + cos b)/2) and the
back (sky view (1 - cos b)/2).

    python planetary/cases/check_pv_vacuum.py [energyplus.exe]  ->  planetary/cases/pv_vacuum/pv_vacuum_check.json
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "build" / "Products" / "energyplus.exe"
CASE = HERE / "pv_vacuum"
SIGMA, EPS, TAU_ALPHA = 5.670374419e-8, 0.85, 0.9
TILT = {"PV_H": 0.0, "PV_E": 90.0}
SURF = {"PV_H": "PV_HORIZONTAL", "PV_E": "PV_EAST"}


def series(db, name, key=None):
    q = ("SELECT d.Value FROM ReportData d JOIN ReportDataDictionary k ON d.ReportDataDictionaryIndex = k.ReportDataDictionaryIndex "
         "JOIN Time t ON d.TimeIndex = t.TimeIndex WHERE k.Name = ? AND k.ReportingFrequency = 'Zone Timestep' AND t.WarmupFlag = 0")
    args = [name]
    if key:
        q += " AND UPPER(k.KeyValue) = ?"
        args.append(key.upper())
    return np.array([r[0] for r in db.execute(q + " ORDER BY t.TimeIndex", args)])


def main():
    out = CASE / "out"
    if out.exists():
        shutil.rmtree(out)
    subprocess.run([str(EXE), "-d", str(out), str(CASE / "pv_vacuum.idf")], cwd=CASE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    db = sqlite3.connect(out / "eplusout.sql")
    Tsky = series(db, "Site Sky Temperature") + 273.15
    Tg = series(db, "Site Planetary Ground Surface Temperature") + 273.15
    res = {}
    for pv, b in TILT.items():
        T = series(db, "Generator PV Cell Temperature", pv) + 273.15
        eta = series(db, "Generator PV Array Efficiency", pv)
        G = series(db, "Surface Outside Face Incident Solar Radiation Rate per Area", SURF[pv])
        fs = 0.5 * (1 + np.cos(np.radians(b)))
        Tf4 = fs * Tsky ** 4 + (1 - fs) * Tg ** 4
        Tb4 = (1 - fs) * Tsky ** 4 + fs * Tg ** 4
        r = (TAU_ALPHA - eta) * G - EPS * SIGMA * (2 * T ** 4 - Tf4 - Tb4)
        big = np.abs(r) > 1.0
        sun = G > 30.0
        res[pv] = dict(steps=int(len(T)), residual_p99_W_m2=float(np.percentile(np.abs(r), 99)), steps_over_1W=int(big.sum()),
                       of_which_below_30W=int((big & ~sun).sum()), Tcell_sunlit_max_K=float(T[sun].max()),
                       Tcell_min_K=float(T.min()), eta_sunlit_mean=float(eta[sun].mean()))
    (CASE / "pv_vacuum_check.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
