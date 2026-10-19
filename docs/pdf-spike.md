# PDF spike (phase 8, step 1)

Question: can the Community Edition ship PDF reports made by WeasyPrint, with a bundled
Noto Sans font, inside the `python:3.12-slim` image?

**Decision: no. CE ships HTML with a print stylesheet only.** The PDF code is not in this
repository. Two of the hard gates cannot be met by this work package, whatever the
measurements say, so the plan's rule applies: "if ANY gate fails, CE ships HTML with
print CSS only, the PDF code is not merged, and docs/pdf-spike.md records the evidence so
R&D can decide the EE path (ReportLab)".

## The gates

| Gate | Needed | Result | Evidence |
| --- | --- | --- | --- |
| Licences read from the primary file (WeasyPrint, Pango and the other OS libraries, the font) | Each one read, each permissive, or LGPL as a dynamically linked OS package with notices | **Not met: not read** | The licence texts of WeasyPrint, Pango, Pyphen and Noto Sans were not opened. The tool that reads a web page was refused to this role (no permission was granted), and the GitHub read grant of this task covers `Theriark/revrook-ce` only. Nothing is assumed from memory: a licence that was not read is not recorded as permissive. |
| A bundled font with its `OFL.txt` in the repository | Noto Sans regular and bold (SIL OFL 1.1) committed with the licence file | **Not met** | A font is a binary file. The tools the crew has write plain text one commit at a time (`push_files`); `brand_assets` copies only the product's own Nextcloud brand folder. A TTF cannot be committed by this role, and a font installed by the operating system (the spike below uses `fonts-noto-core`) is not the bundled font the plan names. |
| Image size increase | Under 250 MB | Measured in CI, see below | `scripts/pdf-spike/measure.sh` |
| Peak RAM during a 10-page report | Under 400 MB | Measured in CI, see below | the same script |
| Render time | Under 30 seconds | Measured in CI, see below | the same script |
| Tagged PDF | A structure tree and `MarkInfo` in the file | Measured in CI, see below | the same script |

## What was measured, and how

This work package has no Docker, so the measurement runs where Docker exists: in check 9
of the merge gate, from `scripts/e2e/phase_08.sh`, which calls
`scripts/pdf-spike/measure.sh`. No workflow file was changed.

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

The script prints lines that start with `SPIKE` in the log of the check, and a final
`SPIKE gates size=... ram=... time=... tagged=...` line. A problem in the script is a
warning, never a failure of the merge gate: the decision above does not depend on it.

## Results of the measurement

The values of the run that merged this change are in the log of check 9 and are quoted
in the report of the task (THE-314). They inform the EE decision; they do not reopen
the CE decision, because the licence and font gates stand regardless.

## What CE ships instead

- HTML, one file with its stylesheet inlined, that loads nothing from outside.
- A print stylesheet (`app/reports/print.css`): A4, one `.page` per sheet, the footer
  with the disclaimer on every page. "Save as PDF" in a browser gives a PDF of it.
- The disclaimer in every footer and in full on the last page (checked on every page of
  both reports by `tests/test_reports.py`). A PDF text-extraction test is not written:
  there is no PDF to extract from.

## What R&D needs to decide for EE

1. Read the primary licence files (WeasyPrint, Pango, HarfBuzz and the other libraries it
   loads, Pyphen, the Noto Sans OFL) and record them in `docs/licences.md` with the date.
   Pyphen offers GPL, LGPL and MPL; the repository policy (check 6) rejects LGPL and GPL
   packages, so the audit would need an explicit exception or a different library.
2. A way to commit the font binary, or the decision to depend on a font package.
3. If WeasyPrint fails on a licence, evaluate ReportLab (BSD-3-Clause, to be read) with
   tagged-PDF support as the plan says.
4. The measurements above, from the run that merged this change.
