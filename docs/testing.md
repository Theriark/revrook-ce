# Testing notes (phase 9)

How to run the tests is in `docs/development.md`. This page records what the page
tests of phase 9 measure and how.

## Page render time

Acceptance check 5 of phase 9: a page renders in under 500 ms of server time with
100 clients.

What is measured. `tests/test_ui_routes.py::test_page_render_stays_under_half_a_second_with_100_clients`
seeds 100 clients: one with the six generic fixtures, a report and an export, and 99
more with one evidence item each (the six generic sources taken in turn), so the
database holds 105 evidence items and every client in the list has evidence. It asks
for each page once so its template is built, then times the second request of each
page with `time.perf_counter()` around the request, through the application itself
(httpx `ASGITransport`, no network, no browser). The time is the time of the
application and its database queries; it does not include a browser, the network or
the first request of a page. The pages are the client list, the overview, the
checklist, the evidence page, the report builder and the report page. Every one must
stay under 0.5 seconds (`MAX_SECONDS` in the test).

Where it runs. In CI the test runs in job `3 - pytest with PostgreSQL 16 and coverage
thresholds` of `.github/workflows/ci.yml`, on a GitHub-hosted `ubuntu-latest` runner
with the PostgreSQL 16 service container of the workflow.

Where the number is. The test prints, in the log of that job:

```text
phase 9, 100 clients, 105 evidence items: slowest page <path> <seconds> s on <runner name>
phase 9 page time <path> <seconds> s        (one line for each page)
```

and, on GitHub Actions, the same first line as a notice annotation titled
`Page render time` on the run. The measurement is only meaningful on the machine
that ran it, so a number is recorded here only when it was read in the log of a
named run:

| Run | Machine | Slowest page with 100 clients |
| --- | --- | --- |
| Not yet recorded | GitHub-hosted `ubuntu-latest` runner, PostgreSQL 16 service container | The delivery report of each phase names the run whose log it was read from |

A slower machine needs a looser limit, not a change of the check.

## Structure of the pages and reports (no axe)

Acceptance check 6 of phase 9 asks for contrast plus axe or html5lib. axe-core needs
a browser and html5lib is not in the development lock, so neither is run. A new
dependency was not added for this: `tests/html_structure.py` reads each page with
`html.parser` of the standard library and lists what is wrong.

What it checks, on every page:

- every element that is opened is closed in order, and nothing is closed that was
  not opened; a paragraph holds no block element;
- the root element has a `lang` attribute; there is exactly one `h1` and one `main`;
- every `id` is used once, and every `label for`, `aria-labelledby`,
  `aria-describedby`, `aria-controls` and `hx-target` names an `id` that exists;
- every `img` has an `alt` attribute;
- every `input`, `select` and `textarea` a person fills in has a label (`label for`,
  a label around it, or `aria-label` / `aria-labelledby`).

Where it runs (`tests/test_phase9_part2.py`):

- every phase 9 page, read from the routes of the application, plus the home page,
  the evidence integrity page, the profile editor and the 404 page, signed in, for a
  client with normal data and a client whose name, notes, plan, owners, exception
  and MSP name are HTML markup; the preview and the download of the review and the
  pack are checked the same way;
- the review and the pack of the worked clients A, B and C, and of client B with
  hostile text in every field a person writes;
- the sign-in and first-run pages, rendered from their templates.

What it does not check: colour contrast (`tests/test_brand_contrast.py` and
`tests/test_report_contrast.py` do), the order of the headings, focus order, how a
screen reader announces a page, and anything a browser decides when it lays out the
page. Those need a browser and are left to the human QA of the phase.

## What the page tests cover

- every page and every state-changing route of phase 9, read from the routes of the
  application, answers someone who is not signed in with a redirect to the sign-in
  page, and a post without the CSRF token with 403;
- a client goes from the period picker to an exported review through the pages
  (`scripts/e2e/phase_09.sh` does the same against the compose stack in check 9);
- every status on a page is an icon and its words;
- the checklist filter keeps exactly the rows that changed or need a look;
- the evidence page names the export to refresh, the oldest first;
- an address that cannot be used is a 4xx, never a 500; an export of another client
  is a 404 (`tests/test_phase9_carryovers.py`), and a report of one client opened,
  previewed or exported under another client is a 404 (`tests/test_phase9_part2.py`);
- an autosave that is refused (the client was deleted, the session ended, the text
  is too long) shows its reason in the status line of the form instead of the last
  "saved" message;
- a note is counted with LF line breaks, as the browser counts it for `maxlength`,
  although the form sends CRLF;
- a second click of "Make the report" within 30 seconds opens the report the first
  click made instead of storing a second snapshot.
