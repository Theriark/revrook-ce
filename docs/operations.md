# Operations (phase 10)

How revrook runs when nobody is looking at it: the worker and its schedules, the
reminders, what is removed and when, how to watch it, and how to back it up and
restore it. Everything here uses the compose stack of `docker-compose.yml`; a
deployment that runs the image another way uses the same commands with its own
container names.

## Roles

| `ROLE` | What runs | `/readyz` |
| --- | --- | --- |
| `web` | The web interface and the API. | Ready when the database answers. |
| `worker` | The scheduler and the jobs, no web interface. | Not served. |
| `all` (the image default) | The web role on port 8080 and the worker, as two processes of one container. | Ready only when the database answers **and** a worker has reported within the last 90 seconds. |

`ROLE=all` is the whole product in one container. Its `/readyz` answers 503 with
`{"status": "not ready", "database": "ok", "worker": "never" | "stale"}` while the
worker is missing, so an orchestrator does not send people to an installation whose
background jobs have stopped. If either process ends, the other is stopped and the
container exits (and is restarted by its supervisor); a role that ends on its own is a
failure. The compose stack runs `web` and `worker` as two containers instead, and
`/readyz` of `web` then looks at the database only.

`python -m app.cli web --port 9000` and `python -m app.cli all --port 9000` serve on
another port; the default is 8080.

## The worker

The worker writes a heartbeat row every 5 seconds, also while a job runs (a job may
take minutes; the heartbeat does not wait for it). One worker at a time holds an
advisory lock in the database and runs the schedules; a second worker stands by and
takes over when the first one stops. A schedule is claimed by one `UPDATE` of its own
row (`next_run_at` moves forward and `last_run_at` is set) before it runs, so a due
schedule runs once, however many workers look at it. A schedule that was missed while
the worker was down runs once when it is back, not once per missed time. A job that
fails is written to the audit trail with the class of the error (never its text) and
does not stop the others.

All times are UTC. A schedule is five cron fields (`minute hour day-of-month month
day-of-week`, with lists, ranges and steps), one of `@hourly`, `@daily`, `@weekly`,
`@monthly`, or `@once`.

| Kind | Needs | What it does |
| --- | --- | --- |
| `expiry-reminder` | nothing (whole installation) | One message about the evidence that crossed a reminder threshold. |
| `retention-purge` | nothing (whole installation) | Removes what has passed its retention time. |
| `dns-check` | a client and its mail domains | Runs the public DNS check and stores it as evidence. |
| `snapshot-build` | a client | Stores the state of the client today as a snapshot of the last full quarter. |

The worker creates two schedules when it starts and does not change them afterwards:
`expiry-reminders` at 06:00 and `retention-purge` at 03:30 UTC every day. They can be
switched off or changed in the database; `GET /api/v1/schedules` lists them.

```text
POST   /api/v1/schedules                           add a schedule (kind, cron, client_id, domains...)
GET    /api/v1/schedules                           list them with their last and next run
DELETE /api/v1/schedules/{id}                      remove one
POST   /api/v1/clients/{id}/snapshot-requests      ask the worker for a snapshot of a client
GET    /api/v1/system                              is a worker reporting?
GET    /api/v1/export                              the data export (see below)
```

A snapshot request is a one-time schedule (`@once`) that the worker runs at its next
look, normally within seconds. Asking again while one is waiting returns the waiting
one. The look for a waiting request and the insert of a new one are one transaction
under the lock of the client, so two requests at once queue one snapshot.

## System page and the stale-worker banner

`/system` shows whether a worker is reporting, the schedules with their last and next
run, which outside services are set, the data export and the deletion of a client.

When no worker has reported for more than 90 seconds every page shows a banner
("The background worker has not reported for more than N minutes"). The banner is
therefore visible within 2 minutes of the worker stopping and always within the 3
minutes the acceptance check allows. Before the first worker has ever reported the
pages stay quiet and `/system` says so.

## Expiry reminders

An evidence item has reminder thresholds at 30 days, 7 days and 0 days (the day it
goes stale) before `expires_at`. Only the newest item of each source of each client
counts: a refreshed export stops the reminders of the old one. A threshold counts only
when it is below half the life of the item, so an automatic export that is stale after
35 days is reminded at 7 days and on the day, not at 30.

