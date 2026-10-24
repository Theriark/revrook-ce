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
carrying the brand lockup, the navigation and the signed-in user, with a 3 px violet-blue
mark on the current page. Signed-out pages show the same charcoal as a panel with the
stacked lockup next to the form.

## Tokens

Colours. The five brand colours are never changed, in either theme. Every rule draws
with a role (what the colour is for) or a derived token, never with a palette colour
for text or a surface, so the dark theme redefines the roles and nothing else; the
accent face of a primary button is the one rule that keeps the brand accent in both
themes. `tests/test_brand_contrast.py` checks every pair of the stylesheet in both
themes, `tests/test_theme.py` the recorded values and the switch.

| Token | Light | Dark | Role |
| --- | --- | --- | --- |
| `--rv-charcoal` | `#2d2f3a` | same | Brand: the value of text, rail, ink and focus in the light theme |
| `--rv-accent` | `#4c5bd4` | same | Brand: the face of a primary button in both themes; links and marks in light |
| `--rv-stone` | `#d9d6cf` | same | Brand: text on the rail; the strong line in light |
| `--rv-gray` | `#8a8f98` | same | Brand: control borders; text only on the rail at 24 px or more |
| `--rv-white` | `#ffffff` | same | Brand: text on the rail, on ink and on a button face; the surface in light |
| `--rv-text` | charcoal | `#e6e7ec` | Text on the surface and the canvas; chart lines and the quote rule |
| `--rv-text-secondary` | `#5a5e6b` | `#aab0bd` | Secondary text, on the surface only; the border of a field |
| `--rv-surface` | white | `#1e2028` | The page and every surface that carries status text |
| `--rv-canvas` | `#f4f3ef` | `#272a34` | Table headers, code, the footer, the import area, toolbars and bands |
| `--rv-line` | `#e4e2db` | `#3a3e4b` | Borders and dividers |
| `--rv-line-strong` | stone | `#4d5261` | Decoration only: dashed borders, the underline of a link, the track of the busy indicator; never the boundary of a control or a graphic that carries meaning (2.09 to 1 on the dark surface) |
| `--rv-mark-tile` | `#fffef5` | same | The tile behind the rook mark of the brand lockup: the cream of the approved logo files |
| `--rv-rail` | charcoal | `#15161c` | The rail and the sign-in panel: the darkest surface in both themes |
| `--rv-charcoal-deep` | `#22242d` | `#0e0f13` | The current page in the rail |
| `--rv-charcoal-soft` | `#3a3d4b` | `#2a2d38` | Hover in the rail, the avatar, the pressed theme button |
| `--rv-stone-dim` | `#a9a69e` | same | Group labels in the rail |
| `--rv-ink` | charcoal | `#5563dc` | A pressed or hovered control with white words: button hover, the selected chip, the skip link, step numbers |
| `--rv-link` | accent | `#8b97f2` | Links and words in the accent |
| `--rv-primary` | accent | `#8b97f2` | Marks and lines in the accent: the current-page mark, ring arcs, sparklines, checkboxes, the violet rule of the sheet |
| `--rv-accent-deep` | `#3a47b5` | `#aeb7f6` | Links on hover |
| `--rv-accent-tint` | `#eceefa` | `#2b3050` | The import area while a file is dragged over it |
| `--rv-focus` | charcoal | `#ffffff` | The focus ring (white on the rail in both themes) |
| `--rv-danger-fill` | `#b3261e` | same | The face of a danger button, white words in both themes |
| `--rv-veil` | charcoal at 55 % | black at 60 % | Behind a dialog and the control drawer |
| `--rv-status-protected` | `#1b6e3c` | `#4fbf7a` | Protected, on the surface only, with an icon |
| `--rv-status-needs-attention` | `#8a5a00` | `#e0a93c` | Needs attention, on the surface only, with an icon |
| `--rv-status-not-protected` | `#b3261e` | `#ff8a80` | Not protected, on the surface only, with an icon |
| `--rv-status-not-checked` | `#5a5e6b` | `#aab0bd` | Not checked and not applicable, on the surface only |

Rules the tests enforce: every rule that sets a text colour also sets its background;
no rule draws text or a surface with a palette colour (the accent face of a button is
the one exception); gray is never text on the surface or the canvas; the link colour
is never text on the rail or on ink; the status colours and secondary text are text
on the surface only; a status is never shown by colour alone; the dark block
redefines roles only, and the block for the system theme holds the same values.

Type: the system stack (`system-ui`, Segoe UI, Roboto, Helvetica, Arial). Sizes 12,
13, 14, 15 (body), 16, 20, 24 and 28 px; the text wordmark is bold Helvetica or Arial.
Spacing 4, 8, 12, 16, 24, 32 and 48 px. Radius 8 px on controls and 12 px on cards and
tables. Two elevations (`--rv-shadow-1` for cards, `--rv-shadow-2` for dialogs).
Motion 150 ms ease-out on hover and focus only, off under `prefers-reduced-motion`.

## Themes

Light, dark, or the theme the system prefers. The root element carries the choice as
`data-theme` (`light`, `dark` or `system`, the default) and the `color-scheme` meta
follows it, so form controls and scrollbars match. The stylesheet holds the light
roles in `:root`, the dark roles in `:root[data-theme="dark"]`, and the same dark
roles in `:root[data-theme="system"]` under `prefers-color-scheme: dark`; the server
renders the attribute, so a page is never drawn in one theme and repainted in
another. Dark is a variant drawn from the brand charcoal, not an inversion: the rail
stays the darkest surface, the page is a blue-charcoal, the canvas lifts above it,
the shadows deepen and the veil darkens; the accent face of a button keeps the brand
accent, while links, marks, rings and sparklines take a lighter accent that reaches
4.5 to 1 on the dark surface. Every status keeps its icon and words in both themes.

