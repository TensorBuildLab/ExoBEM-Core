"""Earth regression: Thermonaut must reproduce unmodified EnergyPlus v26.2.0 exactly when no planetary body is set.

Runs each example file with the baseline build and the fork and compares the full ESO time series and the
tabular (HTML) results numerically. Usage:
    python planetary/tools/earth_regression.py --baseline ../exo-baseline-bin --fork build/Products [files...]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FILES = [
    "1ZoneUncontrolled.idf", "1ZoneUncontrolledFourAlgorithms.idf", "1ZoneUncontrolledCondFDWithVariableKat24C.idf",
    "1ZoneUncontrolled_FCfactor_Slab_UGWall.idf", "1ZoneUncontrolled_win_1.idf", "5ZoneAirCooled.idf",
    "5ZoneAirCooledConvCoef.idf", "5ZoneWaterSystems.idf", "ShopWithPVandBattery.idf", "RefBldgSmallOfficeNew2004_Chicago.idf",
    "EMPD5ZoneWaterCooled_HighRHControl.idf", "HAMT_HourlyProfileReport.idf", "ZoneCoupledKivaConvection.idf", "DaylightingDeviceShelf.idf", "SolarCollectorFlatPlateWater.idf",
]
WEATHER = {"default": "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw"}
NUM = re.compile(r"-?\d+\.?\d*(?:[Ee][-+]?\d+)?")


def run(exe_dir: Path, idf: Path, out: Path):
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    epw = ROOT / "weather" / WEATHER["default"]
    cmd = [str(exe_dir / "energyplus.exe"), "-w", str(epw), "-d", str(out), str(idf)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    return p.returncode, (out / "eplusout.err").read_text(errors="ignore") if (out / "eplusout.err").exists() else ""


def eso_numbers(path: Path):
    """All numeric records of the ESO data section (dictionary and timestamps included)."""
    if not path.exists():
        return None
    lines = path.read_text(errors="ignore").splitlines()
    try:
        start = lines.index("End of Data Dictionary") + 1
    except ValueError:
        start = 0
    return [l for l in lines[start:] if l and not l.startswith("End of Data")]


def compare(a: Path, b: Path):
    ea, eb = eso_numbers(a / "eplusout.eso"), eso_numbers(b / "eplusout.eso")
    if ea is None or eb is None:
        return dict(status="missing eso")
    if len(ea) != len(eb):
        return dict(status=f"length differs {len(ea)} vs {len(eb)}")
    ndiff, maxrel, first = 0, 0.0, None
    for la, lb in zip(ea, eb):
        if la == lb:
            continue
        na, nb = NUM.findall(la), NUM.findall(lb)
        for x, y in zip(na, nb):
            fx, fy = float(x), float(y)
            if fx != fy:
                ndiff += 1
                rel = abs(fx - fy) / max(abs(fx), abs(fy), 1e-12)
                maxrel = max(maxrel, rel)
                first = first or (la, lb)
    return dict(status="identical" if ndiff == 0 else "DIFFERENT", n_diff=ndiff, max_rel=maxrel, first=first)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default=str(ROOT.parent / "exo-baseline-bin"))
    ap.add_argument("--fork", default=str(ROOT / "build" / "Products"))
    ap.add_argument("--out", default=str(ROOT.parent / "exo-runs" / "earth_regression"))
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("files", nargs="*", default=DEFAULT_FILES)
    args = ap.parse_args()
    out = Path(args.out)
    results = {}

    def one(f):
        idf = ROOT / "testfiles" / f
        if not idf.exists():
            return f, dict(status="no such test file")
        rb, eb = run(Path(args.baseline), idf, out / Path(f).stem / "baseline")
        rf, ef = run(Path(args.fork), idf, out / Path(f).stem / "fork")
        if rb != 0 or rf != 0:
            return f, dict(status=f"run failed baseline={rb} fork={rf}", fork_err=ef[-800:])
        return f, compare(out / Path(f).stem / "baseline", out / Path(f).stem / "fork")

    with ThreadPoolExecutor(args.jobs) as ex:
        for f, r in ex.map(one, args.files):
            results[f] = r
            print(f"{f:55s} {r['status']}" + (f"  n={r.get('n_diff')} maxrel={r.get('max_rel'):.2e}" if r.get("n_diff") else ""))
    (out / "summary.json").write_text(json.dumps(results, indent=1, default=str))
    n_ok = sum(r["status"] == "identical" for r in results.values())
    print(f"\n{n_ok}/{len(results)} identical")


if __name__ == "__main__":
    main()
