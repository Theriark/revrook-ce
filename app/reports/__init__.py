"""Reports (phase 8): the quarterly business review and the insurance evidence pack.

A report is built from a stored snapshot (`app/scoring/snapshot.py`) and never from
live evidence: the scores, statuses, evidence times and weights come from the
snapshot, so the same snapshot and the same report details give the same HTML, byte
for byte. The shipping format is HTML with a print stylesheet; the PDF spike
(docs/pdf-spike.md) decided against bundling a PDF library in the Community Edition.

    view.py          the snapshot and the report details as a view model
    status.py        the four status labels and how a control gets one
    topics.py        the insurance topics and their status
    charts.py        inline SVG charts, written here, with a data-table fallback
    completeness.py  what blocks an export (a claim with no dated evidence)
    render.py        Jinja2 templates to the final HTML
    export.py        the export history: an immutable copy and its hash
"""