A reminder is sent once per threshold crossing. The pair (item, threshold) is a primary
key in `reminder_sent` and is inserted before the message goes out; if the message
cannot be sent the rows are removed and the next run tries again. `sent_at` is the time
the rows were claimed, read when the claim is made. When an item is renewed (a new
revision of a manual artefact or an attestation moves its expiry later), the rows sent
for the old expiry are dropped and its thresholds are reminded again for the new expiry.
A correction that keeps the same expiry is not a renewal: nothing is cleared and
nothing is mailed twice. One run sends one message to one address, with client names,
source names and dates only.

To turn reminders on:

1. Set `SMTP_HOST`, `SMTP_PORT` (default 587), `SMTP_FROM` and, if the relay wants a
   login, `SMTP_USER` and `SMTP_PASSWORD` in the environment of the worker.
2. Enter the address in **Settings**. An empty address means no reminders.

The message is always sent over STARTTLS with the certificate of the relay checked. A
relay that does not offer STARTTLS gets no message and no password.

## What is removed, and when

The `retention-purge` job removes, and writes an audit event for every removal:

- raw files whose `raw_expires_at` has passed (only when `RAW_RETENTION_DAYS` is above
  zero); their hashes stay in the hash chain (`evidence.raw_purged`);
- snapshots and exported reports older than `PACK_RETENTION_MONTHS` (default 25), and
  the kept copy of an export unless another row still uses the file (`snapshot.purged`,
  `export.purged`);
- the folder of a client that no longer exists (`files.leftover_removed`);
- one-time schedules that ran more than 7 days ago.

Evidence items, facts, the hash chain and the audit trail are never purged here: they go
with their client, and only then. A run that removed something also writes one
`retention.run` event with the counts.

## Export and deleting a client

`GET /api/v1/export` (or the button on `/system`) is one zip with a CSV file per table:
clients, evidence items and revisions, facts, snapshots and control results, exceptions,
export history, schedules, the audit trail and the hash chain, with `manifest.csv` (the
rows of each file) and `README.txt`. It leaves out what could name a person: user
accounts, password hashes, API tokens, the user behind an audit event, the pseudonym key
of a client, texts typed by people (reviewer names, notes, exception owner and reason)
and the kept files. A text cell that starts with `=`, `+`, `-` or `@` gets a leading
apostrophe so a spreadsheet does not run it. Each export is an audit event (`data.exported`).

The export is for reading and moving data, not for restoring: use the backup below for
that.

The export is built as a stream. Each table is read from a cursor and written into the
zip through a buffer of 64 KiB, in a temporary file that stays in memory up to 8 MiB
and then goes to `/tmp`, and the answer is sent from that file in pieces. Memory use
is therefore about 8 MiB plus one buffer, whatever the size of the data (the compose
stack mounts `/tmp` as a tmpfs, so a large export uses memory there until it has been
sent). The CSV text of one export may not exceed 256 MiB before compression: past that
the export is refused with 413 and nothing is audited. An installation that large takes
a database backup instead (below).

## Limits

Every number below is enforced in code and has a test (`docs/security-review.md`).

| What | Limit | Over it |
| --- | --- | --- |
| An evidence upload (API or profile editor) | `IMPORT_MAX_BYTES`, 20 MiB by default, plus 64 KiB of form overhead; it must declare its size | 413, or 411 without a size |
| Rows of one imported file | `IMPORT_MAX_ROWS`, 200,000 | the file is refused |
| Any other request body (POST, PUT, PATCH, DELETE) | 1 MiB; a body sent in chunks without a size is refused | 413, or 411 |
| An id in an address or a request body | 1 to 9223372036854775807 | 422 (a value the database still refuses is also 422) |
| A report period | 400 days, and it may not end in the future | 422 |
| The data export | 256 MiB of CSV text before compression | 413 |
| API requests | 120 requests a minute per token | 429 with `Retry-After` |
| Sign-ins checked at once | 4 in one process (each holds a database connection while Argon2 runs) | 429 with `Retry-After: 5`, nothing is checked or written |
| Failed sign-ins | 5 lock the account for 5 minutes | 429 |
| A password | 12 to 256 characters | refused |

Notes typed in the report builder are saved on every change, so the end of a session
(it lasts 12 hours) loses nothing that was typed before it ended. A save made after the
session ended is refused with 403 and a message that asks for a reload; sign in again
and the earlier notes are there.

To delete one client, open `/system`, type its exact name and press the button. Its
evidence, facts, reports, exports, kept files and pseudonym key go; the audit entry
(`client.deleted`, with counts) and the hash chain record remain.

## Watching it

