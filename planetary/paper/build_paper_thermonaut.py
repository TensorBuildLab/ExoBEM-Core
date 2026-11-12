"""Build the Thermonaut manuscript for the Journal of Building Performance Simulation (anonymized for double-anonymous
review; the title page, with authors and statements, is built by build_submission_thermonaut.py).

    python planetary/paper/extract_thermonaut_data.py      (needs the verification runs)
    python planetary/paper/build_figures_thermonaut.py
    python planetary/paper/build_paper_thermonaut.py   ->  planetary/paper/Thermonaut_manuscript.docx
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # Thermonaut repository root
sys.path[:0] = [str(HERE), str(HERE / "lib")]

import sections_thermonaut as C  # noqa: E402
from docxkit import build_two_pass  # noqa: E402
from refs import REFS  # noqa: E402
from sections_thermonaut import (AU, DIFF, HZ, MS, N_EARTH, N_FIND, RT_MAX, TS, UT)  # noqa: E402

TITLE = "Thermonaut: auditing and adapting the EnergyPlus engine for building energy simulation on the Moon and Mars"
KEYWORDS = ["EnergyPlus", "building performance simulation", "lunar habitat", "Mars habitat", "software verification",
            "code audit"]



def abstract_text():
    hm, hr = HZ["moon_equator"], HZ["mars_jezero"]
    return (
        "Building energy simulation engines encode the Earth in many places: in the hour and the motion of the Sun, in "
        "one air pressure shared by zone and outdoors, and in convection, sky and ground models that assume an "
        "atmosphere. This paper presents Thermonaut, a research fork of EnergyPlus v26.2 with a planetary mode for "
        f"sealed lunar and Martian habitats. A traced audit recorded {N_FIND} Earth-specific assumptions. The planetary "
        f"mode adds {DIFF['insertions']:,} lines that move the Sun at the body's rate, separate cabin from ambient "
        "pressure, apply vacuum, thin-CO2 and cabin-gas boundaries, start regolith-covered walls consistently and refuse "
        "objects that need outdoor air. Earth results stay bit-for-bit identical for the tested files in two climates. "
        f"Off-Earth, the Sun agrees with JPL Horizons within {max(hm['rmse_all_deg'], hr['rmse_all_deg']):.1f}°, the "
        "regolith with Diviner data, the Martian sky with rover infrared data and the boundaries with closed-form "
        "balances. Validation against thermal-vacuum tests remains necessary.")


def build(m):
    m.para(f"**{TITLE}**", align="center", size=15, space_after=14)
    m.heading("Abstract", numbered=False)
    ab = abstract_text()
    n = len(re.findall(r"\S+", ab))
    assert n <= 150, n
    m.para(ab, space_after=6)
    m.para("**Keywords:** " + "; ".join(KEYWORDS), align="left")

    # ======================================================================= 1 introduction
    m.heading("Introduction", label="intro")
    m.para(
        "Crewed surface habitats on the Moon and Mars will be buildings in a literal sense: enclosed, occupied volumes "
        "whose heating, cooling and power systems must be sized for a climate, a schedule and an envelope "
        "[@Schunk2021;Schunk2022]. Building performance simulation answers these questions on Earth, and EnergyPlus is "
        "its most widely used open-source engine, with a heat-balance formulation tested against analytical, "
        "comparative and empirical benchmarks for two decades [@Crawley2001;Strand2001;EPlus262;ASHRAE140;Judkoff1995]. "
        "A planetary habitat violates assumptions built into such engines: the Moon's day lasts 29.5 Earth days and it "
        "has no atmosphere; Mars has an 88,775-second sol and a 600–800 Pa CO2 atmosphere; and the cabin air is at a "
        "pressure unrelated to the outdoors [@Hayne2017;Allison2000;Anderson2018].")
    m.para(
        "One route is to write a new, compact model of the planetary heat balance [@Ross2022]; it is quick to build "
        "and easy to verify but gives up most of what a full engine offers. This paper takes the other route and "
        "modifies the engine. Its subject is less the planetary physics, whose models are established, than how to find "
        "and change every Earth assumption in a large production engine without disturbing it on Earth, and how to "
        "verify such a change.")
    m.para(
        "The paper makes four contributions. (i) A protocol-based, line-level audit of Earth-specific assumptions in "
        "EnergyPlus v26.2, with every finding traced to its disposition in the code. (ii) The design of a planetary mode "
        "in a fork named Thermonaut, built on three rules that keep Earth results identical, with an explicit "
        "supported domain. (iii) A verification hierarchy: Earth regression in two climates and the unit-test suite; "
        "planetary software tests; numerical and component checks against independent references (JPL Horizons, "
        "Diviner and Apollo data, Martian rover infrared data, closed-form boundary balances and NIST gas properties); "
        "a weather-file round trip on two habitats; and sensitivity to numerics and uncertain inputs. (iv) Lessons for "
        "adapting engines, "
        "notably a warm-up-aware start-up for walls whose time constants exceed the warm-up period and the humidity "
        "conventions of ideal loads in a sealed cabin. None of this evidence validates a complete habitat; that requires "
        "thermal-vacuum tests of a habitat-scale article, for which the verified engine is a precondition. "
        f"{C.sec('bg')} reviews how EnergyPlus meets its environment and the routes to off-Earth simulation, "
        f"{C.sec('auditsec')} the audit, {C.sec('designsec')} the planetary mode, {C.sec('verifsec')} the verification "
        f"and {C.sec('discsec')} its scope and limits.")

    m.heading("Background", label="bg")
    C.background(m)
    m.heading("Auditing the engine for Earth assumptions", label="auditsec")
    C.audit(m)
    m.heading("Planetary mode", label="designsec")
    C.design(m)
    m.heading("Verification", label="verifsec")
    C.verif_intro(m)
    C.verif_earth(m)
    C.verif_independent(m)
    C.verif_cross(m)
    C.verif_startup(m)
    C.verif_habitat(m)
    C.sensitivity(m)
    m.heading("Discussion", label="discsec")
    C.discussion(m)

    m.heading("Conclusions", label="concl")
    m.para(
        "A mature building simulation engine can be adapted to the Moon and Mars with a small, well-placed change, "
        f"provided the Earth is found first. The audit of EnergyPlus v26.2 recorded {N_FIND} Earth-specific assumptions, "
        "hidden in time constants, a single shared pressure, exterior boundary conventions, PV cell-temperature fits and "
        "empirical correlations, and tracing each to the code exposed refusals that had been documented but not "
        f"implemented. Once they are known, a planetary mode of {DIFF['insertions']:,} lines suffices for sealed, "
        "windowless habitats with internal gains, humidity control, ideal loads, PV and batteries, while Earth results "
        "stay bit-for-bit identical in the tested files and climates. Off-Earth, the changed components agree with "
        "independent references, and a weather file exported from the engine's generator reproduces its results within "
        f"{RT_MAX:.2f}%. The verification exposed what mattered most: walls with time constants longer than the warm-up "
        "period must start from a consistent state, and even then a regolith cover keeps about 1% of start-up memory "
        "after a month, so design studies need a long spin-up; and ideal loads dry a sealed cabin more than a condensing "
        "heat exchanger held at the "
        "humidity limit would. Sensitivity to uncertain regolith, envelope and dust inputs exceeds the numerical "
        "differences, and validation against thermal-vacuum tests of a habitat-scale article remains the missing step.")

    # ======================================================================= back matter (anonymized)
    m.heading("Data availability statement", numbered=False)
    m.para(
        "The Thermonaut source code, the audit reports and inventory, the planetary tests, the verification cases, the "
        "scripts that compare it with EnergyPlus v26.2.0, and the data behind every figure and table are "
        "openly available in public repositories (links withheld for anonymous review; they are given on the title page).")
    m.heading("Disclosure statement", numbered=False)
    m.para("The authors report there are no competing interests to declare.")
    m.heading("Supplementary material", numbered=False)
    m.para(
        "S1 audit inventory and traceability; S2 planetary factors; S3 Earth regression per file; S4 planetary tests; "
        "S5 start-up and spin-up robustness; S6 version history; S7 habitat input provenance; S8 planetary weather format; "
        "S9 refused objects; S10 worked example.")

    m.heading("References", numbered=False)
    m.reference_list()


def main():
    m = build_two_pass(build, REFS)
    out = HERE / "Thermonaut_manuscript.docx"
    m.save(out)
    print("saved", out, "| cited", len(m.cite_order), "| figs", m.fig_no, "| tables", m.tab_no, "| eqs", m.eq_no)


if __name__ == "__main__":
    main()
