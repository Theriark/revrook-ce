# Security review (phase 11)

The checklist of the plan, run by the development crew on revrook CE as it stands after
phase 10: authentication, CSRF, uploads, formula injection, XSS, secrets,
pseudonymisation, retention, rate limits and resource limits. Each item says what was
checked, the result, what was fixed or recorded, and the test that keeps it true. A test
is named as `file::function` so that `tests/test_security_review.py` can check that it
exists. Written for this repository only: the design is in `docs/security.md`, the
limits in `docs/operations.md`.

**What this is.** A review of the code and the running application by reading it and by
automated tests that start the real application against PostgreSQL, with synthetic data.
**What it is not.** It is not a penetration test, not an audit by an outside party and
not a certification; nothing in revrook claims one. Human product QA is separate and
stays with the founders.

Severity: High (a stranger can read or change data, or take over an account), Medium (a
signed-in user or a burst of requests can stop the service, or a control is missing
that the plan requires), Low (a weakness that needs access or luck, or a limit that is
known and stated). The result of the review is the table of findings at the end: **no
finding of High or Medium severity is open.**

## 1. Authentication

**Checked:** the first-run page closes once a user exists; passwords are hashed with
Argon2id (12 to 256 characters) and an unknown user costs the same hash check; five
failed sign-ins lock the account for five minutes, even for the right password; the
session is a signed, HttpOnly, SameSite=Lax cookie (Secure over https) that lasts 12
hours; an API token is random, stored only as a SHA-256 hash, can be revoked and is
limited per token; every route under `/api/v1` needs a valid token, and the session
cookie is not accepted there; a burst of parallel sign-ins cannot use up the database
connections.

**Result:** sound after one fix. N3 (Medium): a database connection was held while
Argon2 checked a password with nothing in front of it, so many parallel sign-ins could
use up the pool. Fixed: at most four sign-ins are checked at once per process, the
others get 429 with `Retry-After: 5` and nothing is checked or written. Recorded as
Low: a signed cookie cannot be revoked before it expires (no session table; HttpOnly,
12 hours); an attacker who knows the administrator name can lock that account for five
minutes at a time (the cost of the lockout); an account name can be told from the
lockout (N2, the installation holds a few accounts that the MSP made itself).

**Test:** `tests/test_security_review.py::test_every_api_route_refuses_a_token_that_is_not_valid`
(every API route is read from the application and called with a wrong token),
`tests/test_security_review.py::test_five_wrong_passwords_lock_the_account_even_for_the_right_one`,
`tests/test_security_review.py::test_a_password_over_the_length_limit_is_refused_without_a_hash`,
`tests/test_security_review.py::test_a_sign_in_over_the_gate_is_told_to_wait_and_nothing_is_checked`,
`tests/test_security_review.py::test_the_gate_is_released_after_every_sign_in`; and
`tests/test_auth_flow.py`, `tests/test_api_access.py`, `tests/test_security.py`.

## 2. CSRF

**Checked:** the check is a dependency of the whole application, so no route can leave
it out; every state-changing page route (POST, PUT, PATCH, DELETE) refuses a request
without the token of the session with 403; the token comes from the form field or the
`X-CSRF-Token` header and is compared in constant time; a cookie signed with another key
is refused; the token is renewed at sign-in and sign-out; only the API skips the check,
and only with a Bearer token, which a third-party page cannot send.

**Result:** sound after one fix. N5 (Low): a Bearer header on any path skipped the check,
also on a page that uses the cookie. Not exploitable from another site (a page cannot
set `Authorization` without a CORS preflight, and revrook sends no CORS headers), but it
was wider than it needed to be. Fixed: only a path under `/api/` is exempt.

**Test:** `tests/test_security_review.py::test_every_state_changing_page_route_refuses_a_request_without_a_token`
(the routes are read from the application),
`tests/test_security_review.py::test_a_bearer_header_does_not_exempt_a_page_from_the_csrf_check`,
`tests/test_security_review.py::test_the_api_needs_a_token_and_not_a_csrf_token`,
`tests/test_security_review.py::test_the_session_cookie_is_not_a_credential_for_the_api`,
`tests/test_web_security.py::test_a_bearer_header_does_not_skip_the_csrf_check_of_a_page`.

