# Thermonaut paper (Journal of Building Performance Simulation)

The manuscript, its supplement and the submission package are built from the verification results of this
repository.

```
planetary/paper/
├── lib/                              docxkit (Word builder), refs (reference list), factors (S2 factor table)
├── extract_thermonaut_data.py        collects results from planetary/cases, planetary/tests, the audit and the runs into data/
├── build_figures_thermonaut.py       figures/core_fig1-core_fig6
├── sections_thermonaut.py            section text
├── build_paper_thermonaut.py         Thermonaut_manuscript.docx (anonymized for double-anonymous review)
├── build_supplementary_thermonaut.py Thermonaut_supplementary.docx (S1-S10)
├── build_submission_thermonaut.py    submission_JBPS/: anonymous manuscript, supplement, 300-dpi TIFFs, word count;
│                                     title page and cover letter (built locally, not tracked)
├── data/                             verification results and the audit inventory the paper is built from
└── submission_JBPS/                  submission package, JBPS compliance checklist, response to pre-submission reviews
```

## Building

```
python planetary/cases/roundtrip_check.py            # generator and weather-file runs (../exo-runs/roundtrip)
python planetary/paper/extract_thermonaut_data.py
python planetary/paper/build_figures_thermonaut.py
python planetary/paper/build_paper_thermonaut.py
python planetary/paper/build_supplementary_thermonaut.py
python planetary/paper/build_submission_thermonaut.py    # set THERMONAUT_AUTHOR_EMAIL for the title page
```

Cross-references in the section text are written as `@fig:name`, `@tab:name`, `@sec:name` or `@eq:name` and are
numbered in a second build pass by `docxkit.build_two_pass`.
