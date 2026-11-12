"""Write a planetary weather file (PWF 1.0) from Thermonaut's own environment generator.

The input file is run in generator mode (no weather file named in Site:PlanetaryBody) with every site variable
reported at the zone time step; the generated environment is then written in the format of
planetary/docs/weather_format.md. State quantities (temperatures, pressure, wind, albedo) are the values at the end
of each time step; solar quantities refer to the middle of each interval and are taken as the mean of the two
adjacent end-of-step values. Rerunning the same input with the exported file is a round-trip check of the reader.

    python planetary/tools/export_pwf.py <case.idf> <placeholder.epw> <out.pwf> [energyplus.exe]
"""
from __future__ import annotations

import math
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SOLAR_1AU, SUN_RADIUS_1AU, MARS_SOL_S, MOON_SYNODIC_S = 1361.0, 0.2666, 88775.244147, 29.530589 * 86400.0
VARS = ["Site Direct Solar Radiation Rate per Area", "Site Diffuse Solar Radiation Rate per Area",
        "Site Ground Reflected Solar Radiation Rate per Area", "Site Solar Altitude Angle", "Site Solar Azimuth Angle",
        "Site Sky Temperature", "Site Outdoor Air Drybulb Temperature", "Site Wind Speed",
        "Site Planetary Ground Surface Temperature", "Site Planetary Deep Ground Temperature",
        "Site Planetary Ambient Pressure", "Site Planetary Downwelling Longwave Radiation", "Site Planetary Dust Optical Depth",
        "Site Planetary Solar Longitude", "Site Planetary Sun Distance"]


def planetary_fields(idf: str) -> list[str]:
    m = re.search(r"^Site:PlanetaryBody,(.*);\s*$", idf, re.M)
    return m.group(1).split(",")


def generator_input(idf: str) -> str:
    """The case in generator mode, with only the site variables reported at every time step."""
    m = re.search(r"^Site:PlanetaryBody,(.*);\s*$", idf, re.M)
    f = m.group(1).split(",")
    if len(f) >= 24:
        f[23] = ""
    idf = idf[:m.start()] + "Site:PlanetaryBody," + ",".join(f) + ";" + idf[m.end():]
    idf = re.sub(r"^Output:(Variable|Meter|SQLite|Table:SummaryReports)[^;]*;\s*$\n?", "", idf, flags=re.M)
    return idf + "\nOutput:SQLite,Simple;\n" + "".join(f"Output:Variable,*,{v},Timestep;\n" for v in VARS)


def series(db, name):
    q = ("SELECT rd.Value FROM ReportData rd JOIN ReportDataDictionary d ON rd.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex "
         "JOIN Time t ON rd.TimeIndex=t.TimeIndex WHERE d.Name=? AND (t.WarmupFlag=0 OR t.WarmupFlag IS NULL) "
         "AND t.EnvironmentPeriodIndex=(SELECT MAX(EnvironmentPeriodIndex) FROM Time) ORDER BY rd.TimeIndex")
    return np.array([r[0] for r in db.execute(q, [name])], float)


def visible_fraction(elev_deg, horizon_deg, radius_deg):
    x = np.clip((elev_deg - horizon_deg) / radius_deg, -1.0, 1.0)
    return (np.arccos(-x) + x * np.sqrt(1.0 - x * x)) / math.pi