## 3. Uploads

**Checked:** an upload is refused by its declared size before the body is read (413),
and an upload without a size is refused (411); the name of an uploaded file is never
kept, files are stored under the SHA-256 of their content in a folder per client, and
a storage key that is not exactly that layout is refused; a file that is not text
(NUL bytes), has no known header or has too many rows is refused with a message, not an
error; a personal identifier in a file is replaced before anything is stored; a raw
file is kept only when `RAW_RETENTION_DAYS` is above zero.

**Result:** sound. No finding. The cap of other request bodies is item 10.

**Test:** `tests/test_security_review.py::test_an_upload_over_the_limit_is_413_and_one_without_a_size_is_411`,
`tests/test_security_review.py::test_the_name_of_an_uploaded_file_is_never_kept`,
`tests/test_security_review.py::test_a_file_that_is_not_text_is_refused_not_a_500`; and
`tests/test_limits.py`, `tests/test_importer_hardening.py`, `tests/test_evidence_files.py`.

## 4. Formula injection

**Checked:** a text cell of the data export that starts with `=`, `+`, `-`, `@`, a tab
or a carriage return gets a leading apostrophe, so a spreadsheet does not run it; the
export holds no free text typed by a person; text kept in a fact has the same
protection since phase 3; a number is never changed.

**Result:** sound. No finding.

**Test:** `tests/test_security_review.py::test_a_cell_that_would_run_as_a_formula_gets_an_apostrophe`,
`tests/test_security_review.py::test_the_export_defuses_a_client_name_that_starts_like_a_formula`
(through the API and a real zip); and `tests/test_operations.py`.

## 5. XSS

**Checked:** every page is rendered with Jinja2 autoescape; no template uses `|safe` or
turns escaping off, and trusted markup is built in exactly two places (the charts and the
report style sheet); the content security policy is `default-src 'self'` with no inline
script or style, and the report preview forbids everything but its own style; a client
name, a note, an owner or an exception text that holds `<script>` or an attribute breaker
comes out escaped on every page and in the report preview; texts that can reach a report
refuse bidirectional controls and zero-width characters.

**Result:** sound. No finding.

**Test:** `tests/test_security_review.py::test_a_hostile_client_name_is_escaped_on_every_page`,
`tests/test_security_review.py::test_no_template_turns_escaping_off`,
`tests/test_phase11_carryovers.py::test_no_source_file_holds_a_hidden_or_reordering_character`;
and `tests/test_reports.py`, `tests/test_phase10_carryovers.py`.

## 6. Secrets

**Checked:** `SECRET_KEY`, `FERNET_KEY`, `DATABASE_URL`, the mail password and the
metrics token stay out of the representation of the settings, and a bad environment is
reported by variable name without repeating a value; an API token and a password exist
only as hashes in the database, and the audit trail holds the 12-character prefix of a
token and nothing more; no file of the repository holds a token, a private key or a
cloud key that looks real; `HEARTBEAT_URL` is never logged; the metrics token is
compared in constant time and the path answers 404 without it.

**Result:** sound after documentation. Recorded as Low: `scripts/restore_check.sh`
hands the database URL to the container as an environment argument, visible in the
process list of the host while the check runs (documented in `docs/operations.md`);
`GET /metrics` has no rate limit, so the length of its token (32 random characters) is
its only protection (documented there too).

**Test:** `tests/test_security_review.py::test_secret_settings_stay_out_of_the_repr_of_the_settings`,
`tests/test_security_review.py::test_a_bad_environment_is_reported_without_repeating_its_values`,
`tests/test_security_review.py::test_a_token_and_a_password_are_stored_only_as_hashes`,
`tests/test_security_review.py::test_no_file_of_the_repository_holds_a_secret_that_looks_real`;
and `tests/test_settings.py`, `tests/test_crypto.py`.

## 7. Pseudonymisation

**Checked:** each client has its own random 32-byte key, stored encrypted with
`FERNET_KEY`; user and device identifiers are replaced by a keyed hash of that key
before anything is stored, so the same person has different pseudonyms at two clients;
a stored value that still looks like an email address refuses the upload; deleting the
client deletes the key and with it the ability to reverse a pseudonym; the data export
leaves out accounts, tokens and typed text.

