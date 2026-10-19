# Testing notes (phase 9)

How to run the tests is in `docs/development.md`. This page records what the page
tests of phase 9 measure and how.

## Page render time

Acceptance check 5 of phase 9: a page renders in under 500 ms of server time with
100 clients. `tests/test_ui_routes.py::test_page_render_stays_under_half_a_second_with_100_clients`
seeds 100 clients (one with the six generic fixtures, a report and an export), asks for
each page once so its template is built, then times the second request of each page
through the application itself (httpx `ASGITransport`, no network, no browser).
The pages are the client list, the overview, the checklist, the evidence page, the
report builder and the report page. Every one must stay under 0.5 seconds; the test
prints the slowest page and its time, which shows in the CI log.

Hardware: the measurement is only meaningful on the machine that ran it, so it is
recorded here and not assumed.

| Where | Machine | Slowest page with 100 clients |
| --- | --- | --- |
| CI check on a pull request | GitHub-hosted `ubuntu-latest` runner, with the PostgreSQL 16 service container of the workflow | See the line `phase 9, 100 clients: slowest page ...` in the log of the run named in the delivery report |

The time is the time of the application and its database queries on a small database.
It does not include the browser, the network or the first request of a page (which
builds its template). A slower machine needs a looser limit, not a change of the
check: the limit is `MAX_SECONDS` in the test.

## What the page tests cover

- every page and every state-changing route answers someone who is not signed in with
  a redirect to the sign-in page, and a post without the CSRF token with 403;
- a client goes from the period picker to an exported review through the pages
  (`scripts/e2e/phase_09.sh` does the same against the compose stack in check 9);
- every status on a page is an icon and its words;
- the checklist filter keeps exactly the rows that changed or need a look;
- the evidence page names the export to refresh, the oldest first;
- an address that cannot be used is a 4xx, never a 500, and an export of another client
  is a 404 (`tests/test_phase9_carryovers.py`).
