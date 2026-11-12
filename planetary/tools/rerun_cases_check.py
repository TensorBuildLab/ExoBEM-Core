"""Rerun every planetary verification case with the current build and check that its output is identical to the
recorded runs (a patch set that only adds input checks must not change any planetary result).

    python planetary/tools/rerun_cases_check.py   ->  ../exo-runs/m2e_cases/summary.json
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXE = ROOT / "build" / "Products" / "energyplus.exe"
CASES = ROOT / "planetary" / "cases"
RUNS = ROOT.parent / "exo-runs"
OUT = RUNS / "m2e_cases"

JOBS = [  # name, input, weather (None: none), recorded output folder
    ("moon_equator_gen", CASES / "moon_equator" / "moon_equator.idf", CASES / "moon_equator" / "placeholder.epw", RUNS / "m2d" / "moon_equator_gen"),
    ("mars_jezero_gen", CASES / "mars_jezero" / "mars_jezero.idf", CASES / "mars_jezero" / "placeholder.epw", RUNS / "m2d" / "mars_jezero_gen"),
    ("moon_equator_pwf", CASES / "moon_equator" / "moon_equator_pwf.idf", None, RUNS / "m2d" / "moon_equator_pwf"),
    ("mars_jezero_pwf", CASES / "mars_jezero" / "mars_jezero_pwf.idf", None, RUNS / "m2d" / "mars_jezero_pwf"),
    ("lunar_habitat", CASES / "lunar_habitat" / "lunar_habitat.idf", None, CASES / "lunar_habitat" / "out"),
    ("pv_vacuum", CASES / "pv_vacuum" / "pv_vacuum.idf", None, CASES / "pv_vacuum" / "out"),
]


def data(eso):
    lines = eso.read_text(errors="replace").splitlines()
    return lines[lines.index("End of Data Dictionary") + 1:]


def main():
    res = {}
    for name, idf, epw, ref in JOBS:
        d = OUT / name
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        cmd = [str(EXE), "-d", str(d)] + (["-w", str(epw)] if epw else []) + [str(idf)]
        subprocess.run(cmd, cwd=idf.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        err = (d / "eplusout.err").read_text(errors="replace")
        okrun = "EnergyPlus Completed Successfully" in err
        same = okrun and (ref / "eplusout.eso").exists() and data(d / "eplusout.eso") == data(ref / "eplusout.eso")
        res[name] = dict(completed=okrun, identical_to_recorded=bool(same), n_lines=len(data(d / "eplusout.eso")) if okrun else 0)
        print(name, res[name])
    (OUT / "summary.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
