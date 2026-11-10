"""Generate ExoBEM-Core verification cases and the matching Python ExoBEM reference runs.

For each case this writes, under planetary/cases/<case>/:
  * <case>.idf      - input for ExoBEM-Core (Site:PlanetaryBody, CondFD, ideal loads)
  * placeholder.epw - calendar/location only (all weather values are replaced in planetary mode)
  * python_ref.npz  - the same habitat simulated with the Python reference model ExoBEM

The habitat is the ExoBEM case-study module (horizontal cylinder r = 3 m, L = 10 m, 16 facets, regolith
cover, ideal loads 18/27 C), with constant internal gains so that both programs see identical inputs.

Usage:  python planetary/cases/make_cases.py [--no-python]
"""
from __future__ import annotations

import argparse
import os
import datetime as dt
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
EXOBEM = Path(os.environ.get("EXOBEM_PATH", HERE.parents[2] / "ExoBEM"))  # Python ExoBEM checkout
sys.path.insert(0, str(EXOBEM))

from exobem import simulate  # noqa: E402
from exobem.cases import lunar_habitat, mars_habitat  # noqa: E402
from exobem.weather import write_pwf  # noqa: E402
from exobem.environment.sites import moon_site, mars_site  # noqa: E402
from exobem.materials import Material, NoMassMaterial, hayne_specific_heat  # noqa: E402
from exobem.model import InternalGain  # noqa: E402

STEPS_PER_HOUR = 20
DT = 3600.0 / STEPS_PER_HOUR
GAINS = [("crew", 4 * 85.1, 0.5), ("equipment", 2500.0, 0.3), ("lighting", 400.0, 0.4)]

CASES = {
    "moon_equator": dict(body="Moon", lat=0.674, lon=23.473, days=59, start=dt.datetime(2030, 1, 1)),
    "mars_jezero": dict(body="Mars", lat=18.44, lon=77.45, days=31, start=dt.datetime(2030, 1, 1)),
}


# ------------------------------------------------------------------------------------------------ EPW
def placeholder_epw(path, name, lat, lon, year):
    """A benign EPW that only carries the location and the calendar."""
    head = [
        f"LOCATION,{name},-,-,ExoBEM-Core placeholder,000000,{lat:.4f},{lon:.4f},{round(lon / 15.0):.1f},0.0",
        "DESIGN CONDITIONS,0", "TYPICAL/EXTREME PERIODS,0",
        "GROUND TEMPERATURES,0", "HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0",
        "COMMENTS 1,Placeholder for ExoBEM-Core planetary mode: every weather value is replaced internally",
        "COMMENTS 2,",
        "DATA PERIODS,1,1,Data,Sunday, 1/ 1,12/31",
    ]
    rows = []
    t = dt.datetime(year, 1, 1)
    for h in range(8760):
        d = t + dt.timedelta(hours=h)
        rows.append(f"{year},{d.month},{d.day},{d.hour + 1},60,-,20.0,5.0,40,101325,0,0,300,0,0,0,0,0,0,0,"
                    "180,0.0,0,0,9999,77777,9,999999999,0,0.0,0,88,0.000,0.0,0.0")
    path.write_text("\n".join(head + rows) + "\n", encoding="latin-1")


# ------------------------------------------------------------------------------------------------ geometry
def cylinder_surfaces(radius=3.0, length=10.0, n=16):
    """Vertices of the ExoBEM horizontal cylinder (axis east-west), counter-clockwise from outside."""
    def p(phi):  # cross-section point, phi from the top, positive toward south (-y)
        return (-radius * math.sin(math.radians(phi)), radius * (1 + math.cos(math.radians(phi))))
    surfs = []
    for i in range(n):
        a0, a1 = i * 360.0 / n, (i + 1) * 360.0 / n
        theta = (i + 0.5) * 360.0 / n
        tilt = theta if theta <= 180 else 360 - theta
        (y0, z0), (y1, z1) = p(a0), p(a1)
        verts = [(0.0, y0, z0), (0.0, y1, z1), (length, y1, z1), (length, y0, z0)]
        surfs.append(dict(name=f"shell_{i:02d}", verts=verts, ground=tilt > 150))
    ring = [p(i * 360.0 / n) for i in range(n)]
    surfs.append(dict(name="end_a", verts=[(length, y, z) for (y, z) in ring], ground=False))
    surfs.append(dict(name="end_b", verts=[(0.0, y, z) for (y, z) in ring], ground=False))
    for s in surfs:  # orient so the normal points away from the axis (outward)
        v = np.array(s["verts"])
        nrm = np.cross(v[1] - v[0], v[2] - v[0])
        c = v.mean(axis=0) - np.array([length / 2, 0.0, radius])
        if np.dot(nrm, c) < 0:
            s["verts"] = s["verts"][::-1]
    return surfs