def main():
    case, epw, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    exe = Path(sys.argv[4]) if len(sys.argv) > 4 else ROOT / "build" / "Products" / "energyplus.exe"
    idf = case.read_text()
    pb = planetary_fields(idf)
    body = pb[1].strip().lower()
    horizon = float(pb[9]) if len(pb) > 9 and pb[9].strip() not in ("", "autocalculate") else 0.0
    rp = re.search(r"^RunPeriod,[^,]*,(\d+),(\d+),(\d+),", idf, re.M)
    month, day, year = int(rp.group(1)), int(rp.group(2)), int(rp.group(3))
    steps = int(re.search(r"^Timestep,(\d+);", idf, re.M).group(1))
    dt = 3600.0 / steps
    loc = epw.read_text().splitlines()[0].split(",")
    lat, lon = float(loc[6]), float(loc[7])

    work = Path(tempfile.mkdtemp(prefix="pwf_export_"))
    try:
        (work / "in.idf").write_text(generator_input(idf))
        subprocess.run([str(exe), "-d", str(work / "out"), "-w", str(epw), str(work / "in.idf")], cwd=work,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        err = (work / "out" / "eplusout.err").read_text(errors="replace")
        if "Completed Successfully" not in err:
            raise SystemExit("generator run failed:\n" + "\n".join(l for l in err.splitlines() if "Fatal" in l or "Severe" in l))
        db = sqlite3.connect(work / "out" / "eplusout.sql")
        s = {v: series(db, v) for v in VARS}
        db.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)

    n = len(s["Site Direct Solar Radiation Rate per Area"])
    assert n % (24 * steps) == 0, n

    def mid(v):  # interval mean of two end-of-step values (first interval: its end value)
        return np.concatenate([v[:1], 0.5 * (v[:-1] + v[1:])])

    alt_end = s["Site Solar Altitude Angle"]
    dni, dhi = mid(s["Site Direct Solar Radiation Rate per Area"]), mid(s["Site Diffuse Solar Radiation Rate per Area"])
    alt, azi = mid(alt_end), s["Site Solar Azimuth Angle"]
    zen = 90.0 - alt
    r_au = s["Site Planetary Sun Distance"]
    vis = np.where(alt > -2.0, visible_fraction(alt, horizon, SUN_RADIUS_1AU / np.where(r_au > 0, r_au, 1.0)), 0.0)
    ghi = np.maximum(dni * np.maximum(np.cos(np.radians(zen)), 0.0) + dhi, 0.0)
    ghi_end = np.maximum(s["Site Direct Solar Radiation Rate per Area"] * np.maximum(np.sin(np.radians(alt_end)), 0.0)
                         + s["Site Diffuse Solar Radiation Rate per Area"], 0.0)
    refl = s["Site Ground Reflected Solar Radiation Rate per Area"]
    alb_default = float(pb[11]) if len(pb) > 11 and pb[11].strip() not in ("", "autocalculate") else (0.12 if body == "moon" else 0.17)
    albedo = np.where(ghi_end > 1.0, refl / np.maximum(ghi_end, 1e-9), np.nan)
    last = alb_default
    for i in range(n):  # night: carry the last daylight albedo (it multiplies zero irradiance)
        if np.isnan(albedo[i]):
            albedo[i] = last
        last = albedo[i]
    albedo = np.clip(albedo, 0.0, 1.0)
    K = 273.15
    vacuum = body == "moon"
    t = dt * np.arange(1, n + 1)
    cols = {
        "time_s": t, "local_time_h": (t / 3600.0) % 24.0, "day_index": np.floor((t - dt) / 86400.0),
        "zenith_deg": zen, "sun_azimuth_deg": azi, "sun_visible": vis, "dni_W_m2": dni, "dhi_W_m2": dhi, "ghi_W_m2": ghi,
        "T_air_K": np.full(n, np.nan) if vacuum else s["Site Outdoor Air Drybulb Temperature"] + K,
        "T_sky_K": s["Site Sky Temperature"] + K, "T_ground_K": s["Site Planetary Ground Surface Temperature"] + K,
        "T_deep_K": s["Site Planetary Deep Ground Temperature"] + K, "ground_albedo": albedo,
        "pressure_Pa": s["Site Planetary Ambient Pressure"], "wind_m_s": s["Site Wind Speed"], "wind_dir_deg": np.zeros(n),
    }
    units = ["s", "h", "-", "deg", "deg", "-", "W/m2", "W/m2", "W/m2", "K", "K", "K", "K", "-", "Pa", "m/s", "deg"]
    if not vacuum:
        cols.update({"L_down_W_m2": s["Site Planetary Downwelling Longwave Radiation"], "Ls_deg": mid(s["Site Planetary Solar Longitude"]),
                     "dust_tau": mid(s["Site Planetary Dust Optical Depth"])})
        units += ["W/m2", "deg", "-"]
    head = {"body": body, "site_name": case.stem, "latitude_deg": f"{lat:.6f}", "longitude_deg": f"{lon:.6f}",
            "start_utc": f"{year:04d}-{month:02d}-{day:02d}T00:00:00", "timestep_s": f"{dt:g}", "n_records": str(n),
            "solar_day_s": f"{MOON_SYNODIC_S if vacuum else MARS_SOL_S:.6f}",
            "gravity_m_s2": "1.62500" if vacuum else "3.72100", "atmosphere": "none" if vacuum else "mars_co2",
            "clock": "earth_utc", "sky_includes_air": "false", "generator": "thermonaut (planetary/tools/export_pwf.py)",
            "units": ",".join(units)}

    def fmt(x):
        return "nan" if np.isnan(x) else f"{x:.6g}"

    with out.open("w", newline="\n") as fh:
        fh.write("# PWF 1.0\n" + "".join(f"# {k}: {v}\n" for k, v in head.items()))
        fh.write(",".join(cols) + "\n")
        arr = np.column_stack(list(cols.values()))
        for row in arr:
            fh.write(",".join(fmt(x) for x in row) + "\n")
    print(f"wrote {out} ({n} records of {dt:g} s, {body})")


if __name__ == "__main__":
    main()
