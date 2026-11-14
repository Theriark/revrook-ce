# Reports (phase 8)

Two reports are built from a stored snapshot (`app/scoring/snapshot.py`): the quarterly
security review (QBR) and the cyber insurance evidence pack. The shipping format is HTML
with a print stylesheet. A PDF is that same file, printed on request by the browser of the
image (`app/reports/pdf.py`, see `docs/pdf-spike.md`).

## From snapshot to file

| Step | Module | What it does |
| --- | --- | --- |
| View | `app/reports/view.py` | Reads the bytes of a snapshot (its digest is checked, so an edited pack is refused), scores its stored inputs, and joins the wording of the control library of the same ruleset version. A snapshot made by another ruleset version is refused. No clock, no database. |
| Labels | `app/reports/status.py` | Protected, Needs attention, Not protected, Not checked (and Not applicable), always an icon and words. |
| Topics | `app/reports/topics.py` | The insurance topics and their status (Met, Partly, Not met, Not checked). |
| Charts | `app/reports/charts.py` | Inline SVG, written here: the bar chart of the domains, the status bar of the summary and the score dial of the cover, each with a title and a description, its numbers printed beside it as text or as a table. |
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

## The look of the document

A report is read as a document, not as a page of the application. On a screen each
section is a white sheet as wide as A4 and as tall as what it holds, on a stone desk.
The cover opens with a charcoal head (the one dark surface of a report): the name of
the MSP, the report, the client and the period. Under it the quarterly review draws
its score as a dial with the band, beside who prepared it, the dates, the data sources
and the snapshot; the insurance pack has no dial, because it answers a form. The
summary prints its three figures (score, evidence coverage, band) as one row and the
controls by status as one bar above the table of the same numbers. A finding is a line
of a list and says which evidence it is read from and how that evidence is dated.
When the snapshot keeps it, a finding also says **what was checked**: the sentence of
the check engine at the moment the snapshot was made (`control_result`, one row for
each control, written by `store_results` of `app/snapshots.py`); a snapshot made before
that prints none. Where the technician wrote no recommendation, a finding prints the
**usual next step** of its control (`app/reports/advice.py`: one general sentence for
each of the 51 controls, outside the ruleset; a control that passes on evidence grown
old asks for a fresh export instead); what the technician recommends takes its place.
The kinds
of evidence are named as a client reads them (`PLAIN_SOURCES` of `app/reports/view.py`:
"Microsoft 365 export", "Backup jobs export"), not by the shorthand of the library.
**What could not be checked** lists the kinds of evidence the controls that were not
checked read, the kind most of them wait for first; it is left out when every control
was checked. The roadmap and the plan are printed only when something was written, so
a client never reads an empty heading. Each of the eight domains has a mark beside its
name (the coverage table, the appendix).

Printed (`print.css`), the cover is a sheet of its own, the appendix and the last page
start on a new sheet, and the sections between them follow one another, so a short
section leaves no sheet empty; a heading is never left alone at the foot of a sheet,
and every sheet carries its number. The surfaces that carry meaning by their colour
(the head of the cover, a table heading, a bar) ask the printer to keep them, so a
PDF saved from the browser looks like the screen without the background option.

The page **Preview and export** of the application draws its paper sheet the same way
(`app/ui/templates/report.html`): the dark head of the cover, the dial (`dial_of`) and
the status bar (`status_chart_of`) are the ones the file prints, so what a technician
sees before exporting is the cover and the summary of the file. The card of the
reports offers **Download PDF** for each report (`GET
/clients/<id>/reports/<id>/pdf/<kind>`): the bytes of the preview, printed by the
browser of the image, one request at a time. On a machine without a browser there is
no button and the card says how to print the preview. A PDF is not kept and has no
row in the export history: the export stays the HTML file and its hash.

## The disclaimer and the brand

The disclaimer of rnd-report-3 section 3.8 (`app/reports/disclaimer.py`) is in the footer
of every section of the report (each is one `.page` of the HTML) and in full on the
last page, with the line "Generated with revrook". A section that is longer than one printed sheet has its footer at its end
only, so a middle sheet of a long section does not carry the disclaimer; every
section starts with the report heading, and the last page has the full text. The MSP name is on the cover, under the logo of the MSP when one is set in
Settings (a PNG, JPEG or WebP file of at most 200 KB, known by its first bytes, never
SVG; it travels inside the report as a `data:` picture, on a white plate so that a
dark mark is seen on the dark head, and the preview policy allows `img-src data:` and
nothing else). **Prepared by** is the name the person chose on the Account page, or
the sign-in name when none is set, unless the report builder says otherwise. No
revrook logo is on a client page. The status colours and
the secondary text are the approved brand tokens and appear on white only;
`tests/test_report_contrast.py` reads every foreground and background pair of the report
stylesheets, as `tests/test_brand_contrast.py` does for the application.

## Export history

`export_report` runs the completeness check, renders the HTML, stores the bytes in the
evidence store under their SHA-256 and writes one `report_export` row (hash, size,
file name, key, user). The database refuses to change that row afterwards (migration 0004).
`read_export` checks the stored copy against the hash every time, so a copy altered on disk
is reported and never sent. Deleting a client deletes its exports and their files.
