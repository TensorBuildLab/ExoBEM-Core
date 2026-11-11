"""Compare Thermonaut's solar altitude with an independent ephemeris, NASA JPL Horizons.

Horizons observer tables (Sun, quantity 4: apparent azimuth and elevation, airless, hourly at hh:30 UT) for the two
verification sites are stored in planetary/cases/horizons/.  They were fetched with the public Horizons API, e.g.

  https://ssd.jpl.nasa.gov/api/horizons.api?format=text&COMMAND='10'&CENTER='coord@301'&COORD_TYPE='GEODETIC'
      &SITE_COORD='23.473,0.674,0'&EPHEM_TYPE='OBSERVER'&START_TIME='2030-01-01 00:30'&STOP_TIME='2030-03-01 00:30'
      &STEP_SIZE='1 h'&QUANTITIES='4'&ANG_FORMAT='DEG'&CSV_FORMAT='YES'

(Mars: CENTER='coord@499', SITE_COORD='-77.45,18.44,0'; Horizons takes east longitude as negative for Mars.)

Thermonaut reports the hourly mean of its time-step solar altitude; the time steps are 3 min, so the hourly mean is
compared with Horizons at the middle of the hour.  Usage:

    python planetary/cases/compare_horizons.py <moon_run_dir> <mars_run_dir>   ->  planetary/cases/horizons/horizons_check.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent / "horizons"


def horizons(path):
    rows, on = [], False
    for line in path.read_text().splitlines():
        if line.startswith("$$SOE"):
            on = True
            continue
        if line.startswith("$$EOE"):
            break
        if on:
            f = [x.strip() for x in line.split(",")]
            rows.append((float(f[3]), float(f[4])))
    a = np.array(rows)
    return a[:, 0], a[:, 1]


def engine_altitude(run):
    db = sqlite3.connect(Path(run) / "eplusout.sql")
    q = ("SELECT rd.Value FROM ReportData rd JOIN ReportDataDictionary d ON rd.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex "
         "JOIN Time t ON rd.TimeIndex=t.TimeIndex WHERE d.Name='Site Solar Altitude Angle' AND (t.WarmupFlag=0 OR t.WarmupFlag IS NULL) "
         "AND t.EnvironmentPeriodIndex=(SELECT MAX(EnvironmentPeriodIndex) FROM Time) ORDER BY rd.TimeIndex")
    return np.array([r[0] for r in db.execute(q)])


def stats(eng, ref):
    n = min(len(eng), len(ref))
    e, r = eng[:n], ref[:n]
    up = r > 0.0
    d = e - r
    return dict(hours=int(n), rmse_all_deg=float(np.sqrt(np.mean(d ** 2))), max_abs_deg=float(np.max(np.abs(d))),
                rmse_sunlit_deg=float(np.sqrt(np.mean(d[up] ** 2))), bias_sunlit_deg=float(np.mean(d[up])),
                sunrise_hours_engine=int(np.sum(e > 0)), sunrise_hours_horizons=int(np.sum(up)))


def main():
    moon_run, mars_run = sys.argv[1], sys.argv[2]
    out = {}
    for key, run, f in (("moon_equator", moon_run, "moon_equator_horizons.txt"), ("mars_jezero", mars_run, "mars_jezero_horizons.txt")):
        _az, el = horizons(HERE / f)
        out[key] = stats(engine_altitude(run), el)
        print(key, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in out[key].items()})
    (HERE / "horizons_check.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
