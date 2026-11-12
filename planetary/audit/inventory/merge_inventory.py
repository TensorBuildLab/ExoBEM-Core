"""Merge the per-area audit inventories into one file and count dispositions (the traceability matrix).

Each row is one finding of the six audit reports (planetary/audit/*.md), re-located in the v26.2.0 source
(location_check: ok / moved / not_found / n/a) and given a disposition from the actual Thermonaut code:
  modified  - changed by a hook (planetary/tools/apply_hooks_*.py)
  refused   - the input validator stops the run if the object is present
  avoided   - made correct by a design decision (Earth clock, OutBaroPress = cabin, ...) without editing that line
  deferred  - still open; listed as a limitation or roadmap item
  harmless  - no effect on results off-Earth

    python planetary/audit/inventory/merge_inventory.py  ->  audit_inventory.csv, audit_inventory_summary.json
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARTS = ["area01_02.csv", "area03_04.csv", "area05_06.csv"]
DISP = ["modified", "refused", "avoided", "deferred", "harmless"]


M2E = "M2e (after the traceability pass): "
WIN = (M2E + "windows (FenestrationSurface:Detailed, Window, GlazedDoor and interzone variants) are refused off-Earth; "
       "window support with vacuum-compatible solvers is planned for M3.")
# Gaps that the traceability pass exposed and M2e closed (planetary/tools/apply_hooks_m2e.py; tests in
# planetary/tests/run_planetary_tests.py).  (part, id) -> (new disposition or None to keep, note appended to the treatment)
UPDATES = {
    ("area01_02", "T23"): (None, M2E + "one time step per hour is refused off-Earth, which removes the mid-hour/end-of-step mismatch."),
    ("area01_02", "S09"): (None, M2E + "one time step per hour is refused off-Earth."),
    ("area01_02", "T25"): ("refused", M2E + "ground heat exchangers, PipingSystem:Underground:Domain, Pipe:Underground, Site:GroundDomain and F/C-factor constructions are refused."),
    ("area01_02", "T30"): ("refused", M2E + "water-use and water-heater objects require Site:WaterMainsTemperature with a schedule."),
    ("area01_02", "S18"): ("refused", M2E + "Sandia PV is refused in every mode; PipingSystem:Underground:Domain is refused."),
    ("area01_02", "S32"): ("refused", M2E + "SurfaceConvectionAlgorithm:Outside SimpleCombined and SimpleCombined convection coefficients are refused."),
    ("area01_02", "S33"): ("refused", M2E + "EcoRoof, PVT, transpired, flat-plate and ICS collectors and pond and surface ground heat exchangers are refused."),
    ("area01_02", "S37"): ("refused", M2E + "Daylighting:Controls with the DElight method is refused."),
    ("area03_04", "ZHB-04"): ("refused", M2E + "ZoneAirContaminantBalance with CO2 is refused off-Earth."),
    ("area03_04", "S15"): ("refused", M2E + "SurfaceControl:MovableInsulation is refused."),
    ("area03_04", "G02"): ("refused", M2E + "Construction:FfactorGroundFloor and :CfactorUndergroundWall are refused."),
    ("area03_04", "G04"): ("refused", M2E + "Site:GroundDomain:Slab and :Basement are refused."),
    ("area03_04", "M03"): (None, M2E + "per-surface HAMT (SurfaceProperty:HeatTransferAlgorithm, :Construction, :SurfaceList) is refused."),
    ("area03_04", "PRS-07"): (None, M2E + "air-source HeatPump:PlantLoop:EIR, HeatPump:AirToWater and air-cooled refrigeration condensers are refused; "
                                      "any auto-registered outdoor-air node stops a planetary run (backstop)."),
    ("area05_06", "H13"): (None, M2E + "ZoneHVAC:OutdoorAirUnit, UnitVentilator, VentilatedSlab and EnergyRecoveryVentilator are refused."),
    ("area05_06", "H14"): (None, M2E + "backstop added: a planetary run stops if any outdoor-air node exists."),
    ("area05_06", "H15"): (None, M2E + "TwoStageWithHumidityControlMode and SingleSpeed:ThermalStorage DX coils are refused."),
    ("area05_06", "H18"): (None, M2E + "ZoneHVAC:HybridUnitaryHVAC is refused."),
    ("area05_06", "H19"): (None, M2E + "VRF FluidTemperatureControl(:HR) units are refused."),
    ("area05_06", "H25"): (None, M2E + "air- and evaporatively cooled condensers of all five chiller types are refused; water-cooled chillers are allowed."),
    ("area05_06", "H26"): ("refused", M2E + "air-source HeatPump:PlantLoop:EIR and HeatPump:AirToWater(*) are refused."),
    ("area05_06", "H27"): ("refused", M2E + "air-cooled and evaporative refrigeration condensers and gas coolers are refused."),
    ("area05_06", "H28"): (None, M2E + "heat-pump water heaters are allowed only with Inlet Air Configuration = ZoneAirOnly."),
    ("area05_06", "H29"): (None, M2E + "Pipe:Underground is refused."),
    ("area05_06", "H30"): ("refused", M2E + "GroundHeatExchanger:Surface and :Pond are refused."),
    ("area05_06", "H34"): ("refused", M2E + "water-use and water-heater objects require a scheduled mains temperature."),
    ("area05_06", "H37"): (None, M2E + "Sandia PV is refused in every mode."),
    ("area05_06", "H46"): (None, M2E + "Generator:MicroCHP is refused."),
    ("area05_06", "H48"): ("refused", M2E + "PVT, UnglazedTranspired, FlatPlate:Water and ICS collectors are refused."),
}


def main():
    rows = []
    for p in PARTS:
        with open(HERE / p, newline="", encoding="utf-8") as fh:
            part = list(csv.DictReader(fh))
        for r in part:
            key = (p[:-4], r["id"])
            if key in UPDATES:
                disp, note = UPDATES[key]
                if disp:
                    r["disposition"] = disp
                r["thermonaut_treatment"] = r["thermonaut_treatment"].rstrip() + " " + note
            elif p.startswith("area05_06") and r["id"].startswith("W") and r["disposition"].strip() == "deferred":
                r["disposition"] = "refused"
                r["thermonaut_treatment"] = r["thermonaut_treatment"].rstrip() + " " + WIN
        rows += part
    fields = list(rows[0].keys())
    for r in rows:
        r["id"] = f"A{r['area'].strip().zfill(2)}-{r['id']}"   # ids are unique only within an area
        r["area"] = r["area"].strip().zfill(2)
        r["disposition"] = r["disposition"].strip().lower()
        r["priority"] = r["priority"].strip() if r["priority"].strip() in ("P0", "P1", "P2") else "none"
        assert r["disposition"] in DISP, (r["id"], r["disposition"])
    with open(HERE / "audit_inventory.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    by_area, by_pri = defaultdict(Counter), defaultdict(Counter)
    for r in rows:
        by_area[r["area"]][r["disposition"]] += 1
        by_pri[r["priority"]][r["disposition"]] += 1
    loc = Counter(r["location_check"].strip().lower() for r in rows)
    out = dict(total=len(rows),
               by_disposition={d: sum(r["disposition"] == d for r in rows) for d in DISP},
               by_area={a: {d: by_area[a][d] for d in DISP} for a in sorted(by_area)},
               by_priority={p: {d: by_pri[p][d] for d in DISP} for p in sorted(by_pri)},
               location={k: loc.get(k, 0) for k in ("ok", "moved", "not_found", "n/a")},
               open_P0=[r["id"] for r in rows if r["priority"] == "P0" and r["disposition"] == "deferred"])
    (HERE / "audit_inventory_summary.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
