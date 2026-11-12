"""Assemble the Journal of Building Performance Simulation submission package for the Thermonaut paper.

    python planetary/paper/build_submission_thermonaut.py
writes planetary/paper/submission_JBPS/ (the title page and cover letter are not tracked in git):
    Thermonaut_manuscript_anonymous.docx   (copy of Thermonaut_manuscript.docx; no author information)
    Thermonaut_title_page.docx             (authors, affiliation, ORCID, statements; not sent to reviewers)
    Thermonaut_cover_letter.docx
    Thermonaut_supplementary.docx, Thermonaut_S1_audit_inventory.csv
    Figure1.tif ... FigureN.tif             (300 dpi, in the order of first citation)
and prints the word count (main text, tables, captions and references), which JBPS limits to 10,000.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

from docx import Document
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # Thermonaut repository root
sys.path[:0] = [str(HERE), str(HERE / "lib")]

from build_paper_thermonaut import KEYWORDS, TITLE, abstract_text  # noqa: E402
from docxkit import Manuscript  # noqa: E402
from sections_thermonaut import ENGINE_SHARE  # noqa: E402

OUT = HERE / "submission_JBPS"
AUTHOR = "Liang Zhang"
AFFIL = "Department of Civil and Architectural Engineering and Mechanics, University of Arizona, Tucson, AZ, USA"
ORCID = "0000-0001-9884-5199"
# The email is kept out of the public repository: set THERMONAUT_AUTHOR_EMAIL before building the title page.
EMAIL = os.environ.get("THERMONAUT_AUTHOR_EMAIL", "<corresponding author email>")
FIGS = ["core_fig2_audit.png", "core_fig1_hooks.png", "core_fig6_startup.png", "core_fig5_habitats.png",
        "core_fig3_environment.png", "core_fig4_response.png"]          # order of first citation in the manuscript

CREDIT = ("Liang Zhang: Conceptualization, Methodology, Software, Validation, Formal analysis, Investigation, Data "
          "curation, Writing – original draft, Writing – review & editing, Visualization, Project administration.")
AI = ("During this work the author used Claude (Anthropic), a large language model, as a coding and writing assistant: "
      "its code agents carried out the searches of the source-code audit under the protocol described in the paper and "
      "traced each finding to the code, and it assisted with implementing the planetary mode, writing the verification "
      "and test scripts, and drafting and editing the manuscript. The author designed the study, reviewed every finding, "
      "code change and result, and takes full responsibility for the content.")
DATA = ("Thermonaut (branch thermonaut, release tag thermonaut-m2e.1), with the audit reports and inventory, the "
        "planetary tests, the verification cases and the scripts and data behind every figure and table of the paper "
        "(folder planetary/paper), is openly available at https://github.com/TensorBuildLab/Thermonaut under the "
        "EnergyPlus licence. [Recommended before acceptance: archive the release on Zenodo and cite the DOI here.]")
FUNDING = "[Funding details to be confirmed by the author. If none: “This research received no specific grant from any funding agency in the public, commercial, or not-for-profit sectors.”]"
ACK = ("EnergyPlus is developed by the U.S. Department of Energy's Building Technologies Office, the National Laboratory "
       "of the Rockies (formerly NREL) and their partners; Thermonaut is not EnergyPlus and is not endorsed by them.")


def title_page():
    m = Manuscript()
    m.set_references({})
    m.para(f"**{TITLE}**", align="center", size=15, space_after=12)
    m.para(f"{AUTHOR}^{{*}}", align="center", size=11, space_after=2)
    m.para(AFFIL, align="center", size=10, space_after=2)
    m.para(f"ORCID: {ORCID}", align="center", size=10, space_after=2)
    m.para(f"^{{*}}Corresponding author: {AUTHOR}, {AFFIL}. Email: {EMAIL}", align="center", size=10, space_after=12)
    for head, text in (("Keywords", "; ".join(KEYWORDS)), ("Acknowledgements", ACK), ("Funding", FUNDING),
                       ("Disclosure statement", "The author reports there are no competing interests to declare."),
                       ("Data availability statement", DATA), ("Author contributions (CRediT)", CREDIT),
                       ("Declaration of generative AI use", AI)):
        m.heading(head, numbered=False)
        m.para(text)
    m.save(OUT / "Thermonaut_title_page.docx")


def cover_letter():
    m = Manuscript()
    m.set_references({})
    m.para("Dear Editors,", align="left")
    paras = [
        f"Please consider the manuscript “{TITLE}” for publication as an original research article in the Journal of "
        "Building Performance Simulation.",
        "The paper reports Thermonaut, a research fork of the EnergyPlus v26.2 engine with a planetary mode for sealed "
        "lunar and Martian habitats. Its contribution is to building performance simulation methodology rather than to "
        "planetary science: a protocol-based audit of where a production simulation engine assumes the Earth, with every "
        f"finding traced to its disposition in the code; a design that adds {ENGINE_SHARE:.1f}% to the engine and keeps Earth results "
        "bit-for-bit identical in the tested files and climates; and a verification hierarchy from software regression "
        "and planetary software tests to component checks against independent references, a weather-file round trip and "
        "sensitivity analysis. The study also yields lessons that apply on Earth, notably that constructions whose time "
        "constant exceeds the warm-up period inherit their initial state for months, and how ideal loads misrepresent the "
        "humidity of a sealed zone. We believe the paper fits the journal's interest in the development, verification "
        "and validation of simulation tools.",
        "The manuscript has been prepared for double-anonymous review: author names, affiliations and repository links "
        "appear only on the separate title page. It is not under consideration elsewhere and has not been posted as a "
        "preprint. The code, audit inventory, tests and verification data are openly available. The main text, tables, "
        "captions and references are within the journal's 10,000-word limit; supplementary material gives the complete "
        "audit inventory, per-file regression results, the planetary tests, robustness studies and input provenance.",
        "Thank you for considering this submission.",
    ]
    for p in paras:
        m.para(p, align="justify")
    m.para("Sincerely,", align="left", space_after=2)
    m.para(AUTHOR, align="left", space_after=0)
    m.para("Assistant Professor, " + AFFIL, align="left", space_after=0)
    m.para(EMAIL, align="left")
    m.save(OUT / "Thermonaut_cover_letter.docx")


def figures():
    for i, f in enumerate(FIGS, 1):
        im = Image.open(HERE / "figures" / f).convert("RGB")
        # scale to 16 cm at 300 dpi at most; never upsample
        target_w = round(16.0 / 2.54 * 300)
        if im.width > target_w:
            im = im.resize((target_w, round(im.height * target_w / im.width)), Image.LANCZOS)
        im.save(OUT / f"Figure{i}.tif", dpi=(300, 300), compression="tiff_lzw")


def word_count(path):
    d = Document(str(path))
    words = sum(len(re.findall(r"\S+", p.text)) for p in d.paragraphs)
    cells = 0
    for t in d.tables:
        seen = []                      # keep the elements alive: merged cells repeat the same <w:tc>
        for row in t.rows:
            for c in row.cells:
                if any(c._tc is e for e in seen):
                    continue
                seen.append(c._tc)
                cells += len(re.findall(r"\S+", c.text))
    return words, cells


def main():
    OUT.mkdir(exist_ok=True)
    shutil.copyfile(HERE / "Thermonaut_manuscript.docx", OUT / "Thermonaut_manuscript_anonymous.docx")
    shutil.copyfile(HERE / "Thermonaut_supplementary.docx", OUT / "Thermonaut_supplementary.docx")
    shutil.copyfile(HERE / "data" / "audit_inventory.csv", OUT / "Thermonaut_S1_audit_inventory.csv")
    for f in ("Thermonaut_manuscript_anonymous.docx", "Thermonaut_supplementary.docx"):   # no identifying metadata
        d = Document(str(OUT / f))
        cp = d.core_properties
        cp.author = cp.last_modified_by = cp.comments = cp.title = cp.subject = cp.keywords = ""
        d.save(str(OUT / f))
    title_page()
    cover_letter()
    figures()
    w, c = word_count(OUT / "Thermonaut_manuscript_anonymous.docx")
    n_ab = len(re.findall(r"\S+", abstract_text()))
    print(f"abstract {n_ab} words; paragraphs {w}, tables {c}, total {w + c} (limit 10,000)")
    for f in sorted(OUT.iterdir()):
        print(f.name, f.stat().st_size)


if __name__ == "__main__":
    main()
