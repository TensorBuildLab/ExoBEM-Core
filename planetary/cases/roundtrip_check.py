"""Round trip of the planetary weather-file path: each case is run with Thermonaut's own environment generator, the
generated environment is exported as a PWF file (planetary/tools/export_pwf.py), and the case is run again reading
that file. The two runs see the same environment, so their difference measures the reader (interpolation of the
records to the time step, mid-interval solar values) and nothing else.

    python planetary/cases/roundtrip_check.py [energyplus.exe]   ->  planetary/cases/round_trip.json

The exported files are the weather files of the cases (moon_equator.pwf, mars_jezero.pwf, lunar_habitat.pwf).
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "build" / "Products" / "energyplus.exe"
PY = sys.executable
RUNS = ROOT.parent / "exo-runs" / "roundtrip"

# case, generator input, PWF input, placeholder EPW (site and calendar), comparison window (first hour, hours), top surface
CASES = [
    ("moon_equator", HERE / "moon_equator" / "moon_equator.idf", HERE / "moon_equator" / "moon_equator_pwf.idf",
     HERE / "moon_equator" / "placeholder.epw", "SHELL_00"),
    ("mars_jezero", HERE / "mars_jezero" / "mars_jezero.idf", HERE / "mars_jezero" / "mars_jezero_pwf.idf",
     HERE / "mars_jezero" / "placeholder.epw", "SHELL_00"),
    ("lunar_habitat", HERE / "lunar_habitat" / "lunar_habitat.idf", HERE / "lunar_habitat" / "lunar_habitat.idf",
     HERE / "lunar_habitat" / "placeholder.epw", "ROOF"),
]


def series(db, name, key=None):
    q = ("SELECT rd.Value FROM ReportData rd JOIN ReportDataDictionary d ON rd.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex "
         "JOIN Time t ON rd.TimeIndex=t.TimeIndex WHERE d.Name=? AND d.ReportingFrequency='Hourly' "
         "AND (t.WarmupFlag=0 OR t.WarmupFlag IS NULL) AND t.EnvironmentPeriodIndex=(SELECT MAX(EnvironmentPeriodIndex) FROM Time)")
    a = [name]
    if key:
        q += " AND UPPER(d.KeyValue)=UPPER(?)"
        a.append(key)
    return np.array([r[0] for r in db.execute(q + " ORDER BY rd.TimeIndex", a)], float)


def generator_idf(text):
    m = re.search(r"^Site:PlanetaryBody,(.*);\s*$", text, re.M)
    f = m.group(1).split(",")
    if len(f) >= 24:
        f[23] = ""
    return text[:m.start()] + "Site:PlanetaryBody," + ",".join(f) + ";" + text[m.end():]


def run(name, idf_text, cwd_files, epw):
    d = RUNS / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    (d / "in.idf").write_text(idf_text)
    for f in cwd_files:
        shutil.copy(f, d / f.name)
    cmd = [str(EXE), "-d", str(d / "out")] + (["-w", str(epw)] if epw else []) + [str(d / "in.idf")]
    subprocess.run(cmd, cwd=d, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    err = (d / "out" / "eplusout.err").read_text(errors="replace")
    if "Completed Successfully" not in err:
        raise RuntimeError(name + " failed:\n" + "\n".join(l for l in err.splitlines() if "Fatal" in l or "Severe" in l))
    return sqlite3.connect(d / "out" / "eplusout.sql")


def window(case, n):
    if case == "lunar_habitat":
        return 72, n                     # days 4-30
    skip = (n // 48) * 24                # Moon: second lunation; Mars: days 16-31
    return skip, n


def rmse(a, b):
    return float(np.sqrt(np.mean((a - b) ** 2)))


def main():
    out = {}
    for case, idf_gen, idf_pwf, epw, top in CASES:
        pwf = idf_gen.parent / f"{case}.pwf"
        subprocess.run([PY, str(ROOT / "planetary" / "tools" / "export_pwf.py"), str(idf_gen), str(epw), str(pwf), str(EXE)], check=True)
        g = run(f"{case}_gen", generator_idf(idf_gen.read_text()), [], epw)
        p = run(f"{case}_pwf", idf_pwf.read_text(), [pwf], None)
        qg, qp = series(g, "Zone Ideal Loads Zone Sensible Cooling Rate"), series(p, "Zone Ideal Loads Zone Sensible Cooling Rate")
        a, b = window(case, len(qg))
        r = dict(hours=b - a, first_hour=a,
                 cooling_gen_kWh=float(qg[a:b].sum() / 1000), cooling_pwf_kWh=float(qp[a:b].sum() / 1000),
                 cooling_rmse_W=rmse(qg[a:b], qp[a:b]))
        r["cooling_diff_pct"] = 100 * (r["cooling_pwf_kWh"] / r["cooling_gen_kWh"] - 1)
        lg, lp = series(g, "Zone Ideal Loads Zone Latent Cooling Rate"), series(p, "Zone Ideal Loads Zone Latent Cooling Rate")
        if len(lg):
            r.update(latent_gen_kWh=float(lg[a:b].sum() / 1000), latent_pwf_kWh=float(lp[a:b].sum() / 1000))
            r["latent_diff_pct"] = 100 * (r["latent_pwf_kWh"] / r["latent_gen_kWh"] - 1)
        tg, tp = series(g, "Site Planetary Ground Surface Temperature"), series(p, "Site Planetary Ground Surface Temperature")
        r["ground_rmse_K"] = rmse(tg[a:b], tp[a:b])
        og, op = series(g, "Surface Outside Face Temperature", top), series(p, "Surface Outside Face Temperature", top)
        ig, ip = series(g, "Surface Inside Face Temperature", top), series(p, "Surface Inside Face Temperature", top)
        r.update(top_surface=top, top_outside_rmse_K=rmse(og[a:b], op[a:b]), top_inside_rmse_K=rmse(ig[a:b], ip[a:b]))
        out[case] = r
        print(case, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    (HERE / "round_trip.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
