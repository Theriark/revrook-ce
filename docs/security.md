# Sign-in and security design (phase 1)

What the code does today. Everything here has a test; the file names say where.

## First run

`/setup` creates the one administrator and works only while no user exists.
`GET /setup` redirects to `/login` afterwards and `POST /setup` answers 403.
Creation takes a PostgreSQL advisory lock, so two simultaneous requests create
one administrator (`app/auth.py`, `tests/test_auth_flow.py`). Whoever reaches
a new installation first can claim it: put it behind your network controls
before the first start.

## Passwords, lockout, sessions

- Passwords are hashed with Argon2id (`argon2-cffi` defaults, RFC 9106 low-memory
  profile). 12 to 256 characters. A stored hash is rehashed on sign-in when the
  parameters change. An unknown user costs the same hash check as a known one.
- Five failed sign-ins lock the account for five minutes. While it is locked the
  password is not checked, even when right. After five minutes the counter starts
  again. The state lives in `app_user.failed_login_count` and `locked_until`,
  under a row lock, so parallel attempts cannot skip it.
- The session is a signed cookie (`SECRET_KEY`, itsdangerous): HttpOnly,
  SameSite=Lax, Secure when `BASE_URL` starts with https, 12 hours sliding. It is
  signed, not encrypted: it holds the user id and the CSRF token only. A new
  CSRF token is issued at sign-in and sign-out.

## CSRF

Every POST, PUT, PATCH and DELETE needs the session's CSRF token, in the
`csrf_token` form field or the `X-CSRF-Token` header (htmx sends the header).
Otherwise the answer is 403. A request that carries an `Authorization: Bearer`
header is exempt because it uses no cookie (`app/web.py`, `tests/test_web_security.py`).

## Response headers

Every response carries: `Content-Security-Policy: default-src 'self'; base-uri
'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'`,
`X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
`X-Content-Type-Options: nosniff`, a restrictive `Permissions-Policy`, and
`Strict-Transport-Security` when `BASE_URL` is https. HTML pages also send
`Cache-Control: no-store`. The policy allows no inline script or style: pages
must use files under the same origin (htmx needs `htmx.config.includeIndicatorStyles`
set to `false`).

## API tokens

`app/auth.py` issues tokens (`rvk_` plus 32 random bytes, URL-safe). Only the
SHA-256 hash and a 12-character prefix are stored; the token is shown once.
`GET /api/v1/whoami` authenticates with `Authorization: Bearer <token>` and is
limited to 120 requests a minute per token (in memory, per process). There is no
page to create tokens yet (settings arrive in phase 9).

## Stored secrets

`app/crypto.py` encrypts single values with Fernet and `FERNET_KEY`. Each client
gets a random 32-byte key at creation, stored Fernet-encrypted in
`client.pseudonym_key_encrypted` (decision I6, no `PSEUDONYM_KEY_SEED`).
Deleting the client deletes the key.

## Append-only tables

`audit_event` and `evidence_log` reject UPDATE, DELETE and TRUNCATE inside the
database (triggers from revision `0002`, error code `restrict_violation`). They
have no foreign keys, so deleting a client never touches them. The database
table owner (and a superuser) can disable a trigger with `ALTER TABLE ...
DISABLE TRIGGER`. The guarantee therefore holds against the application, not
against whoever owns the tables: run the application with a role that does not
own them when that matters.

## Evidence files and retention (phases 2 and 3)

- A raw export is kept only while `RAW_RETENTION_DAYS` is above zero (default 0:
  gone as soon as it is parsed). A manual artefact is always kept. Files are
  stored under the SHA-256 of their content, in one folder per client.
- A file is written last, after the database rows and the hash-chain record of the
  upload have been written in the same transaction. A failure before that point
  leaves no file behind (`tests/test_evidence_orphans.py`). A failure while the
  transaction is being committed, after the file is written, can still leave one
  file that no row points to; it holds only what the client uploaded and goes
  when the client is deleted.
- `purge_expired_raw` (`app/evidence/retention.py`) deletes raw files whose
  retention date has passed. Since phase 10 the `retention-purge` schedule of the
  worker calls it every night (03:30 UTC), together with the removal of packs past
  `PACK_RETENTION_MONTHS`; every removal is an audit event (see `docs/operations.md`).
- The capture time and the expiry given with an upload must lie between the year
  2000 and the year 2199, and a capture time found inside a file must also not be
  in the future.

## Importers (phase 3)

An importer reads a file the MSP exported from a tool. The file is untrusted.

- Size and rows: the evidence store refuses a file over `IMPORT_MAX_BYTES` (20 MB)
  and an importer refuses more than `IMPORT_MAX_ROWS` (200,000) rows. A JSON file
  is refused above 20 MB, nested deeper than 12 levels or with a list longer than
  the row limit; a CSV field larger than 131,072 characters refuses the file.
- Text: UTF-8 (with or without a byte order mark) and UTF-16 with a mark are read
  directly; anything else goes through `charset-normalizer`. A file with NUL bytes
  is not text and is refused.
- Recognition: a file is recognised by its header columns or its JSON fields and
  never by its name. A file that lacks a required column is refused naming it, and
  the message says when it looks like another source.
- What is stored: counts, flags, times the importer parsed itself, words from a
  fixed list and short printable text. Personal identifiers (user, device) are
  replaced by the client's pseudonym before anything is stored, and a stored value
  that still looks like an email address refuses the upload.
- Dropped: `imei`, `phoneNumber` and `activationLockBypassCode` are never read.
  Device names, serial numbers and policy names are not read either.
- Spreadsheet formulas: text kept in a fact that starts with `=`, `+`, `-` or `@`
  gets a leading apostrophe, so exporting the facts to a spreadsheet cannot run it.
- Row errors: a row that cannot be read is counted, the first 50 reasons are kept
  as facts, and a file in which no row can be read is refused. A reason names the
  column and never repeats what the file said.

## Known limits

- Sign-out clears the cookie but cannot revoke a stolen signed cookie before it
  expires (there is no server-side session table).
- There is no limit on sign-in attempts for unknown usernames, and the lockout is
  per account, not per address.
- The in-memory API rate limit is per process.
- Internal server errors (500) are produced outside the middleware stack and do
  not carry the security headers.
- Evidence uploads are capped (`IMPORT_MAX_BYTES`, refused before the body is
  read); other request bodies are not size-capped yet.
- N2, for phase 11: account existence can be learned from the lockout (a known
  account answers as locked after five failures, an unknown name never does).
- N3, for phase 11: a database connection is held while Argon2 checks a password
  and no throttle sits in front of it, so many parallel sign-ins can use up the pool.
- N5, for phase 11: every request with an `Authorization: Bearer` header skips the
  CSRF check, not only the API routes.
