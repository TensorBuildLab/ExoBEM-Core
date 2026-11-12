"""Build the supplementary material of the Thermonaut manuscript (anonymized for double-anonymous review).

    python planetary/paper/build_supplementary_thermonaut.py  ->  planetary/paper/Thermonaut_supplementary.docx
The machine-readable audit inventory (supplementary file S1) is planetary/paper/data/audit_inventory.csv.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # Thermonaut repository root
sys.path[:0] = [str(HERE), str(HERE / "lib")]

import sections_thermonaut as C  # noqa: E402
from docxkit import Manuscript  # noqa: E402
from factors import FACTORS  # noqa: E402

S, F = C.S, C.F
DISP = C.DISP


def section(m, num, title):
    m.heading(f"S{num}. {title}", 1, numbered=False)
    m.tab_prefix, m.tab_no = f"S{num}.", 0


def s1_audit(m):
    section(m, 1, "Audit inventory and traceability")
    AU = S["audit_inventory"]
    m.para(
        f"The inventory (supplementary file S1, audit_inventory.csv) has one row for each of the {AU['total']} entries of "
        f"the six audit reports: {C.N_FIND} prioritized findings and {C.AU_NOTES} notes without a priority. Columns: id "
        "(area and finding), area, file_line in EnergyPlus v26.2.0, symbol, earth_assumption, effect_off_earth, "
        "proposed_change, priority, disposition, thermonaut_treatment (where and how the current code handles it) and "
        "location_check (whether the cited line was found again in the v26.2.0 source: ok, moved, not_found, n/a). "
        "Dispositions: modified (changed by a hook), refused (the input validator stops the run), avoided (made correct "
        "by a design decision without editing that line), deferred (open; a limitation or roadmap item), harmless (no "
        "effect off-Earth). The tracing pass also found refusals that were documented but not implemented; they were "
        "implemented in M2e, and the affected rows say so in their treatment.")
    rows = [[p] + [str(AU["by_priority"].get(p, {}).get(d, 0)) for d in DISP] + [str(sum(AU["by_priority"].get(p, {}).values()))]
            for p in ("P0", "P1", "P2", "none")]
    m.table(["Priority", *[d.capitalize() for d in DISP], "Total"], rows, "Dispositions by priority.",
            col_widths_cm=[2.6, 2.0, 2.0, 2.0, 2.0, 2.0, 1.6], font_size=8)
    loc = AU["location"]
    m.para(f"Location check: {loc['ok']} ok, {loc['moved']} moved, {loc['not_found']} not found, {loc['n/a']} without a "
           "file and line.")
    with open(HERE / "data" / "audit_inventory.csv", newline="", encoding="utf-8") as fh:
        inv = list(csv.DictReader(fh))
    rows = [[r["id"], r["priority"], r["symbol"][:70], r["thermonaut_treatment"][:260]] for r in inv if r["disposition"] == "deferred"]
    m.table(["Id", "Priority", "Symbol", "Status in Thermonaut M2e"], rows,
            "All deferred rows (open items).", col_widths_cm=[2.0, 1.4, 4.4, 8.2], font_size=7)


def s2_factors(m):
    section(m, 2, "Planetary factors")
    rows, cat = [], None
    for c, fac, earth, moon, mars, core in FACTORS:
        if c != cat:
            rows.append([f"**{c}**", "", "", "", ""])
            cat = c
        rows.append([fac, earth, moon, mars, core])
    m.table(["Factor", "Earth", "Moon", "Mars", "Treatment in Thermonaut"], rows,
            "Factors that distinguish a lunar or Martian habitat from an Earth building, and how Thermonaut treats each. "
            "modelled: physics implemented and verified; input: a parameter with a documented default; enforced or "
            "refused: contradicting input stops the run; neglected: left out, with the reason.",
            col_widths_cm=[2.9, 2.6, 3.4, 3.2, 3.9], font_size=7.0)


def s3_earth(m):
    section(m, 3, "Earth regression per file")
    ER = S["earth_regression"]
    m.para(
        "Each EnergyPlus example file was run with an unmodified EnergyPlus v26.2.0 build and with Thermonaut M2e "
        "(release builds, MSVC 14.44, Windows 11) and every value of the complete output time series (ESO) was compared "
        "(planetary/tools/earth_regression.py).")
    files = list(ER["chicago"])
    rows = []
    for f in files:
        c, p = ER["chicago"][f], ER["phoenix"].get(f, {})
        fmt = lambda d: (f"identical ({d['n_values']:,} values)" if d.get("status") == "identical" else d.get("status", "—"))
        rows.append([f, fmt(c), fmt(p)])
    m.table(["Example file", "Chicago TMY3", "Phoenix TMY3"], rows, "Earth regression results.",
            col_widths_cm=[6.6, 4.7, 4.7], font_size=7.5)
    m.para(f"Upstream unit tests: {C.UT['tests']:,} tests in {C.UT['suites']} suites, all passing.")


def s4_tests(m):
    section(m, 4, "Planetary software tests")
    TS = S["planetary_tests"]
    m.para("planetary/tests/run_planetary_tests.py runs each test end to end and checks for a clean run or the specific "
           "error message expected.")
    rows = [[t["name"], t["description"], "pass" if t["passed"] else "FAIL"] for t in TS["tests"]]
    m.table(["Test", "What is checked", "Result"], rows, f"Planetary tests ({TS['passed']}/{TS['total']} pass).",
            col_widths_cm=[4.0, 10.6, 1.4], font_size=7.5)


def s5_robust(m):
    section(m, 5, "Start-up, spin-up, numerics and convection scope")
    RB, MC = S["robustness"], S["mars_convection"]
    lab = {"base": "Base: minimum warm-up 6 days, CondFD constant 30, 3-min step", "warmup_min1": "Minimum warm-up 1 day",
           "warmup_min20": "Minimum warm-up 20 days", "grid_C10": "CondFD space-discretization constant 10",
           "grid_C90": "CondFD space-discretization constant 90",
           "timestep_30": "Time step 2 min (30 per hour)"}
    rows = [[lab[k], f"{v['window_kWh']:.1f}", f"{v['vs_base_pct']:+.2f}%", f"{v['first_hour_W']:.0f}"] for k, v in RB["startup"].items() if k in lab]
    m.table(["Variant (Mars regolith module, 31 days)", "Cooling, days 16–31 (kWh)", "vs base", "First-hour cooling (W)"], rows,
            "Sensitivity of the corrected start-up to warm-up length, CondFD grid and time step (a step longer than "
            "3 min is not possible with CondFD, which EnergyPlus runs with at least 20 steps per hour).",
            col_widths_cm=[7.6, 3.0, 2.2, 3.2], font_size=7.5)
    sp = RB["spinup"]
    rows = [["Mars, 25 months vs 31 days (final 16 days)", f"{sp['mars_long']['cooling_kWh']:.1f}", f"{sp['mars_short']['cooling_kWh']:.1f}",
             f"{sp['mars_short_vs_long_pct']:+.2f}%"],
            ["Moon, 36 months vs 2 lunations (final lunation)", f"{sp['moon_long']['cooling_kWh']:.1f}", f"{sp['moon_short']['cooling_kWh']:.1f}",
             f"{sp['moon_short_vs_long_pct']:+.2f}%"]]
    m.table(["Comparison", "Long spin-up (kWh)", "Corrected short run (kWh)", "Short vs long"], rows,
            "Corrected start-up against a long spin-up ending on the same date (each run's environment starts at its "
            "own first day).", col_widths_cm=[7.0, 3.0, 3.4, 2.6], font_size=7.5)
    it = RB["kT"]["max_change_per_iteration_K"]
    m.para("Fixed-point iteration of the steady k(T) profile (lunar regolith cover), largest node change per iteration (K): "
           + ", ".join(f"{x:.1e}" for x in it[:8]) + ". The engine uses six iterations.")
    d = RB["depth"]
    m.para("Engine regolith temperatures at the lunar equator (period mean): " +
           ", ".join(f"{float(k):.1f} m: {v:.1f} K" for k, v in d.items()) + "; reference ≈252–256 K near 1 m.")
    m.para(
        f"Mars exterior convection over the 3-min verification run (top facet, {MC['steps']:,} steps): horizontal length "
        f"A/P = {MC['L_horizontal_m']:.2f} m, forced length √A = {MC['L_forced_m']:.2f} m; Ra (1st–99th percentile) "
        f"{MC['Ra_range'][0]:.2e}–{MC['Ra_range'][1]:.2e}; Re {MC['Re_range'][0]:.2e}–{MC['Re_range'][1]:.2e}; Pr "
        f"{MC['Pr_range'][0]:.3f}–{MC['Pr_range'][1]:.3f}; CO2 mean free path {MC['mean_free_path_um'][0]:.1f}–"
        f"{MC['mean_free_path_um'][1]:.1f} µm; Knudsen number ≤ {MC['Knudsen_max']:.1e}.")
    sens = MC["sensitivity"]
    rows = [["Pressure (Pa)"] + [f"{x:g}: {h:.3f}" for x, h in sens["pressure"]],
            ["Wind (m/s)"] + [f"{x:g}: {h:.3f}" for x, h in sens["wind"]],
            ["Surface–air ΔT (K)"] + [f"{x:g}: {h:.3f}" for x, h in sens["dT"]],
            ["Horizontal length (m)"] + [f"{x:.2f}: {h:.3f}" for x, h in sens["L_horizontal"]]]
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    m.table(["Factor varied"] + [""] * (width - 1), rows,
            f"Convection coefficient h (W/(m²K)) of a hot horizontal facet, one factor at a time around 700 Pa, 3.2 m/s, "
            f"ΔT = 20 K (reference {sens['reference_W_m2K']:.3f}).", col_widths_cm=[3.6] + [12.4 / (width - 1)] * (width - 1), font_size=7.5)


def s6_versions(m):
    section(m, 6, "Version history")
    rows = [[v, d] for v, d in S["versions"]]
    m.table(["Patch set", "Content"], rows, "Thermonaut patch sets applied to EnergyPlus v26.2.0 (planetary/tools/apply_hooks_*.py).",
            col_widths_cm=[2.0, 14.0], font_size=7.5)
    m.para("Every patch set is idempotent, asserts each anchor in the stock source, and was followed by the Earth "
           "regression, the unit tests and (from M2e) the planetary tests. M2e adds only input checks: rerunning every "
           "verification case with the final M2e build reproduced the recorded output exactly "
           "(planetary/tools/rerun_cases_check.py). The PV case was re-recorded after M2d changed the CondFD start-up of "
           "its host module; its PV results were unchanged.")


def s7_habitat(m):
    section(m, 7, "Lunar habitat input provenance")
    N, D, A = "NASA document", "Derived from NASA data", "Authors' assumption"
    rows = [
        ["Geometry", "Vertical cylinder, D 6.5 m, H 5.25 m (174 m³), on legs 1.5 m above the regolith", N, "Artemis surface-habitat concepts (Stromgren et al. 2023; Schunk et al. 2021)"],
        ["Outer layer", "Beta cloth, solar absorptance 0.40, emissivity 0.90", N, "Schunk et al. 2022"],
        ["Insulation", "10-layer MLI, effective R = 19.2 m²K/W", D, "Calibrated to NASA's 1550 W night-time heat leak at 293 K"],
        ["Structure, lining", "Aluminium 2219, 4 mm; interior panel 10 mm", A, "Structure type from Schunk et al. 2022; thicknesses assumed"],
        ["Cabin atmosphere", "56.5 kPa, 34% O2", N, "Exploration atmosphere (Anderson et al. 2018)"],
        ["Control band", "20–25 °C, RH 30–60%", N, "NASA-STD-3001"],
        ["Crew", "4 crew; per person sleep 62 W + 26 W latent, awake 91 W + 48 W, exercise 151 W + 258 W", N, "BVAD nominal crew member (Anderson et al. 2018, Table 3-33)"],
        ["Electric power in the shell", "14 kW (daytime design)", D, "NASA habitat sized for 15 kWe including thermal control"],
        ["Power split", "Life support 25%; O2 electrolysis 0.9 kW (22% as heat); fans 0.5 kW; lighting 7 W/m² of deck; rest avionics and equipment", A, "Life-support share from the ISS ratio; others assumed"],
        ["Cold plates", "60% of avionics and 50% of life-support heat removed by cold plates", A, "Assumed"],
        ["Leakage", "0.05% of the cabin gas mass per day", N, "Anderson et al. 2018"],
        ["Airlock", "2 cycles per week; 12 m³ airlock vented from 6.9 kPa", A, "Assumed"],
        ["Internal mass", "Aluminium-equivalent racks, 6 mm, area 2× deck area", A, "Assumed"],
        ["Cabin air velocity", "0.15 m/s (convection model)", A, "Assumed"],
    ]
    m.table(["Input", "Value", "Source type", "Source"], rows, "Inputs of the NASA-informed four-crew lunar habitat.",
            col_widths_cm=[2.6, 6.2, 2.6, 4.6], font_size=7.2)


def s8_pwf(m):
    section(m, 8, "Planetary Weather Format (PWF 1.0)")
    md = (ROOT / "planetary" / "docs" / "weather_format.md").read_text(encoding="utf-8")

    def md_table(after):
        i = md.index(after)
        lines = [ln for ln in md[i:].splitlines()[1:] if ln.strip()]
        lines = lines[next(k for k, ln in enumerate(lines) if ln.startswith("|")):]
        tab = []
        for ln in lines:
            if not ln.startswith("|"):
                break
            cells = [c.strip().replace("`", "") for c in ln.strip("|").split("|")]
            if not set("".join(cells)) <= set("-: "):
                tab.append(cells)
        return tab[0], tab[1:]

    m.para("A PWF file is UTF-8 CSV: comment lines starting with '#' carry key–value header entries, followed by one "
           "column-header line and one record per interval. Solar quantities refer to the middle of each interval, "
           "state quantities to its end; time_s is the end of the interval in seconds from start_utc.")
    h, r = md_table("### Header keys")
    m.table(h, r, "Header keys.", col_widths_cm=[4.4, 2.0, 9.6], font_size=7.5)
    h, r = md_table("### Columns")
    m.table(h, r, "Columns.", col_widths_cm=[3.4, 1.4, 1.6, 9.6], font_size=7.5)
    m.para("Thermonaut reads every required column except zenith_deg and sun_azimuth_deg (it computes the solar position "
           "itself) and rejects a file for another body, with a missing column, unequal spacing, insufficient coverage "
           "of the run period, or a value outside its physical range: irradiance 0–2000 W/m², temperatures 2.7–1000 K "
           "(nan allowed only for T_air_K), albedo 0–1, pressure 0–200 kPa, wind 0–100 m/s, record length > 0.")


def s9_refused(m):
    section(m, 9, "Objects refused in planetary mode")
    rows = [[o, why] for o, why in S["refused"]]
    m.table(["Object type", "Reason"], rows, "Object types that stop a planetary run when present.",
            col_widths_cm=[7.0, 9.0], font_size=7.2)
    m.bullets([
        "Value-based refusals: HeatBalanceAlgorithm other than CTF or CondFD (also per surface); outside convection "
        "SimpleCombined; DElight daylighting; air- or evaporatively cooled Chiller:Electric:EIR, Chiller:Electric, "
        "ConstantCOP, EngineDriven and CombustionTurbine; air-source plant-loop heat pumps; heat-pump water heaters "
        "with outdoor-air inlets; Sandia, Ulleberg dynamic and Sandia-in-Decoupled PV models; Li-ion batteries without "
        "a zone; the CO2 contaminant balance; one time step per hour; water use without a scheduled mains temperature; "
        "a negative horizon elevation.",
        "Design days and sizing: SizingPeriod:*, Sizing:Zone, Sizing:System.",
        "Backstop: a planetary run stops at the start of the next day if any component has registered an outdoor-air node.",
    ])


def s10_tutorial(m):
    section(m, 10, "Worked example")
    m.para("The repository's tutorial (planetary/TUTORIAL.md) builds the engine and runs the lunar habitat. Repository "
           "addresses are withheld for anonymous review.", indent=False)
    steps = [
        ("**1. Build** (Windows, Visual Studio 2022 Build Tools; elsewhere the standard EnergyPlus CMake build):",
         ["git clone <Thermonaut repository>", "cd Thermonaut", "planetary\\tools\\build.bat configure 8"]),
        ("**2. Optionally write a planetary weather file** from the engine's own generator (without one, the engine "
         "generates the environment itself and takes the site from a placeholder EPW):",
         ["python planetary\\tools\\export_pwf.py lunar_habitat.idf placeholder.epw lunar_habitat.pwf"]),
        ("**3. Add the planetary object** to an ordinary input file:",
         ["Site:PlanetaryBody,", "  lunar_habitat, Moon, EarthClock, 2030,   !- name, body, clock, reference year",
          "  autocalculate, 56500, 0.34, 0.15, 5.25, !- gravity, cabin pressure, O2 fraction, cabin air velocity, length",
          "  0.0, autocalculate, autocalculate, autocalculate, autocalculate, 3.0,  !- horizon; regolith; deep depth",
          "  710, Climatology, 0.5, 0, 0, 0, 3.2, 2.0,  !- Mars-only fields", "  lunar_habitat.pwf;   !- planetary weather file"]),
        ("**4. Run** with the weather file (no EPW is needed), or with the generator and the placeholder EPW:",
         ["build\\Products\\energyplus.exe -d out lunar_habitat.idf",
          "build\\Products\\energyplus.exe -d out -w placeholder.epw lunar_habitat_generator.idf"]),
    ]
    for head, lines in steps:
        m.para(head, align="left")
        for ln in lines:
            m.para(ln, align="left", size=8.5, space_after=0)
        m.para("", space_after=4)
    m.para(
        "The rest is standard input: materials, Material:NoMass (MLI) and constructions; BuildingSurface:Detailed with an "
        "Outdoors floor for a habitat on legs; InternalMass; OtherEquipment with latent and lost fractions for crew and "
        "equipment; thermostat, humidistat and ZoneHVAC:IdealLoadsAirSystem; optionally Generator:Photovoltaic with the "
        "one-diode model in Decoupled mode and a battery in the zone. All standard outputs are available, plus Site "
        "Planetary Ground Surface Temperature, Deep Ground Temperature, Ambient Pressure, Downwelling Longwave Radiation, "
        "Sun Distance, Solar Longitude and Dust Optical Depth.", align="left")


def build(m):
    m.para(f"**Supplementary material for: {C_TITLE}**", align="center", size=13, space_after=12)
    for fn in (s1_audit, s2_factors, s3_earth, s4_tests, s5_robust, s6_versions, s7_habitat, s8_pwf, s9_refused, s10_tutorial):
        fn(m)


C_TITLE = "Thermonaut: auditing and adapting the EnergyPlus engine for building energy simulation on the Moon and Mars"


def main():
    m = Manuscript()
    m.set_references({})
    build(m)
    out = HERE / "Thermonaut_supplementary.docx"
    m.save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