**Result:** sound. No finding. The limit stays as stated in `docs/security.md`: a name
typed into a note by a person is free text and is not pseudonymised.

**Test:** `tests/test_security_review.py::test_user_names_are_replaced_before_anything_is_stored`
(a search of every row of every table); and `tests/test_pseudonym.py`,
`tests/test_importers.py`.

## 8. Retention

**Checked:** a raw file is never written with the default `RAW_RETENTION_DAYS=0`; a kept
file is removed exactly when its retention date has passed, as an audited event;
snapshots and exports older than `PACK_RETENTION_MONTHS` go; deleting a client removes
its rows, its files, its draft notes and its key, and leaves the audit entry and the hash
chain record, which hold ids, hashes and counts only.

**Result:** sound. No finding.

**Test:** `tests/test_security_review.py::test_a_kept_file_goes_when_its_retention_ends_and_with_its_client`;
and `tests/test_evidence_store.py`, `tests/test_evidence_deletion.py`,
`tests/test_operations.py`.

## 9. Rate limits

**Checked:** the API allows 120 requests a minute per token and answers 429 with
`Retry-After`; the sign-in lockout (five failures, five minutes) and the sign-in gate
(four checks at once, then 429 with `Retry-After: 5`) hold; a snapshot request is
queued once however often it is sent.

**Result:** sound. Recorded as Low: the API limit and the sign-in gate live in the memory
of one process, so with several web processes each applies its own; revrook CE runs one.

**Test:** `tests/test_security_review.py::test_the_api_refuses_a_request_over_the_limit_with_retry_after`,
`tests/test_security_review.py::test_the_gate_lets_in_up_to_its_limit_and_frees_a_place_on_leave`,
`tests/test_phase11_carryovers.py::test_two_snapshot_requests_at_once_queue_one`; and
`tests/test_ratelimit.py`.

## 10. Resource limits

**Checked:** the numbers that bound what one request can cost, and that each one is
enforced and refused with a readable status:

| What | Limit |
| --- | --- |
| An evidence upload | 20 MiB by default (`IMPORT_MAX_BYTES`), refused before it is read |
| Rows of one imported file | 200,000 |
| Any other request body | 1 MiB (413; any Transfer-Encoding, with or without a Content-Length, is 411) |
| An id in an address or a body | 1 to 9223372036854775807, else 422; a value the database still refuses is 422 |
| A report period | 400 days, not in the future (422) |
| The data export | 256 MiB of CSV text before compression, streamed (413) |
| API requests | 120 requests a minute per token |
| Sign-ins checked at once | 4 per process |
| A password | at most 256 characters |

**Result:** sound after fixes. Medium, fixed: only evidence uploads were capped, so any
other POST body could be as large as the sender liked (now 1 MiB for every POST, PUT,
PATCH and DELETE); the data export was built whole in memory (now streamed through a
64 KiB buffer into a temporary file and capped at 256 MiB). Low, fixed: an API id
past 2^63 - 1 reached the database and gave a 500 (now bounded in the route, with a
handler that turns a database data error into 422 as a net, and logs only the class of
the error). A report period over 400 days is refused with 422 and is now tested over
HTTP. Medium, fixed after the independent review (P11-11): a request that carried
`Transfer-Encoding: chunked` next to a small `Content-Length` passed the size check,
because the HTTP parser (h11) frames the body by Transfer-Encoding and uvicorn hands
both headers on; any Transfer-Encoding is now refused with 411, and the test sends the
request through a real uvicorn socket.

