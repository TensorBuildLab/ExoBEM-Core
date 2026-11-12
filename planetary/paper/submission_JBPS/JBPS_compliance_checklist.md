# Journal of Building Performance Simulation: Instructions for Authors, checked point by point

Source: the Taylor & Francis Instructions for Authors page for JBPS (TBPS), as updated on 20 October 2026.

**Status labels:**
- **Yes**: the package complies.
- **Action**: you need to do something before or during submission.
- **N/A**: does not apply to this paper.

| # | Requirement in the guide | Status | Where it stands |
|---|---|---|---|
| 1 | Original research article, at most 10,000 words *including* tables, references, figure captions and endnotes | Yes | 8,826 words in total: text, captions and references 7,636, tables 1,190 (count printed by `build_submission_thermonaut.py`). The supplement is outside the limit. |
| 2 | Unstructured abstract of no more than 150 words | Yes | 147 words. The build asserts the limit. |
| 3 | 3–6 keywords | Yes | 6: EnergyPlus; building performance simulation; lunar habitat; Mars habitat; software verification; code audit. |
| 4 | Double-anonymous review: the manuscript carries no author names, affiliations or identifying links | Yes | `Thermonaut_manuscript_anonymous.docx` has no author block, acknowledgements or repository URLs. The repository link is "withheld for anonymous review". The tutorial in the supplement uses `<Thermonaut repository>`. |
| 4a | Remove identifying metadata from the files | Yes / **Action** | The build clears author, last-modified-by and the other document properties. Run Word's Inspect Document once more after any manual edit. |
| 4b | Self-citation in the third person | N/A | The manuscript cites no work of the author. |
| 5 | Separate title page with all authors, affiliations, ORCID, corresponding author and email | Yes | `Thermonaut_title_page.docx` (built locally, not in the repository). |
| 6 | Format-free submission: any layout and any consistent reference style | Yes | Numbered references, used consistently. |
| 7 | Suggested order: title page; abstract; keywords; main text; acknowledgements; declaration of interest; references; appendices; tables; figures; figure captions | Yes | Manuscript: abstract, keywords, main text, data availability, disclosure, supplementary list, references. Acknowledgements and funding are on the title page to keep the manuscript anonymous. Tables and figures are inline, which a format-free submission allows. |
| 8 | Funding details, or a statement that there was none | **Action** | The title page has a placeholder. Add the grant details, or keep the "no specific grant" sentence. |
| 9 | Disclosure statement (competing interests) | Yes | On both the manuscript and the title page. |
| 10 | Data availability statement, with a DOI recommended | Yes / **Action** | Statement present: anonymized in the manuscript, full link on the title page (Thermonaut repository, tag `thermonaut-m2e.1`). **Recommended:** archive the tag on Zenodo and add the DOI on acceptance. |
| 11 | Data deposition | Yes | Code, audit inventory, tests, verification data and the paper's build scripts are in the Thermonaut repository. |
| 12 | Author contributions (CRediT) at submission | Yes | On the title page. Enter the same roles in the submission system. |
| 13 | Declaration of generative-AI use | Yes | On the title page. Section 3.1 also describes the LLM code agents, because they are part of the audit method. |
| 14 | ORCID for the author | Yes | 0000-0001-9884-5199, on the title page. Link it in the submission system. |
| 15 | Figures: 300 dpi for colour; TIFF, JPEG or EPS; separate files | Yes | `Figure1.tif`–`Figure6.tif`, 300 dpi, LZW-compressed, in order of first citation. The figures are also embedded in the manuscript for review. |
| 16 | Figure captions | Yes | In the manuscript under each figure. Upload them as a list too if the system asks. |
| 17 | Tables editable, not images | Yes | Ten Word tables. |
| 18 | Equations editable | Yes | Word (OMML) equations. |
| 19 | SI units | Yes | SI throughout. Thermal inertia is given in J m⁻² K⁻¹ s⁻½, written as "SI". |
| 20 | Supplementary material as separate files | Yes | `Thermonaut_supplementary.docx` (S1–S10) and `Thermonaut_S1_audit_inventory.csv`. Both are anonymized. |
| 21 | Graphical abstract (optional; at most 525 px wide; file named "GraphicalAbstract1") | N/A | Not prepared. It is optional. |
| 22 | Cover letter | Yes | `Thermonaut_cover_letter.docx` (built locally, not in the repository). It states that the paper is not under consideration elsewhere, has not been posted as a preprint and has been prepared for double-anonymous review. |
| 23 | No multi-part or series papers | Yes | The paper stands alone. |
| 24 | Not under consideration elsewhere | Yes | Stated in the cover letter. |
| 25 | Preprints allowed, but they can compromise anonymity | Yes | No preprint posted. **Avoid posting one** during review. |
| 26 | Similarity check (Crossref) | Yes | Text written for this paper. |
| 27 | Article publishing charges | N/A | No fee for standard publication. Colour in print is charged, so request online-only colour if asked. |
| 28 | English and style | Yes | British spelling, consistent with T&F style. |
| 29 | Reporting of software versions | Yes | EnergyPlus v26.2.0, compiler (MSVC 14.44), OS (Windows 11) and patch set (M2e) are named. |

## Files to upload

| Upload slot | File |
|---|---|
| Anonymous manuscript | `Thermonaut_manuscript_anonymous.docx` |
| Title page | `Thermonaut_title_page.docx` |
| Cover letter | `Thermonaut_cover_letter.docx` |
| Figures | `Figure1.tif` … `Figure6.tif` |
| Supplementary material | `Thermonaut_supplementary.docx`, `Thermonaut_S1_audit_inventory.csv` |

## Before you press submit

1. Fill in the funding statement on the title page.
2. If you edit the anonymous manuscript or the supplement in Word, run File › Info › Check for Issues › Inspect Document again.
3. Confirm that the GitHub tag `thermonaut-m2e.1` exists, and consider a Zenodo DOI.
4. Enter the CRediT roles, ORCID and AI declaration in the submission system's forms.
