"""Robustness and sensitivity studies for the Thermonaut paper (all runs use the engine itself).

  1. depth   - lunar regolith temperature at 0.5, 1, 2 and 3 m (equatorial site, periodic equilibrium)
  2. spinup  - start-up correction against a long spin-up: a multi-year run versus a short run that starts on the same
               final dates (Mars: 25 months vs 31 days; Moon: 36 months vs 2 lunations)
  3. startup - sensitivity of the regolith-module result to warm-up length, CondFD grid and time step (Mars; a
               coarser step than 3 min is not possible: EnergyPlus requires 20 steps per hour with CondFD)
  4. params  - sensitivity of cooling energy to uncertain planetary inputs (Moon habitat; Mars regolith module)
  5. kT      - convergence of the steady k(T) start-up profile with the number of fixed-point iterations

    python planetary/cases/robustness.py [energyplus.exe] [study ...]   ->  planetary/cases/robustness.json (merged)
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 and sys.argv[1].endswith(".exe") else ROOT / "build" / "Products" / "energyplus.exe"
STUDIES = [a for a in sys.argv[1:] if not a.endswith(".exe")] or ["depth", "startup", "params", "kT", "spinup"]
WORK = ROOT.parent / "exo-runs" / "robustness"
OUT = HERE / "robustness.json"
PB_FIELDS = ["name", "body", "clock", "year", "gravity", "cabin_p", "o2", "air_v", "conv_len", "horizon", "thermal_inertia",
             "albedo", "emissivity", "spinup", "deep_depth", "mars_p", "dust_model", "dust_tau", "storm_start", "storm_end",
             "storm_peak", "wind_mean", "wind_amp", "pwf"]
MARS_TAIL = ["710", "Climatology", "0.5", "0", "0", "0", "3.2", "2.0", ""]


def set_pb(idf, **kw):
    """Edit fields of the (single-line) Site:PlanetaryBody object."""
    m = re.search(r"^Site:PlanetaryBody,(.*);\s*$", idf, re.M)
    f = m.group(1).split(",")
    while len(f) < len(PB_FIELDS):
        f.append(MARS_TAIL[len(f) - 15] if len(f) >= 15 else "")
    for k, v in kw.items():
        f[PB_FIELDS.index(k)] = str(v)
    return idf[:m.start()] + "Site:PlanetaryBody," + ",".join(f) + ";" + idf[m.end():]


def set_runperiod(idf, m1, d1, y1, m2, d2, y2):
    return re.sub(r"^RunPeriod,([^,]*),[^;]*;", lambda mo: f"RunPeriod,{mo.group(1)},{m1},{d1},{y1},{m2},{d2},{y2},,No,No,No,Yes,Yes;",
                  idf, count=1, flags=re.M)


def run(name, idf, files=(), epw=None):
    d = WORK / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    (d / "in.idf").write_text(idf)
    for f in files:
        shutil.copy(f, d / Path(f).name)
    cmd = [str(EXE), "-d", str(d / "out")] + (["-w", str(epw)] if epw else []) + [str(d / "in.idf")]
    subprocess.run(cmd, cwd=d, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    err = (d / "out" / "eplusout.err").read_text(errors="replace")
    if "Completed Successfully" not in err:
        raise RuntimeError(f"{name} failed:\n" + "\n".join(l for l in err.splitlines() if "Severe" in l or "Fatal" in l)[:2000])
    return sqlite3.connect(d / "out" / "eplusout.sql")


def series(db, name, key=None):
    q = ("SELECT rd.Value FROM ReportData rd JOIN ReportDataDictionary d ON rd.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex "
         "JOIN Time t ON rd.TimeIndex=t.TimeIndex WHERE d.Name=? AND (t.WarmupFlag=0 OR t.WarmupFlag IS NULL) "
         "AND t.EnvironmentPeriodIndex=(SELECT MAX(EnvironmentPeriodIndex) FROM Time)")
    a = [name]
    if key:
        q += " AND UPPER(d.KeyValue)=UPPER(?)"
        a.append(key)
    return np.array([r[0] for r in db.execute(q + " ORDER BY rd.TimeIndex", a)], float)


def cooling_kwh(db, last_hours=None, skip_hours=0):
    q = series(db, "Zone Ideal Loads Zone Sensible Cooling Rate")
    q = q[skip_hours:] if last_hours is None else q[-last_hours:]
    return float(q.sum() / 1000.0)


MOON = HERE / "moon_equator"
MARS = HERE / "mars_jezero"
HAB = HERE / "lunar_habitat"


def study_depth():
    base = (MOON / "moon_equator.idf").read_text()
    base = set_runperiod(base, 1, 1, 2030, 1, 2, 2030)
    out = {}
    for z in (0.5, 1.0, 2.0, 3.0):
        db = run(f"depth_{z}", set_pb(base, deep_depth=z), epw=MOON / "placeholder.epw")
        out[f"{z}"] = float(series(db, "Site Planetary Deep Ground Temperature").mean() + 273.15)
        print("depth", z, round(out[f"{z}"], 2), flush=True)
    return out


def study_spinup():
    res = {}
    # Mars: 25 months vs 31 days, compare days 16-31 of January 2032 (384 h)
    m = (MARS / "mars_jezero.idf").read_text()
    # the environment starts at Reference Year + RunPeriod start date, so a short run sets its own reference year
    jobs = {"mars_long": set_runperiod(m, 1, 1, 2030, 1, 31, 2032),
            "mars_short": set_pb(set_runperiod(m, 1, 1, 2032, 1, 31, 2032), year=2032)}
    # Moon: 36 months vs 2 lunations ending on the same day, compare the last 720 h
    mo = (MOON / "moon_equator.idf").read_text()
    jobs["moon_long"] = set_runperiod(mo, 1, 1, 2030, 12, 31, 2032)
    jobs["moon_short"] = set_pb(set_runperiod(mo, 11, 2, 2032, 12, 31, 2032), year=2032)
    epw = {"mars": MARS / "placeholder.epw", "moon": MOON / "placeholder.epw"}

    def one(k):
        db = run(f"spinup_{k}", jobs[k], epw=epw[k.split("_")[0]])
        n = 384 if k.startswith("mars") else 720
        return k, dict(cooling_kWh=cooling_kwh(db, last_hours=n),
                       inner_face_C=float(series(db, "Surface Inside Face Temperature", "SHELL_00")[-n:].mean()))

    with ThreadPoolExecutor(4) as ex:
        for k, v in ex.map(one, list(jobs)):
            res[k] = v
            print("spinup", k, v, flush=True)
    for b in ("mars", "moon"):
        L, S = res[f"{b}_long"], res[f"{b}_short"]
        res[f"{b}_short_vs_long_pct"] = 100 * (S["cooling_kWh"] / L["cooling_kWh"] - 1)
    return res


def study_startup():
    m = (MARS / "mars_jezero.idf").read_text()
    variants = {
        "base": m,
        "warmup_min1": m.replace("FullExterior,25,6;", "FullExterior,25,1;"),
        "warmup_min20": m.replace("FullExterior,25,6;", "FullExterior,40,20;"),
        "grid_C10": m.replace("FullyImplicitFirstOrder,30,1.0,0.002;", "FullyImplicitFirstOrder,10,1.0,0.002;"),
        "grid_C90": m.replace("FullyImplicitFirstOrder,30,1.0,0.002;", "FullyImplicitFirstOrder,90,1.0,0.002;"),
        "timestep_30": m.replace("Timestep,20;", "Timestep,30;"),
    }
    for k, v in variants.items():
        assert k == "base" or v != m, k

    def one(k):
        db = run(f"startup_{k}", variants[k], epw=MARS / "placeholder.epw")
        q = series(db, "Zone Ideal Loads Zone Sensible Cooling Rate")
        return k, dict(window_kWh=float(q[-384:].sum() / 1000), first_hour_W=float(q[0]))

    out = {}
    with ThreadPoolExecutor(4) as ex:
        for k, v in ex.map(one, list(variants)):
            out[k] = v
    for k in out:
        out[k]["vs_base_pct"] = 100 * (out[k]["window_kWh"] / out["base"]["window_kWh"] - 1)
        print("startup", k, out[k], flush=True)
    return out


def study_params():
    out = {}
    # Moon: NASA-informed habitat, internal generator (no weather file), days 4-30
    h = (HAB / "lunar_habitat.idf").read_text().replace(",lunar_habitat.pwf;", ",;")
    mats = {"beta": "Material,beta_cloth_sh,MediumRough,0.001,0.15,1400,900,0.9,0.4,0.4;",
            "mli": "Material:NoMass,mli_10layer_sh,MediumRough,19.2,0.9,0.4,0.4;"}
    for v in mats.values():
        assert v in h, v
    moon = {
        "base": h,
        "regolith_albedo_0.07": set_pb(h, albedo=0.07), "regolith_albedo_0.17": set_pb(h, albedo=0.17),
        "regolith_emissivity_0.90": set_pb(h, emissivity=0.90), "regolith_emissivity_0.99": set_pb(h, emissivity=0.99),
        "horizon_5deg": set_pb(h, horizon=5.0),
        "shell_solar_abs_0.3": h.replace(mats["beta"], mats["beta"].replace(",0.9,0.4,0.4;", ",0.9,0.3,0.3;")),
        "shell_solar_abs_0.5": h.replace(mats["beta"], mats["beta"].replace(",0.9,0.4,0.4;", ",0.9,0.5,0.5;")),
        "shell_emissivity_0.80": h.replace(mats["beta"], mats["beta"].replace(",0.9,0.4,0.4;", ",0.8,0.4,0.4;")),
        "mli_R_-25pct": h.replace(mats["mli"], mats["mli"].replace(",19.2,", ",14.4,")),
        "mli_R_+25pct": h.replace(mats["mli"], mats["mli"].replace(",19.2,", ",24.0,")),
    }
    m = (MARS / "mars_jezero.idf").read_text()
    m = set_pb(m)  # expand to all fields
    mars = {
        "base": m,
        "thermal_inertia_250": set_pb(m, thermal_inertia=250), "thermal_inertia_450": set_pb(m, thermal_inertia=450),
        "regolith_albedo_0.10": set_pb(m, albedo=0.10), "regolith_albedo_0.18": set_pb(m, albedo=0.18),
        "dust_tau_0.3": set_pb(m, dust_model="Constant", dust_tau=0.3), "dust_tau_1.5": set_pb(m, dust_model="Constant", dust_tau=1.5),
        "wind_1": set_pb(m, wind_mean=1.0), "wind_6": set_pb(m, wind_mean=6.0),
    }
    jobs = [("moon", k) for k in moon] + [("mars", k) for k in mars]

    def one(job):
        b, k = job
        if b == "moon":
            db = run(f"params_moon_{k}", moon[k], epw=MOON / "placeholder.epw")
            return job, cooling_kwh(db, skip_hours=72)
        db = run(f"params_mars_{k}", mars[k], epw=MARS / "placeholder.epw")
        return job, cooling_kwh(db, last_hours=384)

    res = {"moon": {}, "mars": {}}
    with ThreadPoolExecutor(4) as ex:
        for (b, k), v in ex.map(one, jobs):
            res[b][k] = dict(cooling_kWh=v)
    for b in res:
        for k in res[b]:
            res[b][k]["vs_base_pct"] = 100 * (res[b][k]["cooling_kWh"] / res[b]["base"]["cooling_kWh"] - 1)
            print("params", b, k, res[b][k], flush=True)
    return res


def study_kT():
    """Fixed-point convergence of the steady profile of Eq. (steady) for the lunar regolith-module shell."""
    s = (MOON / "moon_equator.idf").read_text()
    shell = re.search(r"^Construction,shell,([^;]*);", s, re.M).group(1).split(",")
    layers = []
    for name in shell:
        mm = re.search(rf"^Material,{re.escape(name)},[^,]*,([^,]*),([^,]*),", s, re.M)
        nm = re.search(rf"^Material:NoMass,{re.escape(name)},[^,]*,([^,]*),", s, re.M)
        kt = re.search(rf"^MaterialProperty:VariableThermalConductivity,{re.escape(name)},([^;]*);", s, re.M)
        if nm:
            layers.append(dict(R=float(nm.group(1))))
        else:
            th, k = float(mm.group(1)), float(mm.group(2))
            tab = None
            if kt:
                v = [float(x) for x in kt.group(1).split(",") if x.strip()]
                tab = (np.array(v[0::2]), np.array(v[1::2]))
            layers.append(dict(th=th, k=k, tab=tab))
    # discretize each massive layer into 20 segments (the engine uses its own CondFD nodes; the fixed point is the same)
    segs = []
    for L in layers:
        if "R" in L:
            segs.append(("R", L["R"], None))
        else:
            for _ in range(20):
                segs.append(("k", L["th"] / 20, L))
    To, Tin = -25.0, 21.0
    T = np.linspace(To, Tin, len(segs) + 1)
    hist = []
    for it in range(12):
        R = [0.0]
        for i, (kind, a, L) in enumerate(segs):
            if kind == "R":
                R.append(R[-1] + a)
            else:
                tm = 0.5 * (T[i] + T[i + 1])
                k = float(np.interp(tm, *L["tab"])) if L["tab"] is not None else L["k"]
                R.append(R[-1] + a / k)
        R = np.array(R)
        Tn = To + (Tin - To) * R / R[-1]
        hist.append(float(np.max(np.abs(Tn - T))))
        T = Tn
    return dict(max_change_per_iteration_K=hist, note="iteration 1 starts from a linear profile; the engine uses 6 iterations")


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    res = json.loads(OUT.read_text()) if OUT.exists() else {}
    for s in STUDIES:
        res[s] = globals()[f"study_{s}"]()
        OUT.write_text(json.dumps(res, indent=1))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
