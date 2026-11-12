"""Thermonaut planetary-mode tests (complement to the upstream EnergyPlus unit tests, which do not exercise it).

Each test runs energyplus.exe on a short variant of the NASA-informed lunar habitat input (2 days, CTF) or of an Earth
example file and checks the outcome: a clean run, or the specific severe/fatal message expected.

    python planetary/tests/run_planetary_tests.py [build/Products/energyplus.exe]   ->  planetary/tests/test_results.json
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HAB = ROOT / "planetary" / "cases" / "lunar_habitat"
EXE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "build" / "Products" / "energyplus.exe"
WORK = ROOT / "planetary" / "tests" / "_runs"
EARTH_IDF = ROOT / "testfiles" / "1ZoneUncontrolled.idf"
EARTH_EPW = ROOT / "weather" / "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw"


def base_idf():
    s = (HAB / "lunar_habitat.idf").read_text()
    return s.replace("RunPeriod,lunar_habitat,1,1,2030,1,30,2030,", "RunPeriod,lunar_habitat,1,1,2030,1,2,2030,")


def pwf_lines():
    return (HAB / "lunar_habitat.pwf").read_text().splitlines()


def header_index(lines):
    return next(i for i, l in enumerate(lines) if l.startswith("time_s,"))


def edit_pwf_column(lines, col, record, value):
    h = header_index(lines)
    cols = lines[h].split(",")
    j = cols.index(col)
    out = list(lines)
    f = out[h + record].split(",")
    f[j] = value
    out[h + record] = ",".join(f)
    return out


def drop_pwf_column(lines, col):
    h = header_index(lines)
    j = lines[h].split(",").index(col)
    return lines[:h] + [",".join(v for k, v in enumerate(l.split(",")) if k != j) for l in lines[h:]]


def run(name, idf_text, pwf=None, epw=None):
    d = WORK / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    (d / "in.idf").write_text(idf_text)
    if pwf is not None:
        (d / "lunar_habitat.pwf").write_text("\n".join(pwf) + "\n")
    cmd = [str(EXE), "-d", str(d / "out")]
    if epw:
        cmd += ["-w", str(epw)]
    subprocess.run(cmd + [str(d / "in.idf")], cwd=d, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    err = (d / "out" / "eplusout.err").read_text(errors="replace") if (d / "out" / "eplusout.err").exists() else ""
    return d, err


def ok(err):
    return "EnergyPlus Completed Successfully" in err and re.search(r"[1-9]\d* Severe Errors", err) is None


def eso_values(path):
    lines = path.read_text(errors="replace").splitlines()
    k = lines.index("End of Data Dictionary")
    return lines[k + 1:]


def main():
    idf, pwf = base_idf(), pwf_lines()
    tests = []

    def check(name, desc, passed, detail=""):
        tests.append(dict(name=name, description=desc, passed=bool(passed), detail=detail))
        print(("PASS " if passed else "FAIL ") + name + (f"  ({detail})" if detail and not passed else ""))

    # --- accepted inputs
    _, err = run("valid_habitat", idf, pwf)
    check("valid_habitat", "Habitat with crew/equipment OtherEquipment, InternalMass, thermostat, humidistat and ideal loads runs cleanly",
          ok(err))
    gen = idf.replace(",lunar_habitat.pwf;", ",;")
    _, err = run("valid_generator", gen, epw=ROOT / "planetary" / "cases" / "moon_equator" / "placeholder.epw")
    check("valid_generator", "Same habitat with the internal environment generator (calendar-only EPW, every weather value generated) runs cleanly", ok(err))

    # --- planetary weather file checks
    bad = [l.replace("# body: moon", "# body: mars") for l in pwf]
    _, err = run("pwf_wrong_body", idf, bad)
    check("pwf_wrong_body", "PWF for another body is rejected", "is for body" in err)
    _, err = run("pwf_missing_column", idf, drop_pwf_column(pwf, "T_ground_K"))
    check("pwf_missing_column", "PWF without a required column is rejected", "lacks the required column T_ground_K" in err)
    _, err = run("pwf_negative_irradiance", idf, edit_pwf_column(pwf, "dni_W_m2", 5, "-12"))
    check("pwf_negative_irradiance", "Negative irradiance is rejected with its record number", "dni_W_m2 = -12 in record 5" in err)
    _, err = run("pwf_missing_ground", idf, edit_pwf_column(pwf, "T_ground_K", 7, "nan"))
    check("pwf_missing_ground", "A missing (nan) ground temperature is rejected", "T_ground_K is missing (nan) in record 7" in err)
    _, err = run("pwf_air_nan_vacuum", idf, pwf)
    check("pwf_air_nan_vacuum", "nan air temperature (vacuum) is accepted", ok(err))
    _, err = run("pwf_bad_albedo", idf, edit_pwf_column(pwf, "ground_albedo", 3, "1.4"))
    check("pwf_bad_albedo", "Albedo above 1 is rejected", "ground_albedo = 1.4 in record 3" in err)
    h = header_index(pwf)
    _, err = run("pwf_unequal_spacing", idf, pwf[:h + 10] + pwf[h + 11:])
    check("pwf_unequal_spacing", "Records that are not equally spaced are rejected", "not equally spaced" in err)
    long_run = idf.replace("RunPeriod,lunar_habitat,1,1,2030,1,2,2030,", "RunPeriod,lunar_habitat,1,1,2030,1,5,2030,")
    _, err = run("pwf_short_coverage", long_run, pwf[:h + 1 + 160])
    check("pwf_short_coverage", "A file that does not cover the run period is rejected", "does not cover the run period" in err)
    _, err = run("pwf_not_pwf", idf, ["time_s,dni"] + pwf[h + 1:h + 5])
    check("pwf_not_pwf", "A file without the PWF header is rejected", "is not a PWF planetary weather file" in err)

    # --- input validator
    inf = idf + ("\nZoneInfiltration:DesignFlowRate,leak,lunar_surface_habitat,life_support_sched,AirChanges/Hour,,,,0.1,1,0,0,0;\n")
    _, err = run("refuse_infiltration", inf, pwf)
    check("refuse_infiltration", "Infiltration is refused in planetary mode", "ZoneInfiltration:DesignFlowRate" in err and "Severe" in err)
    pv = (ROOT / "planetary" / "cases" / "pv_vacuum" / "pv_refused.idf")
    if pv.exists():
        d = WORK / "refuse_pv_battery"
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        # run in place: the input refers to its weather file by a relative path
        subprocess.run([str(EXE), "-d", str(d / "out"), str(pv)], cwd=pv.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        err = (d / "out" / "eplusout.err").read_text(errors="replace")
        check("refuse_pv_battery", "Ulleberg dynamic PV and a Li-ion battery without a zone are both refused",
              "cell-temperature model is fitted to Earth air" in err and "needs a Zone Name off-Earth" in err)
    neg = idf.replace(",5.25,0.0,autocalculate,", ",5.25,-2.0,autocalculate,")
    _, err = run("refuse_negative_horizon", neg, pwf)
    check("refuse_negative_horizon", "A negative horizon elevation is refused", "negative Horizon Elevation Angle" in err)

    sc = idf.replace("SurfaceConvectionAlgorithm:Outside,DOE-2;", "SurfaceConvectionAlgorithm:Outside,SimpleCombined;")
    _, err = run("refuse_simplecombined", sc, pwf)
    check("refuse_simplecombined", "Outside convection SimpleCombined (radiation folded into h) is refused",
          "SurfaceConvectionAlgorithm:Outside SimpleCombined is not supported" in err)
    t1 = idf.replace("Timestep,20;", "Timestep,1;")
    _, err = run("refuse_timestep1", t1, pwf)
    check("refuse_timestep1", "One time step per hour (sun at mid-hour) is refused", "one time step per hour is not supported" in err)
    wu = idf + "\nWaterUse:Equipment,crew_water,,0.0001,life_support_sched;\n"
    _, err = run("refuse_water_mains", wu, pwf)
    check("refuse_water_mains", "Water use without scheduled mains temperature is refused", "need Site:WaterMainsTemperature" in err)
    eco = idf + "\nMaterial:RoofVegetation,eco,0.5,5,0.2,0.95,180,EcoRoofSoil,MediumSmooth,0.18,0.4,641,1100,0.95,0.8,0.7,0.4,0.01,0.2,Simple;\n"
    _, err = run("refuse_ecoroof", eco, pwf)
    check("refuse_ecoroof", "EcoRoof material is refused", "Material:RoofVegetation objects are not supported off-Earth" in err)

    win = idf + "\nWindow,porthole,porthole_glass,WALL_05,,1,0.5,1.0,0.5,0.5;\n"
    _, err = run("refuse_window", win, pwf)
    check("refuse_window", "Windows are refused in this version", "Window objects are not supported off-Earth" in err)
    ch = idf + "\nChiller:Electric:EIR,chiller,10000,5.5,6.67,29.4,0.001,0.003,cap,eir,plr,0.1,1,1,0.2,chw_in,chw_out,cnd_in,cnd_out,AirCooled;\n"
    _, err = run("refuse_aircooled_chiller", ch, pwf)
    check("refuse_aircooled_chiller", "An air-cooled chiller is refused", "air- and evaporatively cooled condensers are not supported" in err)

    ff = idf + "\nConstruction:FfactorGroundFloor,slab_ff,0.5,30,20;\n"
    _, err = run("refuse_ffactor", ff, pwf)
    check("refuse_ffactor", "F-factor ground floors (Earth ground temperatures) are refused",
          "Construction:FfactorGroundFloor objects are not supported off-Earth" in err)
    co2 = idf + "\nZoneAirContaminantBalance,Yes,life_support_sched;\n"
    _, err = run("refuse_co2_balance", co2, pwf)
    check("refuse_co2_balance", "The CO2 balance (standard-pressure air) is refused", "Carbon Dioxide Concentration = Yes is not supported" in err)

    # --- Earth: the object with Body = Earth changes nothing
    e = EARTH_IDF.read_text()
    d0, err0 = run("earth_plain", e, epw=EARTH_EPW)
    e2 = e + ("\nSite:PlanetaryBody,earth,Earth,EarthClock,2030,autocalculate,101325,0.21,0.15,2.5,0.0,autocalculate,"
              "autocalculate,autocalculate,autocalculate,3.0,710,Climatology,0.5,0,0,0,3.2,2.0,;\n")
    d1, err1 = run("earth_with_object", e2, epw=EARTH_EPW)
    same = ok(err0) and ok(err1) and eso_values(d0 / "out" / "eplusout.eso") == eso_values(d1 / "out" / "eplusout.eso")
    check("earth_body_identical", "Site:PlanetaryBody with Body = Earth gives an identical ESO to the same file without it", same)

    res = dict(engine=str(EXE), passed=sum(t["passed"] for t in tests), total=len(tests), tests=tests)
    (ROOT / "planetary" / "tests" / "test_results.json").write_text(json.dumps(res, indent=1))
    print(f"{res['passed']}/{res['total']} passed")
    return 0 if res["passed"] == res["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
