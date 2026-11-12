"""Collect the Thermonaut verification results used by the manuscript and its supplement.

    python planetary/cases/roundtrip_check.py         (generator and weather-file runs -> ../exo-runs/roundtrip)
    python planetary/paper/extract_thermonaut_data.py

Writes planetary/paper/data/core_<case>_hourly.csv (hourly series of the generator run and of the run reading the
exported weather file, with the JPL Horizons solar altitude where available) and planetary/paper/data/core_summary.json.
The paper is then built from these files only.  THERMONAUT_RUNS overrides the run folder (default ../exo-runs).
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CORE = HERE.parents[1]                                   # Thermonaut repository root
RUNS = Path(os.environ.get("THERMONAUT_RUNS", CORE.parent / "exo-runs"))
CASES_DIR = CORE / "planetary" / "cases"
OUT = HERE / "data"
sys.path.insert(0, str(CASES_DIR))
from compare_horizons import horizons  # noqa: E402


def sql_series(db, name, key=None):
    q = ("SELECT rd.Value FROM ReportData rd JOIN ReportDataDictionary d ON rd.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex "
         "JOIN Time t ON rd.TimeIndex=t.TimeIndex WHERE d.Name=? AND d.ReportingFrequency='Hourly' "
         "AND (t.WarmupFlag=0 OR t.WarmupFlag IS NULL) AND t.EnvironmentPeriodIndex=(SELECT MAX(EnvironmentPeriodIndex) FROM Time)")
    args = [name]
    if key is not None:
        q += " AND UPPER(d.KeyValue)=UPPER(?)"
        args.append(key)
    return np.array([r[0] for r in db.execute(q + " ORDER BY rd.TimeIndex", args)], float)


def write_csv(path, cols):
    n = min(len(v) for v in cols.values())
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["hour"] + list(cols))
        for h in range(n):
            w.writerow([h] + [f"{v[h]:.6g}" for v in cols.values()])
    return n


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    rt = json.loads((CASES_DIR / "round_trip.json").read_text())
    hz_files = {"moon_equator": "moon_equator_horizons.txt", "mars_jezero": "mars_jezero_horizons.txt"}
    for case in ("moon_equator", "mars_jezero"):
        g = sqlite3.connect(RUNS / "roundtrip" / f"{case}_gen" / "out" / "eplusout.sql")
        p = sqlite3.connect(RUNS / "roundtrip" / f"{case}_pwf" / "out" / "eplusout.sql")
        _az, hz = horizons(CASES_DIR / "horizons" / hz_files[case])
        cols = dict(
            alt=sql_series(g, "Site Solar Altitude Angle"), hz_alt=hz,
            beam=sql_series(g, "Site Direct Solar Radiation Rate per Area"), dif=sql_series(g, "Site Diffuse Solar Radiation Rate per Area"),
            Tg=sql_series(g, "Site Planetary Ground Surface Temperature"), Tsky=sql_series(g, "Site Sky Temperature"),
            Qc=sql_series(g, "Zone Ideal Loads Zone Sensible Cooling Rate"), pwf_Qc=sql_series(p, "Zone Ideal Loads Zone Sensible Cooling Rate"),
            top=sql_series(g, "Surface Outside Face Temperature", "SHELL_00"), pwf_top=sql_series(p, "Surface Outside Face Temperature", "SHELL_00"),
            tin=sql_series(g, "Surface Inside Face Temperature", "SHELL_00"), pwf_tin=sql_series(p, "Surface Inside Face Temperature", "SHELL_00"),
        )
        n = write_csv(OUT / f"core_{case}_hourly.csv", cols)
        summary[case] = dict(hours_total=n, round_trip=rt[case], cooling_window_kWh=rt[case]["cooling_gen_kWh"])
        print(case, n, "hours")
    # NASA-informed lunar habitat (generator run; the weather-file run agrees within the round-trip figures)
    g = sqlite3.connect(RUNS / "roundtrip" / "lunar_habitat_gen" / "out" / "eplusout.sql")
    cols = dict(Qc=sql_series(g, "Zone Ideal Loads Zone Sensible Cooling Rate"), Ql=sql_series(g, "Zone Ideal Loads Zone Latent Cooling Rate"),
                rh=sql_series(g, "Zone Air Relative Humidity") / 100.0, Tz=sql_series(g, "Zone Mean Air Temperature"),
                To_s=sql_series(g, "Surface Outside Face Temperature", "WALL_05"), To_r=sql_series(g, "Surface Outside Face Temperature", "ROOF"),
                To_f=sql_series(g, "Surface Outside Face Temperature", "FLOOR"), Tg=sql_series(g, "Site Planetary Ground Surface Temperature"))
    n = write_csv(OUT / "core_lunar_habitat_hourly.csv", cols)
    a = 72
    summary["lunar_habitat"] = dict(hours_total=n, window_first_hour=a, round_trip=rt["lunar_habitat"],
                                    sensible_kWh=float(cols["Qc"][a:].sum() / 1000), latent_kWh=float(cols["Ql"][a:].sum() / 1000),
                                    mean_sensible_kW=float(cols["Qc"][a:].mean() / 1000), peak_sensible_kW=float(cols["Qc"][a:].max() / 1000),
                                    To_s_range_C=[float(cols["To_s"][a:].min()), float(cols["To_s"][a:].max())],
                                    To_f_range_C=[float(cols["To_f"][a:].min()), float(cols["To_f"][a:].max())])
    summary["pv_vacuum"] = json.loads((CASES_DIR / "pv_vacuum" / "pv_vacuum_check.json").read_text())
    summary["horizons"] = json.loads((CASES_DIR / "horizons" / "horizons_check.json").read_text())
    summary["boundary"] = json.loads((CASES_DIR / "boundary_check.json").read_text())
    summary["moon_regolith"] = json.loads((CASES_DIR / "moon_regolith_check.json").read_text())
    summary["mars_sky"] = json.loads((CASES_DIR / "mars_sky_check.json").read_text())
    summary["robustness"] = json.loads((CASES_DIR / "robustness.json").read_text())
    summary["humidity"] = json.loads((CASES_DIR / "humidity_check.json").read_text())
    summary["mars_convection"] = json.loads((CASES_DIR / "mars_convection_scope.json").read_text())
    summary["planetary_tests"] = json.loads((CORE / "planetary" / "tests" / "test_results.json").read_text())
    summary["earth_regression"] = {w: json.loads((RUNS / f"earth_regression_{w}" / "summary.json").read_text())
                                   for w in ("chicago", "phoenix")}
    summary["audit_inventory"] = json.loads((CORE / "planetary" / "audit" / "inventory" / "audit_inventory_summary.json").read_text())
    shutil.copyfile(CORE / "planetary" / "audit" / "inventory" / "audit_inventory.csv", OUT / "audit_inventory.csv")
    rr = RUNS / "m2e_cases" / "summary.json"
    summary["case_rerun"] = json.loads(rr.read_text()) if rr.exists() else {}
    # refused object types (with reasons where the validator gives one) and the patch-set history
    src = (CORE / "src" / "EnergyPlus" / "PlanetaryBody.cc").read_text(encoding="utf-8")
    body = src[src.index("void ValidateInput("):src.index("// ---------------------------------------------------------------------------------------------- environment")]
    first = body[body.index("blocked = {"):body.index("};", body.index("blocked = {"))]
    refused = [[o, "needs outdoor air, Earth weather or an Earth-only model"] for o in re.findall(r'"([A-Za-z0-9:\-]+)"', first)]
    refused += [[o, why] for o, why in re.findall(r'\{"([A-Za-z0-9:\-]+)", "([^"]+)"\}', body)]
    summary["refused"] = refused
    versions = []
    for f in sorted((CORE / "planetary" / "tools").glob("apply_hooks_m*.py")):
        doc = f.read_text(encoding="utf-8").split('"""')[1]
        versions.append([f.stem.replace("apply_hooks_", "").upper(), " ".join(doc.split("Run from")[0].split())])
    summary["versions"] = versions
    summary["meta"] = dict(source="Thermonaut M2e (branch thermonaut)", moon_window="second lunation (720 h)",
                           mars_window="days 16-31 (384 h)", habitat_window="days 4-30 (648 h)",
                           modes="gen = engine's own environment generator; pwf = engine reading the weather file exported from it")
    (OUT / "core_summary.json").write_text(json.dumps(summary, indent=1))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
