"""Cabin humidity of the lunar habitat in Thermonaut (ideal loads with a humidistat) and ExoBEM (condensing heat
exchanger): relative humidity, dew point and the margin between the coldest inside surface and the dew point,
hourly over days 4-30.

    python planetary/cases/humidity_check.py   ->  planetary/cases/humidity_check.json
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CASE = HERE / "lunar_habitat"
H0, H1 = 72, 720          # days 4-30, hourly


def dew_point(T, rh):
    """Magnus formula over water (T in C, rh 0-1)."""
    a, b = 17.62, 243.12
    g = np.log(np.clip(rh, 1e-6, 1)) + a * T / (b + T)
    return b * g / (a - g)


def series(db, name, key=None):
    q = ("SELECT d.Value FROM ReportData d JOIN ReportDataDictionary k ON d.ReportDataDictionaryIndex = k.ReportDataDictionaryIndex "
         "JOIN Time t ON d.TimeIndex = t.TimeIndex WHERE k.Name = ? AND k.ReportingFrequency = 'Hourly' AND (t.WarmupFlag = 0 OR t.WarmupFlag IS NULL)")
    args = [name]
    if key:
        q += " AND UPPER(k.KeyValue) = ?"
        args.append(key.upper())
    return np.array([r[0] for r in db.execute(q + " ORDER BY t.TimeIndex", args)])


def stats(T, rh, Tsurf_min):
    dp = dew_point(T, rh)
    m = Tsurf_min - dp
    return dict(rh_min=float(100 * rh.min()), rh_max=float(100 * rh.max()), rh_mean=float(100 * rh.mean()),
                dew_min=float(dp.min()), dew_max=float(dp.max()), margin_min_K=float(m.min()), margin_mean_K=float(m.mean()))


def main():
    db = sqlite3.connect(CASE / "out" / "eplusout.sql")
    keys = [r[0] for r in db.execute("SELECT DISTINCT KeyValue FROM ReportDataDictionary WHERE Name = 'Surface Inside Face Temperature'")]
    Ts = np.array([series(db, "Surface Inside Face Temperature", k) for k in keys])
    T = series(db, "Zone Mean Air Temperature")
    rh = series(db, "Zone Air Relative Humidity") / 100.0
    engine = stats(T[H0:H1], rh[H0:H1], Ts.min(axis=0)[H0:H1])
    ref = np.load(CASE / "python_ref.npz")
    n = len(ref["time_s"]) // H1                                 # steps per hour
    hourly = lambda x: x[: n * H1].reshape(H1, n, *x.shape[1:]).mean(axis=1)
    Tp, rhp, Tsp = hourly(ref["T_zone_C"]), hourly(ref["rh"]), hourly(ref["T_inside_C"]).min(axis=1)
    exobem = stats(Tp[H0:H1], rhp[H0:H1], Tsp[H0:H1])
    out = dict(engine=engine, exobem=exobem)
    (HERE / "humidity_check.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