**Metrics.** Set `METRICS_TOKEN` to turn on `GET /metrics` (Prometheus text format,
`Authorization: Bearer <token>`); without the token the path answers 404. Use a long
random value (at least 32 random characters, for example `openssl rand -hex 32`): the
path has no rate limit, so the length of the token is its only protection. Only totals
are exported, never a client name or identifier:

| Metric | Type | Meaning |
| --- | --- | --- |
| `revrook_build_info{version}` | gauge | Always 1. |
| `revrook_clients` | gauge | Clients. |
| `revrook_evidence_items` | gauge | Evidence items. |
| `revrook_snapshots` | gauge | Stored snapshots. |
| `revrook_report_exports` | gauge | Exported reports kept. |
| `revrook_audit_events_total` | counter | Audit events written. |
| `revrook_schedules_enabled` | gauge | Enabled schedules. |
| `revrook_schedules_overdue` | gauge | Enabled schedules more than 5 minutes late. |
| `revrook_worker_up` | gauge | 1 when a worker reported in the last 90 seconds. |
| `revrook_worker_heartbeat_age_seconds` | gauge | Seconds since the newest heartbeat, NaN before the first. |

Alert on `revrook_worker_up == 0` and on `revrook_schedules_overdue > 0`.

**Outside heartbeat.** Set `HEARTBEAT_URL` to an `http://` or `https://` address of a
dead-man's-switch service (an address with a space, a control character or a port
that is not a number is refused and logged once; the worker keeps running). The worker that holds the lock sends one plain `GET` a minute
while it is healthy: no body, no data, a fixed user agent. The URL may hold a secret, so
it is never logged.

## Backup

A backup is two things taken together: the database and the evidence folder. The
database holds every row and the hash chain; the folder holds the kept files (the
exports of reports and the raw files, if you keep them). Both are needed, and the
encryption key (`FERNET_KEY`) and `SECRET_KEY` of the installation must be kept
somewhere else, because the pseudonym keys in the dump are encrypted with `FERNET_KEY`
and are useless without it.

```bash
mkdir -p backup
docker compose exec -T db pg_dump -U revrook -d revrook -Fc > backup/revrook.dump
docker compose cp web:/data/evidence/. backup/evidence
```

`pg_dump` reads a consistent snapshot while the application runs; the evidence folder
only ever gains files (a purge removes some), so copy it right after the dump and the
restore check below tells you if something is missing. Keep the two together, with the
date in the folder name, and copy them off the machine.

## Restore

On a stopped or fresh stack, with the same `SECRET_KEY` and `FERNET_KEY` in `.env`:

```bash
docker compose up -d db
docker compose exec -T db psql -U revrook -d postgres \
  -c "DROP DATABASE IF EXISTS revrook" -c "CREATE DATABASE revrook"
docker compose exec -T db pg_restore -U revrook -d revrook --no-owner --exit-on-error \
  < backup/revrook.dump
docker compose create web
docker compose cp backup/evidence/. web:/data/evidence
docker compose run --rm --user root --entrypoint chown web -R 10001:10001 /data/evidence
docker compose run --rm web verify-chain
docker compose up -d
```

`verify-chain` reads every client's hash chain and prints one line per client:
`intact` with the number of records and the head hash, or `BROKEN` with the record where
it stopped (exit code 1). Do not put the restored installation into use until it says
`intact` for every client. The web role brings the schema up to date when it starts, so
a dump from an older version restores into a newer one.

## Checking that a backup restores

`scripts/restore_check.sh` does the backup and the restore on a running compose stack,
into a second database that it drops again, and fails if anything differs:

```bash
bash scripts/restore_check.sh
```

It (1) dumps the database with `pg_dump -Fc`, (2) restores the dump into the database
`revrook_restore_check`, (3) compares the row count of every table of the two (a count
may lie between the counts taken before and after the dump, because the application
keeps running), (4) copies the evidence folder out of the web container and checks that
every kept file is there, that its content has the SHA-256 in its name and that the
copy equals the folder, and (5) runs `verify-chain` against the restored database and
requires the same chains, record counts and head hashes as the live database. It needs
`docker`, a running stack (the same one `tests/e2e/run.sh` uses), and takes about half a
minute. It never reads or writes anything of the live database except the dump.

The script gives the database URL, password included, to the web container as an
environment argument of `docker exec -e DATABASE_URL=...` (it runs `verify-chain` twice
against the live database and once against the restored one). While a check runs, any
user who can list processes on the Docker host can read that URL in the process list.
Run the check on a host you administer alone, or with a database user whose password
you change afterwards.

A restore that has never been tried is not a backup: run the check after every change
to the database schema, and the restore itself once on another machine before you rely
on it.