The Pico variables are mapped to the roles in `:root`, and once more in
`revrook-retest.css` for `:root[data-theme]`: Pico writes its own light values for
`:root:not([data-theme="dark"])`, a rule of higher rank than `:root`, so with the
system theme on a system that prefers dark the text, surfaces and fields Pico draws
kept their light values on the dark roles (found in the rendered check of the charts
on Development). The second mapping has Pico's rank and comes later, so the roles win
whatever the theme; `base.html` always names one.

The switch (`_theme.html`) is a form of three real buttons, Light, Dark and System,
with the sun, moon and monitor icons; the pressed one carries `aria-pressed="true"`.
It sits in the rail above the sign-out button (its words alone from 1024 px: three
icons beside three words did not fit the 248 px rail, so `revrook-retest.css` hides the
icons there; below 1024 px the bar shows the icons alone) and beside the edition badge
on the signed-out pages, with the icons alone. A button posts
the form to `/theme` (`app/ui/site.py`); with script, `revrook.js` applies the theme
the moment the button is pressed and htmx posts the form with nothing swapped (the
server answers 204), and without script the page comes back in the new theme. The
choice is kept on the user row (`app_user.theme`, revision 0006, `app/theme.py`) so
that it follows the person to every browser, and mirrored in the `rv_theme` cookie (a
year, HttpOnly, SameSite=Lax, Secure under https) so that the sign-in page is drawn
in the same theme. Signed out, the switch sets the cookie only and the way back is
the sign-in page. With script, a post the server refuses (403 when the session ended,
422 for a value it does not know) or that fails puts the theme back to the one in use,
since nothing was remembered. The brand is the same lockup in both themes (The shell).

Non-text contrast. The boundary of a control (the border of a field, the focus ring,
the mark of a checkbox) and a graphic that carries meaning (the arc and the track of a
posture ring, the sparkline, the segments of a bar) reach 3 to 1 against what they
sit on in both themes; `tests/test_brand_contrast.py` lists those pairs. The strong
line is decoration and is kept out of them.

## The shell

`app/ui/templates/base.html` draws one of two shells. A page rendered with a `user` in
its context gets the app shell: the charcoal rail (`header.rv-header`) with the brand
lockup, the "Community Edition" badge, the grouped navigation of `_nav.html` and the
signed-in user with the sign-out button; then the page column with the stale-worker
banner, `main.rv-content` and the footer with the disclaimer. From 1024 px the rail is
a 248 px sidebar that stays in view, with the sign-out button on its own line under the
user name; below that it is a charcoal bar with the navigation as a scrolling strip, so
no menu is ever hidden behind a button, and below 600 px the bar drops the edition
badge (the footer still names the edition) so it never meets the sign-out button. The
strip (`div.rv-nav-strip`, like `div.rv-tabs-strip` around the tabs of a client) fades
the last visible link into its background at the right edge, so a person sees that it
goes on: the 48 px fade reaches its colour within 20 px, the strip ends in 48 px of
space (as wide as the fade, so with the last link in view nothing is under it), and
`revrook.js` marks the strip `data-scroll-end="true"` while nothing lies to the right
of what is in view, which hides the fade; without the script the fade stays. A link
that keyboard focus scrolls into view stops 48 px clear of the edge (`scroll-padding`).
The rules of this follow-up are in `app/static/css/revrook-retest.css`, loaded after
`revrook.css` so that they win by order; they belong in `revrook.css` at its next
rewrite.

A page without a `user` (sign-in, first run) gets the signed-out shell: the charcoal
panel with the stacked lockup and three lines about the product on the left, the
lockup in a row, the badge, the form and the footer on the right. Below 768 px the
panel becomes a short band above the form.

The brand lockup (`_brand.html`, `{{ b.lockup(brand_files) }}` or
`b.lockup(brand_files, "stack")`) is the rook mark in its cream tile beside, or above,
the wordmark as text (rev and rook, bold Helvetica or Arial). The mark is the approved
`logo-mark-512x512.png`, drawn on nothing, so the tile is the stylesheet's
(`.rv-mark`, `--rv-mark-tile`) and the lockup sits on the rail, on the sign-in panel
and on the surface of either theme; the composed logo files carry a charcoal surround
that showed as a lighter box on the darker rail of the dark theme, so they are not
drawn. The tile is 40 px in the bar, 48 px in the rail, 44 px in the signed-out header
and 72 px, then 128 px from 768 px, on the panel; the wordmark is 28 px in the rail
and on the panel (stone and gray, large text), 24 px in the bar, and the text and
link colours on the surface. Below 600 px the bar shows the tile alone, and the
signed-out header does so below 1024 px, where it shares its line with the badge and
the theme switch beside the panel (which still carries the whole lockup). Without the
mark file the wordmark alone is the brand, as before.

A page marks where it is with `nav` in its context: `home`, `clients`,
`profile-editor`, `integrity`, `explorer`, `settings`, `system` or `glossary`. The
link of that page carries `aria-current="page"` and the violet-blue mark. The links
are three groups: Work (Home, Clients), Evidence (the profile editor, the integrity
check and the Evidence Explorer) and Administration (Settings, System, Glossary).