# ------------------------------------------------------------------------------------------------ IDF
def idf_material(m) -> list[str]:
    out = []
    if isinstance(m, NoMassMaterial):
        out.append(f"Material:NoMass,{m.name},{m.roughness},{m.resistance},{m.thermal_emissivity},{m.solar_absorptance},"
                   f"{m.solar_absorptance};")
        return out
    cp_ref = m.specific_heat
    if m.cp_of_T is not None:
        T = np.linspace(-200.0, 160.0, 13)
        cp_ref = float(np.min(hayne_specific_heat(T + 273.15)))
    out.append(f"Material,{m.name},{m.roughness},{m.thickness},{m.conductivity},{m.density},{cp_ref:.3f},"
               f"{m.thermal_emissivity},{m.solar_absorptance},{m.solar_absorptance};")
    if m.k_of_T is not None:
        T = np.linspace(-200.0, 160.0, 10)
        pairs = ",".join(f"{t:.1f},{float(m.k_of_T(t + 273.15)):.6e}" for t in T)
        out.append(f"MaterialProperty:VariableThermalConductivity,{m.name},{pairs};")
    if m.cp_of_T is not None:
        T = np.linspace(-200.0, 160.0, 13)
        Tf = np.linspace(-200.0, 160.0, 2001)
        h = np.concatenate([[0.0], np.cumsum(0.5 * (m.cp_of_T(Tf[1:] + 273.15) + m.cp_of_T(Tf[:-1] + 273.15)) * np.diff(Tf))])
        hh = np.interp(T, Tf, h)
        pairs = ",".join(f"{t:.1f},{e:.2f}" for t, e in zip(T, hh))
        out.append(f"MaterialProperty:PhaseChange,{m.name},0.0,{pairs};")
    return out


def write_idf(path, case, model, epw_year):
    c = CASES[case]
    L = []
    a = L.append
    a("Version,26.2;")
    a("SimulationControl,No,No,No,No,Yes,No,1;")
    a(f"Building,{case},0.0,Suburbs,0.04,0.4,FullExterior,25,6;")
    a(f"Timestep,{STEPS_PER_HOUR};")
    a("HeatBalanceAlgorithm,ConductionFiniteDifference,200;")
    a("HeatBalanceSettings:ConductionFiniteDifference,FullyImplicitFirstOrder,30,1.0,0.002;")
    a("SurfaceConvectionAlgorithm:Inside,TARP;")
    a("SurfaceConvectionAlgorithm:Outside,DOE-2;")
    a("ShadowCalculation,PolygonClipping,Periodic,1,15000;")
    a(f"Site:PlanetaryBody,{case},{c['body']},EarthClock,{epw_year},autocalculate,70300,0.265,0.15,6.0,0.0,"
      "autocalculate,autocalculate,autocalculate,autocalculate,3.0;")
    end = c["start"] + dt.timedelta(days=c["days"] - 1)
    a(f"RunPeriod,{case},1,1,{epw_year},{end.month},{end.day},{epw_year},Tuesday,No,No,No,Yes,Yes;")
    a("GlobalGeometryRules,UpperLeftCorner,Counterclockwise,World;")
    # materials and constructions. CondFD cannot resolve the thin, highly conductive aluminium shell
    # (stock check: thickness < sqrt(3 alpha dt)); its resistance is dropped and its heat capacity is
    # added to the interior panel it is bonded to (the aluminium is isothermal to within ~0.01 K).
    al = next(m for con in model.constructions.values() for m in con.layers if m.name.startswith("aluminum"))
    mats, cons_layers = {}, {}
    for con in model.constructions.values():
        names = []
        for m in con.layers:
            if m is al or m.name == al.name:
                continue  # R = 3e-5 m2K/W is negligible (and below the 0.001 input minimum)
            elif m.name.startswith("interior_panel"):
                extra = al.thickness * al.density * al.specific_heat
                rho = m.density + extra / (m.thickness * m.specific_heat)
                m = Material(m.name + "_with_al", m.thickness, m.conductivity, rho, m.specific_heat,
                             m.solar_absorptance, m.thermal_emissivity, m.roughness)
            mats[m.name] = m
            names.append(m.name)
        cons_layers[con.name] = names
    for m in mats.values():
        L.extend(idf_material(m))
    for cname, names in cons_layers.items():
        a(f"Construction,{cname}," + ",".join(names) + ";")
    a(f"Zone,{model.zone.name},0,0,0,0,1,1,autocalculate,autocalculate;")
    for s in cylinder_surfaces():
        cons = "floor" if s["ground"] else ("end" if s["name"].startswith("end") else "shell")
        kind = "Floor" if s["ground"] else "Wall"
        obc = "Ground" if s["ground"] else "Outdoors"
        sun = "NoSun" if s["ground"] else "SunExposed"
        wind = "NoWind" if s["ground"] else "WindExposed"
        verts = ",".join(f"{x:.6f},{y:.6f},{z:.6f}" for (x, y, z) in s["verts"])
        a(f"BuildingSurface:Detailed,{s['name']},{kind},{cons},{model.zone.name},,{obc},,{sun},{wind},autocalculate,"
          f"{len(s['verts'])},{verts};")
    a("ScheduleTypeLimits,Any,,,Continuous;")
    a("Schedule:Constant,AlwaysOn,Any,1.0;")
    a("Schedule:Constant,HeatSP,Any,18.0;")
    a("Schedule:Constant,CoolSP,Any,27.0;")
    a("Schedule:Constant,CtrlType,Any,4;")
    for name, W, rad in GAINS:
        a(f"OtherEquipment,{name},None,{model.zone.name},AlwaysOn,EquipmentLevel,{W},,,0.0,{rad},0.0;")
    a(f"ZoneControl:Thermostat,{model.zone.name} Thermostat,{model.zone.name},CtrlType,ThermostatSetpoint:DualSetpoint,DualSP;")
    a("ThermostatSetpoint:DualSetpoint,DualSP,HeatSP,CoolSP;")
    zn = model.zone.name
    a(f"ZoneHVAC:IdealLoadsAirSystem,{zn} Ideal,,{zn} Supply,,,50,13,0.015,0.009,NoLimit,,,NoLimit,,,,,None,,None;")
    a(f"ZoneHVAC:EquipmentList,{zn} Equipment,SequentialLoad,ZoneHVAC:IdealLoadsAirSystem,{zn} Ideal,1,1,,;")
    a(f"ZoneHVAC:EquipmentConnections,{zn},{zn} Equipment,{zn} Supply,,{zn} Air Node,{zn} Return;")
    for v in ["Zone Mean Air Temperature", "Zone Ideal Loads Zone Sensible Heating Rate", "Zone Ideal Loads Zone Sensible Cooling Rate",
              "Surface Outside Face Temperature", "Surface Inside Face Temperature", "Surface Outside Face Convection Heat Transfer Coefficient",
              "Surface Inside Face Convection Heat Transfer Coefficient", "Surface Outside Face Incident Solar Radiation Rate per Area",
              "Site Direct Solar Radiation Rate per Area", "Site Diffuse Solar Radiation Rate per Area", "Site Sky Temperature",
              "Site Outdoor Air Drybulb Temperature", "Site Planetary Ground Surface Temperature", "Site Planetary Deep Ground Temperature",
              "Site Planetary Ambient Pressure", "Site Planetary Downwelling Longwave Radiation", "Site Planetary Dust Optical Depth",
              "Site Solar Altitude Angle", "Site Solar Azimuth Angle"]:
        a(f"Output:Variable,*,{v},Hourly;")
    a("Output:SQLite,SimpleAndTabular;")
    a("Output:Diagnostics,DisplayExtraWarnings;")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


