# Design system

The web interface is one stylesheet, `app/static/css/revrook.css`, on top of the
vendored Pico CSS, which is kept only as a reset and for element defaults. There is
no build chain, the fonts are the system stack, nothing is loaded from outside the
installation, and no page carries an inline style or script
([docs/security.md](security.md)). This page records the tokens, the shell and the
components so that every page is built from the same parts.

## What it is for

A small MSP owner opens revrook to see where each client stands and to prepare the
evidence a client, an insurer or a quarterly review asks for. The interface is calm,
dense and readable: charcoal and white with one violet-blue accent, status always as
an icon and its words, and nothing that moves unless the person did something.

The one signature of revrook is the charcoal rail on the left: the rook's plumage,
carrying the dark logo, the navigation and the signed-in user, with a 3 px violet-blue
mark on the current page. Signed-out pages show the same charcoal as a panel with the
stacked logo next to the form.

## Tokens

Colours. The five brand colours are never changed; the derived ones are checked
against the text they carry by `tests/test_brand_contrast.py` and
`tests/test_design_system.py`.

| Token | Value | Role |
| --- | --- | --- |
| `--rv-charcoal` | `#2d2f3a` | Text on white; the rail and the sign-in panel |
| `--rv-accent` | `#4c5bd4` | Links, primary buttons, the mark of the current page |
| `--rv-stone` | `#d9d6cf` | Text on charcoal; dashed borders |
| `--rv-gray` | `#8a8f98` | Control borders; text only on charcoal at 24 px or more |
| `--rv-white` | `#ffffff` | The page and every surface that carries status text |
| `--rv-text-secondary` | `#5a5e6b` | Secondary text, on white only |
| `--rv-canvas` | `#f4f3ef` | Table headers, code, the footer, the import area |
| `--rv-line` | `#e4e2db` | Borders and dividers |
| `--rv-charcoal-deep` | `#22242d` | The current page in the rail |
| `--rv-charcoal-soft` | `#3a3d4b` | Hover in the rail, the avatar |
| `--rv-stone-dim` | `#a9a69e` | Group labels in the rail |
| `--rv-accent-deep` | `#3a47b5` | Links on hover |
| `--rv-accent-tint` | `#eceefa` | The import area while a file is dragged over it |
| `--rv-status-protected` | `#1b6e3c` | Protected, on white only, with an icon |
| `--rv-status-needs-attention` | `#8a5a00` | Needs attention, on white only, with an icon |
| `--rv-status-not-protected` | `#b3261e` | Not protected, on white only, with an icon |
| `--rv-status-not-checked` | `#5a5e6b` | Not checked and not applicable, on white only |

Rules the tests enforce: every rule that sets a text colour also sets its background;
gray is never text on white or stone; the accent is never text on charcoal; the status
colours and secondary text are text on white only; a status is never shown by colour
alone.

Type: the system stack (`system-ui`, Segoe UI, Roboto, Helvetica, Arial). Sizes 12,
13, 14, 15 (body), 16, 20, 24 and 28 px; the text wordmark is bold Helvetica or Arial.
Spacing 4, 8, 12, 16, 24, 32 and 48 px. Radius 8 px on controls and 12 px on cards and
tables. Two elevations (`--rv-shadow-1` for cards, `--rv-shadow-2` for dialogs).
Motion 150 ms ease-out on hover and focus only, off under `prefers-reduced-motion`.

## The shell

`app/ui/templates/base.html` draws one of two shells. A page rendered with a `user` in
its context gets the app shell: the charcoal rail (`header.rv-header`) with the dark
logo, the "Community Edition" badge, the grouped navigation of `_nav.html` and the
signed-in user with the sign-out button; then the page column with the stale-worker
banner, `main.rv-content` and the footer with the disclaimer. From 1024 px the rail is
a 248 px sidebar that stays in view, with the sign-out button on its own line under the
user name; below that it is a charcoal bar with the navigation as a scrolling strip, so
no menu is ever hidden behind a button, and below 600 px the bar drops the edition
badge (the footer still names the edition) so it never meets the sign-out button.

A page without a `user` (sign-in, first run) gets the signed-out shell: the charcoal
panel with the stacked logo and three lines about the product on the left, the light
logo, the badge, the form and the footer on the right. Below 768 px the panel becomes a
short band above the form.

A page marks where it is with `nav` in its context: `home`, `clients`,
`profile-editor`, `integrity`, `settings`, `system` or `glossary`. The link of that
page carries `aria-current="page"` and the violet-blue mark.

Icons come from the macro in `app/ui/templates/_icons.html`:
`{% import "_icons.html" as i %}` then `{{ i.icon("clients") }}`. Every icon is an
inline stroke drawing in the current colour, hidden from assistive technology, with
the words next to it carrying the meaning. Add an icon there, never as an image file
or a data: URL: the content security policy (`default-src 'self'`) blocks `data:`
images, which is why the control icons of Pico (select arrow, date picker, checkbox
mark) were blank. The stylesheet switches every Pico icon variable off and shows the
native controls instead, with `accent-color` for checkboxes and radios.

Static files and caches. The two stylesheets and the two scripts are linked with a
version query: `?v=` followed by `asset_version()` of `app/ui/brand.py`, a 12-character
digest of the four files read once at start-up. A browser, and any cache in front of
the installation, keeps a static file for hours; with the digest in the address a new
version of a file has a new address, so a page is never shown with the stylesheet of
the release before it. The brand files are not versioned: they are copies of the
approved assets and do not change between releases.

## Components

Page header: the title, one line of purpose and the actions of the page.

