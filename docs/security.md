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