The rail fold (`_rail.html`). From 1024 px one button at the top of the rail folds it
to its icons: a 72 px rail with the mark, one icon per link, the stacked icons of the
theme switch and the sign-out icon, so a wide table, a chart or a scene gets the
room. The words of every link, the user and the sign-out button stay in the page for
assistive technology (hidden the way the `rv-sr-only` heading is), each icon carries
its words as a tooltip (`title`, drawn by the server when the rail comes back folded
and set by `revrook.js` the moment it folds), the current page keeps its mark and the
button says what it does (`aria-label`, `aria-expanded`). It
is a real form that posts to `/rail` (`app/ui/site.py`): without script the page
comes back with the rail as chosen; with script `revrook.js` folds the rail the
moment the button is pressed and htmx posts the form with nothing swapped (the server
answers 204; a refused or failed post opens the rail again, since nothing was
remembered). The choice is a browser preference kept in the `rv_rail` cookie (a year,
HttpOnly, SameSite=Lax, Secure under https; `app/theme.py`, `RAILS`), read by
`render` into `rail` and drawn as `data-rail` on the body, so a page is never drawn
open and folded afterwards. Below 1024 px the rail is a bar and the form is not
drawn. Its rules are in `revrook-retest.css`, like the other follow-ups of the shell.

Icons come from the macro in `app/ui/templates/_icons.html`:
`{% import "_icons.html" as i %}` then `{{ i.icon("clients") }}`. Every icon is an
inline stroke drawing in the current colour, hidden from assistive technology, with
the words next to it carrying the meaning. An icon has one of four named sizes, so
the icons of a kind are the same size on every page (`--rv-icon-sm` to
`--rv-icon-xl`; `tests/test_icons.py`): `sm` (18 px) inside a button, a pill or a
field (sign out, add, search, the theme switch); `md` (22 px, the default) beside a
line of text (the navigation, list markers, the marks of the sources); `lg` (36 px)
the mark of a card (the import area, a small empty state, the drawer); `xl` (48 px)
the mark of an empty state that fills a page or a section. A number is never passed.
The marks of the evidence sources (`i.source_mark(code)`, `source_icon` in
`app/sources.py`) are the icon of the source's family (cloud, devices, backup,
network, training, leavers, mail, globe, list) in a canvas tile beside the name, on
the sources table of the evidence page and among the integrations of the home empty
state; never a vendor logo. Add an icon there, never as an image file
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

Empty state: `div.rv-empty` with its `xl` icon (`lg` in `rv-empty-small`),
`p.rv-empty-title`, `p.rv-empty-text` and the one action that fills it. It says what to do first, never only that nothing is
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

Toolbar: `form.rv-toolbar` is a canvas band that holds the controls of a list or of a
period: `div.rv-toolbar-search` (an icon over a search field and its button),
`ul.rv-chips` of `a.rv-chip` links (the one that applies carries
`aria-current="true"`; a count sits in `span.rv-chip-count`) and `p.rv-toolbar-note`
for one line of context. Every text inside the band declares the canvas as its
background, so a label never shows as a white box on it; secondary text is not used
there. Chips also make the pager (`div.rv-pager[role="navigation"]`, with
`span.rv-chip.rv-chip-off` for the way that does not exist).

Client header: `_client_nav.html` draws the header of every page of one client, the
link back to the list above the name, the actions the page gives in `client_actions`
(a path without its leading slash, the text and whether it is the primary one) and
the tabs. A page that gives no actions renders the name and the tabs alone.

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
  from the stored reports (`.rv-stat`, `.rv-spark`). The number is a link. The cards
  stand one to a row on a phone, two from 600 px and four from 1280 px, never three
  and one.
- The rookery (`.rv-rookery`), the signature of Home: one posture ring per client,
  the score inside, the band beside it, the controls that need work and the movement
  since the last report under it. A client whose evidence is too thin for a score has
  a dashed stone ring and a question mark, never a number that would read as a score.
- Needs attention (`.rv-attention`): the eight most urgent controls across every
  client, gate controls first, then what is not protected, by weight. Every row is the
  status pill, the control, the client and the reason beyond the status (old evidence,
  an open exception), and one action.
- Score over time (`.rv-chart`, the body of the card in `_trend_chart.html`): one
  line per client from the stored reports of the last 7, 30 or 90 days, up to six,
  labelled at its end and told apart by its dash pattern; every stored report is a
  mark on its line, a link to that report; a table under the chart carries every
  number, each date a link too. The chart is drawn twice (`ChartSize` in
  `app/ui/dashboard.py`, the `score_chart` macro of `_chart.html`): the wide drawing
  of 640 units, and below 600 px a narrow one of 320 units whose labels keep their
  size on a phone, with the clients named in a legend (`ul.rv-chart-legend`) under
  it. The range is a row of real submit buttons (`form.rv-range`, `?days=`). Controls
  by domain (`.rv-domains`): one stacked bar per domain across the whole card with
  the domain and its protected share above it, each segment a link to its row of the
  numbers, a legend of status pills, and every count in a table folded under "Show
  the numbers" (`details.rv-chart-data`, the same fold as the chart; the table sits
  in `div.rv-table-scroll` so a narrow phone scrolls the table, never the page). The
  two cards sit side by side from 1024 px, each at its own height (stretched to the
  taller one, the chart stood over an empty third of its card).
- Recent changes (`.rv-timeline`): the newest audit entries that changed a client,
  its evidence or its reports, with who did it and when (the exact time on hover).

States: a fresh installation shows one empty state with the three first steps and
one action; a client without evidence shows a dashed ring and "No evidence imported
yet"; a client whose evidence cannot be read today is listed in a warning strip above
the dashboard instead of stopping it; the attention list, the chart and the timeline
each have their own empty state that says what fills them. The page is
rendered whole on the server: there is no part that loads later, so there is no
loading state to show.

Charts are inline SVG drawn on the server with the role tokens only: the sparkline
and the ring arc in the accent, the lines in the text colour, the domain bars in the
status colours with the counts beside them, so nothing is told by colour alone. No
library, no image, nothing loaded from outside. How they answer the pointer and the
keyboard is the section Charts below.

## Charts