```html
<div class="rv-page-header">
<div><h1>Clients</h1><p class="rv-page-purpose">Every client and the date of its newest evidence.</p></div>
<div class="rv-page-actions"><a role="button" href="/clients/new">Add a client</a></div>
</div>
```

Buttons: a bare `<button>` is the one primary action of a form; `rv-button-quiet`
for the secondary action; `rv-button-danger` for a deletion, always next to a
confirmation; `rv-button-small` in table rows; `rv-button-block` on the sign-in form.
Group them in `<div class="rv-actions">`.

Fields: one `div.rv-field` per control with a `<label for>`, the control, and
`small.rv-help` or `small.rv-field-error` named by `aria-describedby`. Put two short
fields side by side in `div.rv-field-row`. Checkboxes and radios sit in
`label.rv-check`. Selects and date fields are native controls.

Tables: a plain `<table>` with a `<caption>`, `<th scope="col">` in the head and
`<th scope="row">` for the first cell. The head is sticky, rows show a hover colour,
and `rv-numeric` aligns numbers. Wrap a wide table in `div.rv-table-scroll`.

Cards and stats: `div.rv-card` with `h2.rv-card-title` and `p.rv-card-subtitle`;
several cards in `div.rv-grid`. A stat card holds `span.rv-stat-value` (28 px, tabular
numbers) and `span.rv-stat-label`.

Status: the macro in `_status.html` renders `<span class="rv-status-protected">` with
the icon and the words, drawn as a pill. The same class on a `<p>` with
`role="status"` or `role="alert"` is a message strip with the colour as its left rail.

Alerts: `div.rv-alert` with `p.rv-alert-title` and text; `rv-alert-success`,
`rv-alert-warning` and `rv-alert-danger` change the rail. Form errors use
`_errors.html`.

Empty state: `div.rv-empty` with an icon, `p.rv-empty-title`, `p.rv-empty-text` and
the one action that fills it. It says what to do first, never only that nothing is
there.

Import area: a `label.rv-dropzone` around the file input. The input covers the whole
area, so dropping a file on it or clicking it works without script;
`app/static/js/revrook.js` adds the drag-over colour and writes the chosen file names
into `output.rv-dropzone-file`.

```html
<label class="rv-dropzone">
{{ i.icon("upload") }}
<span class="rv-dropzone-title">Drop the export here, or choose a file</span>
<span class="rv-dropzone-hint">CSV or JSON, up to 25 MB</span>
<input type="file" name="file" accept=".csv,.json" required>
<output class="rv-dropzone-file" aria-live="polite"></output>
</label>
```

Confirmation: an inline `details.rv-confirm` whose `<summary>` is the quiet button
and whose `div.rv-confirm-body` holds the question, the field to type the name where
one is required, and the danger button. It opens without script. A page that needs a
full stop uses `dialog.rv-dialog` rendered with the `open` attribute; its actions sit
in `div.rv-dialog-actions`.

Loading: `span.rv-skeleton` for a block that is still coming and `span.rv-busy` next
to a button that is working. htmx swaps keep `aria-busy`.

## Dashboard

Home (`app/ui/templates/home.html`, data from `app/ui/home.py` and the pure functions
of `app/ui/dashboard.py`) is the page an MSP owner opens every morning: which client
needs work today, and what changed. It is read-only. Every number comes from the same
views, labels and stored snapshots as the client pages and the reports, so Home never
says something a report would not say.

Its parts, in order:

- Four stat cards: clients, controls protected, controls that need work, exports to
  refresh. Each shows the number, its context, the change against the last stored
  report of every client that has one, and a sparkline of the last twelve weeks drawn
  from the stored reports (`.rv-stat`, `.rv-spark`). The number is a link.
- The rookery (`.rv-rookery`), the signature of Home: one posture ring per client,
  the score inside, the band beside it, the controls that need work and the movement
  since the last report under it. A client whose evidence is too thin for a score has
  a dashed stone ring and a question mark, never a number that would read as a score.
- Needs attention (`.rv-attention`): the eight most urgent controls across every
  client, gate controls first, then what is not protected, by weight. Every row is the
  status pill, the control, the client and the reason beyond the status (old evidence,
  an open exception), and one action.
- Score over the last 90 days (`.rv-chart`): one line per client from the stored
  reports, up to six, labelled at its end and told apart by its dash pattern; a table
  under the chart carries every number. Controls by domain (`.rv-domains`): a stacked
  bar per domain with the counts in the columns beside it and a legend of status pills.
- Recent changes (`.rv-timeline`): the newest audit entries that changed a client,
  its evidence or its reports, with who did it and when (the exact time on hover).

States: a fresh installation shows one empty state with the three first steps and
one action; a client without evidence shows a dashed ring and "No evidence imported
yet"; a client whose evidence cannot be read today is listed in a warning strip above
the dashboard instead of stopping it; the attention list, the chart and the timeline
each have their own empty state that says what fills them. The page is rendered whole
on the server: there is no part that loads later, so there is no loading state to
show.

Charts are inline SVG drawn on the server with the brand colours only: the sparkline
and the ring arc in the accent, the lines in charcoal, the domain bars in the status
colours with the counts beside them, so nothing is told by colour alone. No library,
no image, nothing loaded from outside.

## Floors every page keeps

- Works at 390, 768 and 1440 px without horizontal overflow.
- A 3 px focus ring on every control (white on charcoal), a label on every field,
  one `h1` and one `main`, and no element inside a `<p>` that a browser would close
  early (`tests/html_structure.py`, see [docs/testing.md](testing.md)).
- Empty, loading, error and success states designed; copy in plain words, active
  voice, sentence case.
- No external font, image, script or style; no tracking.
