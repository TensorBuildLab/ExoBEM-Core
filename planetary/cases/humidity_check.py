"""Cabin humidity of the lunar habitat with ideal loads and a humidistat: relative humidity, dew point and the margin
between the coldest inside surface and the dew point, hourly over days 4-30. The same margin is also evaluated for a
cabin held at its 60 % humidity limit (what a condensing heat exchanger controlled to the limit would maintain), with
the engine's air and surface temperatures.

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
RH_LIMIT = 0.60


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
    Ts = np.array([series(db, "Surface Inside Face Temperature", k) for k in keys]).min(axis=0)[H0:H1]
    T = series(db, "Zone Mean Air Temperature")[H0:H1]
    rh = series(db, "Zone Air Relative Humidity")[H0:H1] / 100.0
    out = dict(engine=stats(T, rh, Ts), at_limit=stats(T, np.full_like(T, RH_LIMIT), Ts), rh_limit_pct=100 * RH_LIMIT)
    (HERE / "humidity_check.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
