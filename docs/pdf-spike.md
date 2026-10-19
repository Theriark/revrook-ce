# PDF spike (phase 8, step 1)

Question: can the Community Edition ship PDF reports made by WeasyPrint, with a bundled
Noto Sans font, inside the `python:3.12-slim` image?

**Decision for now: CE ships HTML with a print stylesheet only, and the PDF code is not
in this repository.** The plan says that if any gate fails, CE ships HTML with print CSS
only, the PDF code is not merged, and this page records the evidence so that R&D can
decide the PDF path for a later edition (ReportLab). No gate was shown to fail. Two gates
could not be assessed by this work package (see the table) and the other four were never
measured in a run whose numbers are recorded, so every gate is **not assessed**. HTML only
is the safe shipping format while that is so. Whether a gate that was not assessed counts
as failed is a question for R&D, and so is who reads the licences; this document does not
answer it.

## The gates

| Gate | Needed | Result | Evidence |
| --- | --- | --- | --- |
| Licences read from the primary file (WeasyPrint, Pango and the other OS libraries, the font) | Each one read, each permissive, or LGPL as a dynamically linked OS package with notices | **Not assessed: not read** | The licence texts of WeasyPrint, Pango and the other libraries it loads, and of Noto Sans, were not opened. The tool that reads a web page was refused to this role (no permission was granted), and the GitHub read grant of this task covered `Theriark/revrook-ce` only. Nothing is assumed from memory: a licence that was not read is not recorded as permissive or as anything else. |
| A bundled font with its `OFL.txt` in the repository | Noto Sans regular and bold (SIL OFL 1.1) committed with the licence file | **Not assessed** | A font is a binary file. The tools the crew has write plain text one commit at a time (`push_files`); `brand_assets` copies only the product's own Nextcloud brand folder. A TTF cannot be committed by this role, and a font installed by the operating system (the spike below uses `fonts-noto-core`) is not the bundled font the plan names. |
| Image size increase | Under 250 MB | Not measured in a recorded run | `scripts/pdf-spike/measure.sh` (opt-in, see below) |
| Peak RAM during a 10-page report | Under 400 MB | Not measured in a recorded run | the same script |
| Render time | Under 30 seconds | Not measured in a recorded run | the same script |
| Tagged PDF | A structure tree and `MarkInfo` in the file | Not measured in a recorded run | the same script |

## What the measurement does, and how to run it

The measurement needs Docker, so it runs where Docker exists. It is **opt-in**: it
builds a throwaway image and installs unpinned packages, which takes minutes, so it does
not run on every pull request. `scripts/e2e/phase_08.sh` calls
`scripts/pdf-spike/measure.sh` only when the variable `RUN_PDF_SPIKE=1` is set, for
example `RUN_PDF_SPIKE=1 bash scripts/e2e/phase_08.sh` on a machine with the compose
stack running. No workflow file runs it.

1. The script pulls `python:3.12-slim` and records its size (`docker image inspect`).
2. It builds a **throwaway** image from that base with `libpango-1.0-0`,
   `libpangoft2-1.0-0`, `fonts-noto-core` (Debian packages), and `weasyprint` and `pypdf`
   from PyPI (pypdf only to extract text). That image is never pushed, never part of the
   product image, and its Python packages are not hash-locked, because it is a
   measurement and not a dependency of revrook.
3. The size increase is the size of that image minus the size of the base.
4. It renders the six golden reports of `tests/golden/reports` (the QBR and the insurance
   pack for clients A, B and C, about 15 pages each) in one container limited to 1 GB.
   `docker stats` is sampled once a second and the largest value is the peak RAM.
   Sampling once a second can miss a short peak, so the figure is a lower bound.
5. The render time is the wall clock from `docker run` to exit, interpreter start and
   font-cache build included.
6. The PDFs are written with the PDF/UA-1 variant when WeasyPrint offers it. A file
   counts as tagged when it holds both `/StructTreeRoot` and `/MarkInfo`. The text of every
   page is extracted and checked for the first sentence of the disclaimer.

The script prints lines that start with `SPIKE`, and a final
`SPIKE gates size=... ram=... time=... tagged=...` line. A problem in the script is a
warning, never a failure.

## Results of the measurement

None is recorded. The script was not run in a run whose log is kept with the change that
introduced it, and no figure is quoted here. Run it, then record the `SPIKE` lines, the
date and the machine in this section. The numbers would inform the decision for a later
edition; the licence and font gates would still need to be assessed.

## What CE ships instead

- HTML, one file with its stylesheet inlined, that loads nothing from outside.
- A print stylesheet (`app/reports/print.css`): A4, one `.page` for each section of the
  report, each section starting on a new sheet, with the footer and the disclaimer at the
  end of the section. A section that is longer than one printed sheet carries its footer
  on its last sheet only, so a sheet in the middle of a long section has no disclaimer.
  "Save as PDF" in a browser gives a PDF of it.
- The disclaimer in the footer of every section and in full on the last page (checked on
  every section of both reports by `tests/test_reports.py`). A PDF text-extraction test
  is not written: there is no PDF to extract from.

## What R&D needs to decide for a later edition

1. Whether a gate that was not assessed counts as failed, and who reads the primary
   licence files (WeasyPrint, Pango, HarfBuzz and the other libraries it loads, and the
   Noto Sans OFL) and records them in `docs/licences.md` with the date. The repository
   policy (check 6) rejects LGPL and GPL packages, so a dependency of the PDF stack that
   is licensed that way would need an explicit exception or a different library.
2. A way to commit the font binary, or the decision to depend on a font package.
3. If WeasyPrint fails on a licence, evaluate ReportLab (BSD-3-Clause, to be read) with
   tagged-PDF support as the plan says.
4. The measurements, from a run of the opt-in script.