# ------------------------------------------------------------------------------------------------ Python reference
def python_reference(case, model):
    c = CASES[case]
    n_days = c["days"]
    if c["body"] == "Moon":
        env = moon_site(c["lat"], c["lon"], c["start"], n_days, dt=DT)
    else:
        env = mars_site(c["lat"], c["lon"], c["start"], n_days * 86400.0 / 88775.244147, dt=DT)
    model.zone.gains = [InternalGain(nm, W, rad, 0.0, [1.0] * 24) for nm, W, rad in GAINS]
    model.zone.leakage_kg_per_day = 0.0
    model.thermal_control = None
    model.curvature = "off"       # planar layers, as in the EnergyPlus engine (like-for-like comparison)
    res = simulate(model, env)
    # the same environment as a planetary weather file, for the ExoBEM-Core run in PWF mode
    env.extra["start_utc"] = c["start"]
    write_pwf(env, HERE / case / f"{case}.pwf", site_name=case, generator="exobem (planetary/cases/make_cases.py)")
    return res, env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-python", action="store_true")
    ap.add_argument("cases", nargs="*", default=list(CASES))
    args = ap.parse_args()
    for case in args.cases:
        c = CASES[case]
        d = HERE / case
        d.mkdir(exist_ok=True)
        model = lunar_habitat(dt=DT) if c["body"] == "Moon" else mars_habitat(dt=DT)
        placeholder_epw(d / "placeholder.epw", case, c["lat"], c["lon"], c["start"].year)
        write_idf(d / f"{case}.idf", case, model, c["start"].year)
        print("wrote", d / f"{case}.idf")
        # PWF variant: the engine reads the environment from <case>.pwf and needs no EPW
        txt = (d / f"{case}.idf").read_text(encoding="utf-8")
        assert txt.count(",3.0;\n") == 1
        (d / f"{case}_pwf.idf").write_text(txt.replace(",3.0;\n", f",3.0,710,Climatology,0.5,0,0,0,3.2,2.0,{case}.pwf;\n"),
                                          encoding="utf-8")
        if not args.no_python:
            res, env = python_reference(case, model)
            np.savez_compressed(d / "python_ref.npz", time_s=res.time_s, T_zone_C=res.T_zone_C, Q_heating_W=res.Q_heating_W,
                                Q_cooling_W=res.Q_cooling_W, T_outside_C=res.T_outside_C, T_inside_C=res.T_inside_C,
                                h_conv_in=res.h_conv_in, h_conv_out=res.h_conv_out, names=np.array(res.surface_names),
                                T_ground=env.T_ground, T_deep=env.T_deep, T_sky=env.T_sky, dni=env.dni, dhi=env.dhi,
                                T_air=env.T_air, pressure=env.pressure, zenith=env.zenith)
            print(case, "python:", res.summary())


if __name__ == "__main__":
    main()
