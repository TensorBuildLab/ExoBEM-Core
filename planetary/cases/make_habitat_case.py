"""NASA-informed lunar surface habitat in Thermonaut and in ExoBEM, on the same planetary weather file.

The model is ExoBEM's example lunar_surface_habitat.json (4 crew, 174 m3 vertical cylinder on legs, beta cloth /
MLI / aluminium / panel, 56.5 kPa / 34 % O2 cabin, 20-25 C, RH 30-60 %, life support, electrolysis, fans,
lighting and avionics with cold plates, internal mass).  This script

  1. generates 30 days of the lunar-equator environment at 3-minute steps (PWF),
  2. writes the habitat as an IDF for Thermonaut from the ExoBEM model's surface vertices
     (CTF conduction; crew latent heat as OtherEquipment latent fraction; heat that does not reach the cabin
     air - cold plates and the chemical energy of electrolysis - as the OtherEquipment "lost" fraction;
     humidity held by the ideal loads with a humidistat),
  3. runs ExoBEM on the same weather file (planar layers, no leakage) and stores the reference.

    set EXOBEM_PATH=<ExoBEM checkout>
    python planetary/cases/make_habitat_case.py
    energyplus -d out planetary/cases/lunar_habitat/lunar_habitat.idf      (no EPW needed)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
EXOBEM = Path(os.environ.get("EXOBEM_PATH", HERE.parents[2] / "ExoBEM"))
sys.path.insert(0, str(EXOBEM))

from exobem import simulate  # noqa: E402
from exobem.io import build_model  # noqa: E402
from exobem.materials import NoMassMaterial  # noqa: E402
from exobem.weather import generate, read_pwf, write_pwf  # noqa: E402

CASE = "lunar_habitat"
D = HERE / CASE
STEPS_PER_HOUR = 20
DT = 3600.0 / STEPS_PER_HOUR
START = dt.datetime(2030, 1, 1)
DAYS = 30


def idf_material(m):
    if isinstance(m, NoMassMaterial):
        return f"Material:NoMass,{m.name},{m.roughness},{m.resistance},{m.thermal_emissivity},{m.solar_absorptance},{m.solar_absorptance};"
    return (f"Material,{m.name},{m.roughness},{m.thickness},{m.conductivity},{m.density},{m.specific_heat},"
            f"{m.thermal_emissivity},{m.solar_absorptance},{m.solar_absorptance};")


def compact_hourly(name, values):
    v = list(values) if not np.isscalar(values) else [float(values)] * 24
    parts = [f"Schedule:Compact,{name},Any,Through: 12/31,For: AllDays"]
    for h, x in enumerate(v):
        parts.append(f"Until: {h + 1:02d}:00,{x:.6g}")
    return ",".join(parts) + ";"


def write_idf(model, path):
    z = model.zone
    L = []
    a = L.append
    a("Version,26.2;")
    a("SimulationControl,No,No,No,No,Yes,No,1;")
    a(f"Building,{CASE},0.0,Suburbs,0.04,0.4,FullExterior,25,6;")
    a(f"Timestep,{STEPS_PER_HOUR};")
    a("HeatBalanceAlgorithm,ConductionTransferFunction,200;")
    a("SurfaceConvectionAlgorithm:Inside,TARP;")
    a("SurfaceConvectionAlgorithm:Outside,DOE-2;")
    a("ShadowCalculation,PolygonClipping,Periodic,1,15000;")
    a(f"Site:PlanetaryBody,{CASE},Moon,EarthClock,{START.year},autocalculate,{z.cabin_pressure_Pa:.0f},{z.cabin_o2_fraction},"
      f"{z.cabin_air_velocity},5.25,0.0,autocalculate,autocalculate,autocalculate,autocalculate,3.0,710,Climatology,0.5,0,0,0,"
      f"3.2,2.0,{CASE}.pwf;")
    end = START + dt.timedelta(days=DAYS - 1)
    a(f"RunPeriod,{CASE},{START.month},{START.day},{START.year},{end.month},{end.day},{end.year},Tuesday,No,No,No,Yes,Yes;")
    a("GlobalGeometryRules,UpperLeftCorner,Counterclockwise,World;")
    mats = {}
    for con in model.constructions.values():
        for m in con.layers:
            mats[m.name] = m
    L.extend(idf_material(m) for m in mats.values())
    for con in model.constructions.values():
        a(f"Construction,{con.name}," + ",".join(m.name for m in con.layers) + ";")
    a(f"Zone,{z.name},0,0,0,0,1,1,autocalculate,autocalculate;")
    for s in z.geometry.surfaces:
        kind = "Roof" if s.tilt < 1 else ("Floor" if s.tilt > 179 else "Wall")
        # EnergyPlus vertex order: counter-clockwise seen from outside, starting at the upper-left corner
        v = s.vertices
        verts = ",".join(f"{x:.6f},{y:.6f},{zz:.6f}" for (x, y, zz) in v)
        a(f"BuildingSurface:Detailed,{s.name},{kind},{s.construction},{z.name},,Outdoors,,SunExposed,WindExposed,autocalculate,"
          f"{len(v)},{verts};")
    for im in z.internal_mass:
        a(f"InternalMass,{im.name},{im.construction},{z.name},,{im.area_m2};")
    a("ScheduleTypeLimits,Any,,,Continuous;")
    a("Schedule:Constant,AlwaysOn,Any,1.0;")
    a(f"Schedule:Constant,HeatSP,Any,{z.thermostat.heating_setpoint_C};")
    a(f"Schedule:Constant,CoolSP,Any,{z.thermostat.cooling_setpoint_C};")
    a("Schedule:Constant,CtrlType,Any,4;")
    a(f"Schedule:Constant,RHmax,Any,{100 * z.rh_max};")
    a(f"Schedule:Constant,RHmin,Any,{100 * z.rh_min};")
    for g in z.gains:
        a(compact_hourly(f"{g.name}_sched", g.schedule))
        if g.latent_W > 0:
            a(f"OtherEquipment,{g.name},None,{z.name},{g.name}_sched,EquipmentLevel,{g.latent_W},,,1.0,0.0,0.0;")
            continue
        to_zone = g.heat_fraction * (1.0 - g.coldplate_fraction)
        a(f"OtherEquipment,{g.name},None,{z.name},{g.name}_sched,EquipmentLevel,{g.power_W},,,0.0,"
          f"{to_zone * g.radiant_fraction:.6f},{1.0 - to_zone:.6f};")
    a(f"ZoneControl:Thermostat,{z.name} Thermostat,{z.name},CtrlType,ThermostatSetpoint:DualSetpoint,DualSP;")
    a("ThermostatSetpoint:DualSetpoint,DualSP,HeatSP,CoolSP;")
    a(f"ZoneControl:Humidistat,{z.name} Humidistat,{z.name},RHmin,RHmax;")
    zn = z.name
    a(f"ZoneHVAC:IdealLoadsAirSystem,{zn} Ideal,,{zn} Supply,,,50,13,0.015,0.002,NoLimit,,,NoLimit,,,,,Humidistat,,Humidistat;")
    a(f"ZoneHVAC:EquipmentList,{zn} Equipment,SequentialLoad,ZoneHVAC:IdealLoadsAirSystem,{zn} Ideal,1,1,,;")
    a(f"ZoneHVAC:EquipmentConnections,{zn},{zn} Equipment,{zn} Supply,,{zn} Air Node,{zn} Return;")
    for var in ["Zone Mean Air Temperature", "Zone Air Relative Humidity", "Zone Ideal Loads Zone Sensible Cooling Rate",
                "Zone Ideal Loads Zone Sensible Heating Rate", "Zone Ideal Loads Zone Latent Cooling Rate",
                "Zone Ideal Loads Zone Latent Heating Rate", "Surface Outside Face Temperature", "Surface Inside Face Temperature",
                "Site Planetary Ground Surface Temperature", "Site Direct Solar Radiation Rate per Area"]:
        a(f"Output:Variable,*,{var},Hourly;")
    a("Output:SQLite,SimpleAndTabular;")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    D.mkdir(exist_ok=True)
    env = generate("moon", 0.674, 23.473, START, DAYS + 1, DT, site_name="Mare Tranquillitatis")
    write_pwf(env, D / f"{CASE}.pwf", site_name="Mare Tranquillitatis (lunar equator)",
              generator="exobem (planetary/cases/make_habitat_case.py)")
    cfg = json.loads((EXOBEM / "examples" / "lunar_surface_habitat.json").read_text())
    cfg["simulation"]["timestep_s"] = DT
    model = build_model(cfg)
    model.curvature = "off"                       # planar layers, as in the engine
    model.zone.leakage_kg_per_day = 0.0           # gas losses are not modelled in the engine (< 1 W)
    model.zone.airlock_cycles_per_day = 0.0
    write_idf(model, D / f"{CASE}.idf")
    print("wrote", D / f"{CASE}.idf")
    env = read_pwf(D / f"{CASE}.pwf")
    n = int(DAYS * 86400 / DT)
    for k in ("time_s", "jd_utc", "zenith", "sun_azimuth", "dni", "dhi", "ghi", "sun_visible", "T_air", "T_sky", "T_ground",
              "T_deep", "wind_speed", "wind_dir", "pressure", "ground_albedo", "local_time_h", "day_index"):
        setattr(env, k, getattr(env, k)[:n])
    res = simulate(model, env)
    print("ExoBEM:", {k: round(v, 2) for k, v in res.summary().items() if isinstance(v, float)})
    np.savez_compressed(D / "python_ref.npz", time_s=res.time_s, Q_cooling_W=res.Q_cooling_W, Q_heating_W=res.Q_heating_W,
                        Q_latent_W=res.Q_latent_W, rh=res.rh_zone, T_zone_C=res.T_zone_C, T_inside_C=res.T_inside_C,
                        T_outside_C=res.T_outside_C, names=np.array(res.surface_names), T_ground=env.T_ground)


if __name__ == "__main__":
    main()