Every chart of the product is fed by data the application already stores, is drawn
on the server as SVG with a table of its numbers under it, and works without script:
a mark is a link to its report, a segment is a link to its list, a range is a GET
form, the title of a mark is its native tooltip. One first-party script,
`app/static/js/charts.js` (no library, nothing loaded from outside, same origin
under the content security policy), layers the interaction on what is in the page,
with its rules in `app/static/css/charts.css`, loaded after the stylesheet and its
follow-up and drawn with the role tokens only; the pure view models are
`app/ui/charts.py` and `app/ui/dashboard.py`, and `tests/test_charts.py` pins all of
it, each text pair of the chart stylesheet in both themes included.

The charts and what feeds each:

| Where | Chart | Data | Drills down to |
| --- | --- | --- | --- |
| Home, stat cards | Sparkline of the last twelve weeks (`.rv-spark`) | The stored reports and the clients that existed at the end of each week | The page the number leads to |
| Home | Score over time (`#trend`) | Every stored report of every active client in the last 7, 30 or 90 days (`Snapshot` rows) | The report behind each mark |
| Home | Controls by domain (`#domains`) | The live view of every client, controls by status | The row of the domain under "Show the numbers" |
| Clients | Clients by band (`#bands`) | The newest stored report of every client, by the band of the scoring model | The list narrowed to that band (`?band=`) |
| Client overview | Controls by status (`.rv-mix-bar`) | The live view of the client | The checklist narrowed to that status (`?status=`) |
| Client overview | Coverage by domain (`#domains`) | The live view of the client | The checklist narrowed to that domain and status (`?domain=`, `?status=`) |
| Evidence and imports | How old is each export (`#ages`) | The newest export of every source and the date it goes stale (`SourceRow`) | The row of the source in the Sources table |
| Report builder | Score over time (`#history`) | Every stored report of the client, over 90 days, a year or all of them (`?span=`) | The report behind each mark |

How a chart answers:

- Tooltip: a mark, a segment, a band or a week of a sparkline carries `data-tip`,
  the exact values in words written on the server (`Mark.tip`, `AgeBar.tip`,
  `BandCount.tip`, `SparkMark.tip`); the script shows them in one element
  (`.rv-tip`, rail-dark with white words in both themes, the first line bold) beside
  the mark under the pointer or the keyboard, and hides it on leave, blur and
  Escape. The element is fixed to the view, so a hidden tooltip near the right
  edge never widens the page, and a scroll or a resize moves it with its mark (a
  wheel that brings a mark under a still pointer keeps its tip). The same words
  are the `<title>` of the mark, so a screen reader hears them and the tooltip
  itself is hidden from it.
- Keyboard: the marks of one chart are one tab stop (`data-roving`); Left and Right
  move between them, Home and End to the first and the last, Enter follows the link,
  and Up and Down are left to the page, so it still scrolls while a mark has the
  focus. A sparkline is one tab stop too (`data-spark`): Left and Right walk its
  weeks. A
  focused mark grows (a scale about its centre, whatever its shape) and takes the
  focus ring as a stroke that keeps its width
  whatever the stretch of a bar (`vector-effect: non-scaling-stroke`).
- Range: the row of buttons above a score chart (`form.rv-range`, the `range_form`
  macro) is a GET form whose pressed button (`aria-pressed`) is the range drawn.
  With script the button asks `data-fragment` (`/charts/trend?days=30`,
  `/clients/{id}/charts/history?span=365`, `app/ui/fragments.py`) for the body of
  the card through htmx and swaps it into `data-target` in place, then writes the
  range into the address (`replaceState`) so a reload keeps it; the card says
  `aria-busy` while it waits and the drawing that arrives rises into place once
  (`.rv-chart-enter`, 180 ms, off under `prefers-reduced-motion`). The script reads
  the answer from the request events of htmx, not from its promise: only a success
  is swapped in and remembered in the address; any other status (the page's
  response handling would otherwise swap a 422 or a 500 body in as an answer, as
  the control drawer wants), or no answer at all, leaves for the page with that
  range, as the form would. A fragment asked for as a page redirects to the page
  that holds the chart with that range; signed out it answers as every page does; a
  range that is not known is a 422.
- Series: the legend of the Home trend becomes a row of pressed buttons
  (`button.rv-series`); not pressed, the line, its marks and its rows are hidden in
  both drawings (the `hidden` attribute, since an SVG group has no such property),
  and a series switched off stays off when another range is swapped in. With every
  client switched off the card says so (`data-all-off`) and how to bring a line back.
  Each client of the legend shows the key of its line (its dash with its mark shape)
  and how many reports the range holds for it.
- Few reports: a line joins two stored reports or more of the same client, and
  nothing is drawn that is not stored. Each line has its own mark shape (circle,
  square, diamond, triangle up, triangle down, cross; the `marker` macro of
  `_chart.html`), so clients are told apart where no line is drawn. A client with
  one report in the range and none before it is one larger mark in a dashed ring,
  keyed by its mark alone in the legend, and a note above the drawing
  (`sparse_note`, `.rv-chart-note`) says it in words: "One report per client in
  the last 30 days, so there is no line yet", or names the clients with one report
  beside the lines. A line that enters from the report before the range
  (`continues_from`) starts at the left edge with no mark there; it is keyed and
  drawn as a line, and the note names the report it comes from and its date. On
  Home the note invites the 90-day range; on the report builder it counts the older
  reports outside the span. No report at all is the empty state of the card.
- Announcement: after a range is swapped in, its summary (`data-chart-summary`: the
  range, the reports and the clients drawn) is read out through one polite live
  region, since focus stays on the pressed button.
- Drill-down: every link is a real address. A link into a folded table opens the
  fold and focuses the row; a segment of the overview opens the checklist with a
  third chip that names the narrowing (`a.rv-chip-narrowed`) and takes it away.
- Motion: 120 ms for a tooltip or a stepped-back segment, 180 ms for a swapped
  drawing, on a person's action only; nothing moves on load.
