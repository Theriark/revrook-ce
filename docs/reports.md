# Reports (phase 8)

Two reports are built from a stored snapshot (`app/scoring/snapshot.py`): the quarterly
security review (QBR) and the cyber insurance evidence pack. The shipping format is HTML
with a print stylesheet; see `docs/pdf-spike.md` for why there is no PDF.

## From snapshot to file

| Step | Module | What it does |
| --- | --- | --- |
| View | `app/reports/view.py` | Reads the bytes of a snapshot (its digest is checked, so an edited pack is refused), scores its stored inputs, and joins the wording of the control library of the same ruleset version. A snapshot made by another ruleset version is refused. No clock, no database. |
| Labels | `app/reports/status.py` | Protected, Needs attention, Not protected, Not checked (and Not applicable), always an icon and words. |
| Topics | `app/reports/topics.py` | The insurance topics and their status (Met, Partly, Not met, Not checked). |
| Charts | `app/reports/charts.py` | Inline SVG bar charts, written here, with a title, a description and a table of the same numbers. |
| Check | `app/reports/completeness.py` | Blocks an export that claims more than its evidence shows. |
| Render | `app/reports/render.py` | Jinja2 with autoescape to one HTML file with its stylesheets inlined. |
| History | `app/reports/export.py` | Keeps an immutable copy and the SHA-256 of every file made. |

The same snapshot and the same context give the same bytes: the renderer reads no
clock, no random value and no unordered dictionary. The context is put together when a
file is previewed or exported (`app/ui/reports.py`): the details of the report builder,
the open exceptions of the client as they are at that moment (`open_exceptions` of
`app/posture.py`, not a copy kept in the snapshot) and the date of generation from the
clock of the application. A later preview of an older report therefore prints an
exception recorded after its snapshot; the export history keeps each exported file as
it was sent. `tests/golden/reports` holds the six
reports of the worked clients A, B and C (written by `tools/make_report_golden.py`, read
by `tests/test_reports.py`).

## A claim needs dated evidence

A control is Protected only when its status is pass, its evidence has a date that is not
after the pack date and the evidence is not out of date. Anything else is Not checked. So
a Protected label without dated evidence cannot be produced (a property test draws 500
random states of all 51 controls and checks it). The completeness check goes further and
stops the export when the snapshot holds a result with no date, evidence dated after the
pack date, a control marked not applicable with no reason (and no second reviewer for a
gate control), a finding or exception that names no control, or details that are empty or
too long.

## Escaping

Every text a person enters (MSP and client name, preparer, data sources, findings, plan
lines, exception owner, reason and compensating control, the reason and the reviewers of
a not-applicable decision, topic owners) goes through Jinja2 autoescape. A hostile name or
exception text is printed as text. This closes the limit recorded in `docs/controls.md`
and `docs/scoring-engine.md`: the reason of a not-applicable decision is copied into the
check result unescaped and is escaped here, where it is printed.

## The disclaimer and the brand

The disclaimer of rnd-report-3 section 3.8 (`app/reports/disclaimer.py`) is in the footer
of every section of the report (each is one `.page` of the HTML, and starts on a new
sheet when printed) and in full on the last page, with the line "Generated with
revrook". A section that is longer than one printed sheet has its footer at its end
only, so a middle sheet of a long section does not carry the disclaimer; the first
sheet of every section starts with the report heading, and the last page has the full
text. The MSP name is on the cover. No revrook logo is on a client page. The status colours and
the secondary text are the approved brand tokens and appear on white only;
`tests/test_report_contrast.py` reads every foreground and background pair of the report
stylesheets, as `tests/test_brand_contrast.py` does for the application.

## Export history

`export_report` runs the completeness check, renders the HTML, stores the bytes in the
evidence store under their SHA-256 and writes one `report_export` row (hash, size,
file name, key, user). The database refuses to change that row afterwards (migration 0004).
`read_export` checks the stored copy against the hash every time, so a copy altered on disk
is reported and never sent. Deleting a client deletes its exports and their files.