**Test:** `tests/test_security_review.py::test_the_resource_limits_are_the_documented_numbers`,
`tests/test_phase11_carryovers.py::test_an_id_past_the_database_range_is_refused_never_a_500`,
`tests/test_phase11_carryovers.py::test_a_data_error_that_gets_through_is_422_not_500`,
`tests/test_phase11_carryovers.py::test_a_request_body_over_one_mebibyte_is_413_before_anything_reads_it`,
`tests/test_phase11_carryovers.py::test_the_export_is_the_same_when_it_spills_to_disk_in_tiny_chunks`,
`tests/test_phase11_carryovers.py::test_an_export_over_the_cap_is_413_and_is_not_audited`,
`tests/test_phase11_carryovers.py::test_a_report_period_over_400_days_is_422_and_400_days_is_not`,
`tests/test_limits.py::test_a_body_over_the_general_limit_is_refused_with_413`,
`tests/test_limits.py::test_a_chunked_body_with_a_content_length_is_refused_over_a_socket`,
`tests/test_limits.py::test_a_transfer_encoding_is_refused_with_411_whatever_the_length_says`.

## Findings

| ID | Item | Severity | What | Status |
| --- | --- | --- | --- | --- |
| N3 | Authentication | Medium | Parallel sign-ins could use up the database connections | Fixed |
| P11-1 | Resource limits | Medium | Request bodies other than uploads had no size cap | Fixed |
| P11-2 | Resource limits | Medium | The data export was built whole in memory | Fixed |
| P11-3 | Resource limits | Low | An API id past 2^63 - 1 gave a 500 | Fixed |
| P11-11 | Resource limits | Medium | A chunked body with a small Content-Length passed the size check | Fixed |
| N5 | CSRF | Low | A Bearer header on a page skipped the CSRF check | Fixed |
| N2 | Authentication | Low | An account name can be told from the lockout | Accepted |
| P11-4 | Authentication | Low | A signed cookie cannot be revoked before it expires (12 hours) | Accepted |
| P11-5 | Authentication | Low | Five wrong passwords lock an account for five minutes, which an attacker can repeat | Accepted |
| P11-6 | Rate limits | Low | The API limit and the sign-in gate are per process | Accepted |
| P11-7 | Resource limits | Low | A 500 is produced outside the middleware and has no security headers | Accepted |
| P11-8 | Secrets | Low | `scripts/restore_check.sh` shows the database URL in the host process list while it runs | Documented |
| P11-9 | Secrets | Low | `GET /metrics` has no rate limit; its token length is its protection | Documented |
| P11-10 | XSS | Info | A byte order mark is written as a literal in three files that read or test one | Accepted |
| P11-12 | Authentication | Low | Four sign-ins at once fill the sign-in gate, so a sender can keep real sign-ins at 429 | Accepted |
| P11-13 | Extension API | Low | A plugin runs in the process with full rights, and an error it raises as `ExtensionError` is shown as written | Accepted |

## Accepted exceptions

- **N2, P11-4, P11-5.** revrook CE has one organisation and a few accounts that the MSP
  made itself; the names are not secret, the cookie lasts 12 hours and is HttpOnly, and
  a lockout that can be repeated is the price of a lockout that cannot be skipped. A
  server-side session table and a lockout per address belong with the roles and single
  sign-on of the later edition.
- **P11-6.** One web process per installation is the supported shape; the limits would
  need a shared store to hold across processes.
- **P11-7.** Starlette answers an unhandled error from outside the middleware; the body
  is a fixed text with no data in it. No handler was added because the error is already
  the failure path.
- **P11-12.** The gate (4 sign-ins checked at once per process) protects the database
  connections from Argon2 work. A sender who keeps four sign-ins running can make real
  sign-ins wait and get 429, but cannot get in, read data or lock an account. Closing it
  needs a limit per address or a queue, which belong with a reverse proxy or the later
  edition.
- **P11-13.** A plugin is installed by the person who runs revrook and runs in the same
  process with the same rights; nothing in Python can isolate it. The loader names the
  plugin and the class of an error it raises and drops the error itself from the
  chain, but an `ExtensionError` that a plugin raises on its own is the plugin's text
  and is shown. Install only plugins you trust.
- **P11-10.** A byte order mark is a real part of how the importers read files, and the
  tests that write one need it. `tests/test_phase11_carryovers.py` allows it in those
  three files only and refuses it, and every hidden or reordering character, anywhere
  else.

## Not covered

Live deployment settings (TLS, the reverse proxy, the host, backups of a real
installation), dependencies beyond what `pip-audit` and the licence audit check in CI,
and anything that needs a real tenant or customer data. Those belong to the people who
deploy revrook, and to the product QA that the founders do.