- Status: never colour alone. A segment, a bar and a band carry their words in the
  tooltip, the title and the table; the age bars take the state token of the export
  as their fill with the state in words beside them, and the stale date as a mark in
  the secondary text colour, which reaches 3 to 1 in both themes
  (`tests/test_brand_contrast.py`).

## Scenes

Three pages carry a scene drawn in the browser: the rookery skyline of Home, the
domain keep of a client overview and the rookery wall of the Evidence Explorer
([evidence-explorer-preview.md](evidence-explorer-preview.md)). Depth means the same
thing in every one of them: height is a measure, footprint is weight, status is shape
and colour together, and every word stays in the DOM. A scene adds a way of looking
at facts the page already shows and never replaces them: the rings, the bars and the
tables are the record, and without script, without WebGL 2 or with the scenes hidden
the page is exactly what the server drew.

How they are built. One first-party ES module, `app/static/js/scenes.js`, and one
stylesheet, `app/static/css/scenes.css`, linked by `base.html` with the asset version
on every page; the module looks for `[data-scene]` stages, and a page without one
imports nothing. With a stage, it checks for WebGL 2 first, keeps the stages that have
something to draw and puts the others away (a Home without a client, a browser without
WebGL 2: `data-scene-state="unavailable"`), and only then imports the pinned three.js
r186 that the Evidence Explorer already vendors (`app/static/vendor/three`,
`PINNED.json`, `tools/fetch_three.py`; nothing from a CDN). A scene reads its facts
from the data attributes the template renders on the cards or the bars of the page
(`data-client`, `data-score`, `data-band`, `data-insufficient`, `data-evidence`,
`data-needs-work`; `data-code`, `data-weight`, `data-count-<status>`), from the same
view model as the ring or the bar beside them, so the two can never disagree and no
request is made; the address a node opens (`data-href`) is accepted only as a path of
this site, one leading slash and nothing else, or the node opens nothing and the card
or the bar keeps its own link. The stage macro (`_scene.html`, `sc.stage(...)`) draws
the lead line and the hide button, the stage with its note, the turn and reset buttons
and the detail line (`aria-live`). The block is hidden in the HTML; where script runs
the stylesheet gives it its room at once (`@media (scripting: enabled)`, the note
"Preparing the scene" on the charcoal), so the cards and the bars under it never move
once the page is drawn, and without script, or when the module puts a stage away, no
empty box appears.

The rookery skyline (Home, `#rookery-scene`). One rook per client on a charcoal
yard, as tall as its score, crenellated like the mark: stone for a strong or a good
band, amber for fair, red for weak or critical; a wire rook where the evidence is
too thin for a score (the dashed ring of its card), a footprint where nothing is
imported yet, and a notch at its foot for every control that needs work. Pointing at
a rook, or at its card, names it in the hover line; a press chooses it, marks its
card with the violet rail and writes its facts in the detail line; Enter opens the
client. While every client is only a footprint the detail line says so and what to
do (import an export); with no client at all the stage is put away and Home keeps its
own empty state.

The domain keep (client overview, `#keep-scene`, in the Coverage by domain card). One
block per domain of the control library, as wide as its weight in the score, built of
its controls in layers from the foot up: protected, needs attention, not protected,
and not checked as wire, in the status colours of the bars. A heavy domain with red
layers stands out at once, which the flat bars tell only one at a time. A press
chooses a block and marks its bar with a line in the margin of the card (the row
itself does not move); Enter opens the checklist narrowed to that domain, the link
the bar already carries. More than six domains stand in two rows, more than eight
rooks likewise, so a row never runs so wide that every node is small.

How a scene answers. The home view fits the row to the stage: as near as the width
of the stage allows and never so near that the tallest node is cut off, measured
again when the stage changes shape (a folded rail, a turned phone) unless a person
has moved closer or away. A drag turns and tilts the yard; the buttons under it turn
it by a step or reset the view; with the canvas focused (an application, a scene) Left
and Right choose the next node and lean the yard a little towards it (never so far
that the row lines up behind it), the brackets turn it, plus and minus move closer and
away, Home resets, Enter opens the chosen node and Escape clears it. Nothing turns by
itself in any scene; under
`prefers-reduced-motion` every move is immediate, also when the setting changes
while the page is open. Frames are drawn only when something changed, never while
the page is hidden or the stage is out of view; leaving the page disposes every
geometry, material and the renderer, and `revrookScene` on each stage offers
`dispose()`, `mount()` and `info()` so a test can cycle a scene and read the
renderer's counts. The button above a stage closes the scenes in this browser
(`localStorage`, `rv-scenes`) and then offers to show them again: it names the action
it offers next, so it carries no pressed state as well; the detail and the tools go
with the scene, the cards and the bars stay. A lost graphics context stops the drawing with a note and resumes when
the browser restores it; a library that cannot be loaded leaves a note on the stage.
The ground is the brand charcoal in both themes, the same dark surface as the rail;
the colours on it are the dark-theme status values of `revrook.css`, which reach 4.5
to 1 on that ground. `tests/test_scenes.py` pins the module, the stylesheet, the
macro, the attributes and the routes.

## Clients

The clients list (`app/ui/templates/clients.html`, the pure functions of
`app/ui/clientlist.py`) is where the owner picks the client to work on next, and the
client overview (`client_overview.html`, `app/ui/overview.py`) is where they see
where that client stands before opening the checklist or a report. Both read the same
views, labels and snapshots as Home and the reports; nothing is stored and no rule of
evidence changes.

The list. One table (`table.rv-clients`) with the client name as the row heading, the
last stored report as a small posture ring beside its band and date, the controls of
that report by status as pills with their counts ("3 not protected", "7 need
attention", "1 not checked", or "All checked controls protected"), the date of the
newest evidence with its age and the number of exports, and the row actions. The
posture is read from the newest stored snapshot of each client with the same scoring
the report was made with (`last_report_of`), never from a check run on the list, so
the page stays one query for the clients and one for their newest snapshots. A client
without a report says so in words; a client without evidence shows the "No evidence
yet" pill.

Above the table a toolbar carries the search (by name, case-insensitive), the filter
chips with their counts (all, needs work, no report yet, no evidence yet), and the
density (comfortable or compact, `table.rv-table-compact`). Under it the card
"Clients by band" (`#bands`, `band_counts` in `app/ui/charts.py`): one bar per band
of the scoring model, in the accent, with the count beside it, for the clients the
search and the filter leave, each a link that narrows the list to that band
(`?band=strong` ... `?band=none` for the clients without a report; the chosen one
carries `aria-current` and a link shows every band again). The column headings of
the name, the last report and the newest evidence are sort links with `aria-sort`;
the first click on the score sorts the lowest first and on the evidence the newest
first, and a client without the value a column sorts by comes last whichever the
order. Fifty rows make a page (`.rv-pager`). Every one of these is a query parameter
of `GET /clients` (`q`, `show`, `sort`, `order`, `density`, `page`, `band`), read by
`read_query`, which refuses a value it does not know with a 422 like the checklist
filter does; a page number past the end gives the last page.

The table has no scroll box, so its heading stays sticky while the page scrolls.
Below 1024 px, where the sidebar ends, every row becomes a card (two to a row from
768 px, one on a phone): the heading row is kept for assistive technology only and
each cell names its column before its value. The empty list is
an empty state that says what a client is; a search or filter that matches nothing
is its own empty state with the way back to the whole list. The form that adds a
client is a card at the end of the page, and the primary action of the page header
leads to it.

The overview. The client header (`_client_nav.html`) gives the way back to the list,
the name, two actions (review the flagged controls, prepare a report for the period)
and the tabs. Under it the period toolbar (`form.rv-period`), then:

- Where the client stands (`#posture`): a large posture ring (`.rv-ring-large`, the
  same drawing as Home at 144 px) with the band, four facts (evidence coverage,
  controls that need work, exports to refresh, the movement since the last report)
  and the three summary sentences of the report (`#summary`). A client whose
  evidence is too thin shows a dashed ring and the lower bound in words.
- Controls by status (`#status-counts`): one stacked bar (`.rv-mix-bar`) and the
  count beside each status pill, with the way to the checklist; a segment of the bar
  opens the checklist narrowed to that status.
- Needs attention (`#needs-attention`): the eight most urgent controls of this
  client in the order of the report (gate controls first, then what is not
  protected, by weight), each with its status, the reasons beyond the status and
  one action; a link to the rest on the flagged checklist; an empty state that says
  what fills it.
- Coverage by domain (`#domains`): one stacked bar per domain of the control library
  with its protected share, its weight and its score, a legend of status pills and
  every number under "Show the numbers"; a segment opens the checklist narrowed to
  that domain and status (the Charts section).
- How fresh is the evidence (`#freshness`): the strip that names how many sources
  need a fresh export (or that every source is current) and the table of sources.
- Recent changes (`#recent-changes`): the audit entries of this client only, read
  with the same words as Home.

## Checklist and control detail

The checklist (`app/ui/templates/checklist.html`) is where the owner scans every
control of one client to find what to fix before a report, and the control page
(`control.html`) is where they read what was checked and write the four lines the
report prints. Both read the same rows, labels and results as before; nothing is
stored on either page except the notes, which were already saved as they are typed.

The checklist. Under the client header, the section head names the page and its
purpose, then a canvas band (`.rv-checklist-toolbar`) holds two chips with their
counts, all controls and the ones that changed or need a look (the one that applies
carries `aria-current="true"`), and the count line (`#checklist-count`), which also
says when no report exists yet to compare against. The table (`table.rv-checklist`)
has no scroll box, so its head stays sticky: the control is the row heading with its
id and "gate control" under it, the status a pill, the coverage and the date in
tabular figures, the owner, and the flags as a short dotted list (`ul.rv-flags`). A
row whose status changed since the last report carries the violet mark of the rail on
its heading cell, with the words "Changed since the last report" beside it. Below
768 px every row is a card and each cell names its column; a row with nothing to flag
drops that cell. The flagged view with nothing in it is an empty state that says what
would fill it and leads back to the whole list.

The control page. A kicker leads back to the checklist; the title is the control's
sentence, with its id, domain, gate and weight under it (`ul.rv-control-meta`). The
verdict band (`section.rv-verdict`, the signature of the page) shows the status as a
large pill beside the four evidence facts (dated, state, type, coverage) on the
canvas. From 1024 px the page splits 3:2: what was checked (the rule as a lead,
`p.rv-rule`, then what the check found and its notes) and the exceptions of this
control (owner, open or overdue as a pill, reason, compensating control, review date;
an empty state leads to the exceptions page) on the left, and the notes card on the
right, which stays in view while the person reads. The notes card holds the suggested
wording on canvas (`.rv-suggestion`), one `div.rv-field` per line with a help text
on "By when", the primary button, a "Saving" indicator (`.rv-notes-saving`, shown
while htmx posts, when the form carries `htmx-request`) and the `aria-live` status
line that receives "Saved at" or the refusal.

The control drawer. The checklist, the home page and the client overview carry a
closed native dialog (`_drawer.html`, `dialog.rv-drawer`) at the right edge of the
page. A link to a control marked `data-drawer` (the control of a checklist row, the
control and the Open button of a "Needs attention" row) opens it: `revrook.js`
shows the dialog as a modal, so Escape closes it, Tab stays inside and the page
behind is inert, then asks htmx for the control with the drawer as its target
(`HX-Target: control-drawer-body`), which the server answers with
`_control_drawer.html`, the control head and body without the shell. The page and
the drawer share `_control_body.html`, so the verdict band, what was checked, the
exceptions and the autosaved notes are the same in both. The bar of the drawer is a
canvas band with the word Control and the Close button (a `method="dialog"` form);
under it the skeleton shows while the control loads (`aria-busy` on the dialog),
then the head, whose kicker names the client and leads to the control as a page
("Open as a page", for a bookmark or a second tab), the title (which names the
dialog and takes focus) and the body in one column. Closing returns focus to the
link. From 768 px the drawer is 38 rem wide beside the veiled page; on a phone it
is the whole screen. A click with a modifier key, a middle click, a browser without
dialogs, a page without htmx or a request that fails leave the link as it is: the
control page.

## Evidence imports, the profile editor and the integrity check

The evidence page of one client (`app/ui/templates/evidence_imports.html`) is where
the owner sees which export to refresh before a report and what was imported; the
profile editor (`profile_editor.html` and its result part
`_profile_editor_result.html`) is where a technician turns a vendor export into
evidence in five steps; the integrity page (`evidence_integrity.html`,
`app/ui/evidence.py`) proves that nothing in the log changed after it was written.
All three read the same rows, labels and results as before; no behaviour, data or
evidence rule changed.

The evidence page. Under the client header, whose one action leads to the profile
editor, the section head names the page and the rule of freshness, then the evidence
verdict (`section.rv-verdict`, the band of the control page): the state of the
client's evidence as one large pill (every export current; `1 stale`; `1 expired, 2
not imported`; no evidence yet) beside four facts (sources, current, to refresh,
items imported), computed by `evidence_facts` in `app/ui/viewmodels.py` from the
source rows the page shows. Then four parts, each with a section head at h3:
"How old is each export" (`#ages`, `age_bars` in `app/ui/charts.py`), one bar per
source on one shared scale with the age of its newest export in words, the state
token of the export as its fill and the date it goes stale as a mark, each bar a link
to the row of the source in the Sources table (the Charts section);
"Refresh these exports", an ordered list (`.rv-refresh`, the oldest export first and
then the sources never imported) whose numbers are the order to work in, with the
state pill, the date of the newest export and what to do, or a success strip when
every export is current; "Sources", a table of every source a control reads with
its state, newest export, the date it goes stale and the exports kept; and
"Everything imported", a table of every item with its id under the source, its type,
date, state, revisions and size, or an empty state that leads to the profile editor.
Dates are `.rv-date` (tabular figures, never wrapped); counts are `.rv-numeric`.

The profile editor. The page header names the job; without a client the page is one
empty state that leads to the clients page. The form is five steps, each a card
(`fieldset.rv-step` with its legend floated across the card as the title, or
`section.rv-step` with `h2.rv-step-title` for the preview, which has no controls),
numbered with the circle of the Home steps because the steps are a sequence: the
client and the source side by side and the file in the import area
(`label.rv-dropzone`, whose hint names the limit and that nothing is stored until
the import); the mapping, one `div.rv-field` per column of the source in the
`.rv-mapping` grid; the preview of the first rows in a scroll region, with the UTC
note as a status strip and an empty state when the file has no data rows; the
profile name with a help text; and the import with the saved profile and the capture
time side by side, or an empty state that says to save a profile first. Every button
has an indicator beside it (`.rv-editor-busy`, named by `hx-indicator`, shown while
htmx posts). Missing required columns and a refused file stay `.rv-errors` with
`role="alert"`; a saved profile is a status strip; an import is a result card
(`.rv-import-result`) with the strip, three facts, the counts, the controls that read
the export (`.rv-import-reach`, each a link to its control page, with the note that
the other controls keep their status until their own export is imported) and the way
to the checklist and the evidence page of the client. Step 3 is always there, with an
empty state while no row can be shown, so the numbers never skip. Before any file is
read the result area is a small empty state that says what to do. Opened from the
evidence page or a control page, the editor carries the client (`?client_id=`).

The integrity page. The page header carries the purpose; before a check the page is
one empty state whose action is the check (nothing else is on the page, since the
check is what fills it); after a check the header's action is "Check again". The
result is the verdict band (all chains intact, or how many of how many are broken)
beside four facts (chains checked, records, broken, the time of the check), then the
table of every client's chain (`table.rv-chains`): the result as a pill, the records,
the hash of the latest record in `code.rv-hash` and the problem. A broken chain
carries the not-protected mark on its heading cell beside the words of its pill. An
installation without records is an empty state that leads to the profile editor. The
alert under the table says what the check proves and what it cannot.

Tables that carry `rv-table-cards` (the sources, the items, the chains) become
cards below 768 px like the clients list and the checklist: the heading row stays
for assistive technology, each cell names its column through `data-label`, numbers
align left and an empty cell is dropped.

## Exceptions and reports

The last six kinds of page: the exceptions register (`exceptions.html`), the report
builder (`reports.html`), the report page (`report.html`), the export history
(`exports.html`), the settings and the glossary (`settings.html`, `glossary.html`,
`app/ui/site.py`), the system page (`system.html`, `app/ui/system.py`) and the
problem page (`problem.html`, rendered by `problem` in `app/ui/common.py`). All read
the same rows and views as before; no behaviour, data or evidence rule changed. The
API and the CSRF check keep their JSON refusals; only the page a person sees changed.

The exceptions register. Under the client tabs, the section head names the page
and its rule (an exception never changes a status). Then the verdict band of the
control page: how the register stands as one pill (how many are past their review
date; open with none overdue; no open exception) beside four facts (open, overdue,
closed, the next review date), computed in the template from the rows the page
shows. The table (`table.rv-exceptions`, with `rv-table-cards`) lists the open
exceptions first with the earliest review date at the top: the control with its id
under it, the owner, the reason and the compensating control in a column of their
own, the review date, the state as a pill and the small quiet button that closes an
open one; a closed row is quieter. Without a row the page shows an empty state
whose action leads to the form. The form to add one is a card
(`section.rv-exception-card`): the control, the owner beside the review date, the
reason, the compensating control, each with its help text, and the one primary
button; a refusal stays `_errors.html` above the fields. Adding or closing one
redirects to the register with `?done=added` or `?done=closed`, which draws a
success strip (`#exceptions-message`) under the section head, because a message in
the page itself would not survive the redirect of the form.

The report builder. Under the section head, a success strip (`#builder-message`)
when the details form was posted without script and came back with `?saved=1`.
Three numbered step cards (`section.rv-step` with
`h3.rv-step-title`, the circle of the Home steps, because the steps are a sequence):
the period, two date fields side by side with the quiet button and the period
beside it; the details, the preparer, the plan with its help, and the topics of the
insurer in `fieldset.rv-topics`, one row each (`div.rv-topic`) with the checkbox
beside the owner field, then the quiet save button with the "Saving" indicator
(`.rv-notes-saving`, shown while htmx posts the form) and the status line
(`#details-status`, `aria-live="polite"`) that receives "Saved at" or the refusal;
and the one primary action of the page, making the report. Then "Score over time"
(`#history`, `_history_chart.html`), the score of the client at every stored report
over 90 days, a year or all of them, each a mark that opens the report (the Charts
section). Then "Reports made before", a table (`table.rv-snapshots`) of period,
pack date and the way to each report, or an empty state that says to make the
first one.

The report page. The control head gives the way back to the builder, the title and
the facts of the report (period, pack date, snapshot). Then the export readiness as
the verdict band: "Ready to export" or how many things to fix first, beside the
controls, the open exceptions, the data sources and the preparer. Under it, from
1024 px side by side (`div.rv-report-layout`): the sheet and the side column. The
sheet (`article.rv-sheet` on the canvas of `div.rv-sheet-band`) is the signature of
the page: a white sheet with the elevation of a dialog, drawn with the same facts
and rules as the cover of the exported file (`app/reports/report.css`): the running
head with the business and the client, the business name at 28 px, the subtitle,
the cover facts (client, period, prepared by, generated, pack date, data sources),
the violet rule, the summary lines (`#summary`) and the controls by status as pills
with their counts; a business name that is not set shows where it will be. The side
column holds the problems to fix first (`#problems`, `.rv-errors`) or the success
strip, and the card of the two reports (`ul.rv-kinds`), each with its name, what it
is for, the quiet preview button and the primary export button.

The export history. The section head and the success strip after an export, then
the table (`table.rv-exports`, with `rv-table-cards`): when, the report, the file
and the SHA-256 in `code.rv-digest` (which breaks anywhere, so a card on a phone
never grows wider than the page), the size, who exported it and the small download
button; or an empty state that leads to the builder. Below 1024 px the rows are
cards one to a row, like the clients list (`revrook-retest.css`): with the seven
columns in 704 px at 768 px the file name and the digest broke into columns of six
letters.

Settings. The page header with the purpose, the success strip and the errors, then
the form card: the business name and the reminder address, each with a help text
that says what it does and whether a mail relay is set, and the one primary button.
Under the section head "Fixed by the rules and the installation", the read-only
facts as cards two to a row from 1024 px (`div.rv-readonly`): the disclaimer as a
lead (`p.rv-quote`), the retention and limits as facts, the weights of the domains
as a table with the ruleset in its subtitle, and the users as chips
(`ul.rv-users`, the first letter as the mark) with the mapping policy under them.

System. The page header with the version and the role, the success strip after a
deletion, then the worker as the verdict band (`#worker-status`, the label of
`app/system.py` as the pill) beside the newest heartbeat, when the banner appears,
the number of schedules and the role of this process. The schedules are a table
(`table.rv-schedules`, with `rv-table-cards`) with the enabled state as a pill and
the runs as dates, or an empty state that says the worker adds them when it
starts; the cron expression never wraps, and from 768 px to 1023 px the rows are
cards two to a row. Two cards side by side from 1024 px: the reminders and outside services as
a list (`ul.rv-services`) of a pill (set, not set, on, off) and its sentence, and
the data export with its primary button and the way to the integrity check. The
deletion of a client is a card with the not-protected rail (`.rv-danger-card`):
one `details.rv-confirm` per client whose summary is the quiet button and whose
body holds the field to type the name and the danger button; opened, the summary
is the pressed button, white on charcoal (Pico coloured it grey, and on a touch
screen the hover stays after the tap).

Glossary. The page header, then one card (`dl.rv-glossary`): from 768 px each term
sits beside its meaning, on a phone above it. The closing sentence is an alert that
says what a report is.

The problem page. A refusal a person can read (404, 409, 422) is one card
(`section.rv-problem`, `role="alert"`): the status code as a 28 px figure in
violet-blue (`p.rv-problem-code`, with "Status" for assistive technology), the
title as the `h1`, the message, the details where there are any, one line that says
what to do, and two ways back, Home as the primary button and the clients list as
the quiet one. An address no page answers (404) and a method a page does not take
(405) get the same page, in the signed-out shell when nobody is signed in; under
`/api/`, the probes and `/static/` the answer stays JSON. The htmx fragment of the
same refusal is unchanged.

## Floors every page keeps

- Works at 390, 768 and 1440 px without horizontal overflow.
- A 3 px focus ring on every control (white on charcoal), a label on every field,
  one `h1` and one `main`, and no element inside a `<p>` that a browser would close
  early (`tests/html_structure.py`, see [docs/testing.md](testing.md)).
- Empty, loading, error and success states designed; copy in plain words, active
  voice, sentence case.
- No external font, image, script or style; no tracking.
