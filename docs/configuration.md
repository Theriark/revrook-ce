# Configuration

revrook reads its settings once, from environment variables, when a role starts. A
value that is not valid stops the start with a message that names every variable at
fault and never prints a value. `tests/test_docs.py` fails when this page and
`app/settings.py` disagree about a variable or a default.

Anything about people (the business name on the reports, the address that gets the
reminders) is set in the web interface under **Settings**, not here.

## The variables

A variable that is empty counts as not set.

| Variable | Default | What it does |
| --- | --- | --- |
| `DATABASE_URL` | required | The PostgreSQL 16 database, as `postgresql+asyncpg://USER:PASSWORD@HOST:5432/DATABASE`. Any other scheme is refused. |
| `SECRET_KEY` | required | Signs the session cookie. At least 16 characters; `openssl rand -hex 32` makes a good one. |
| `FERNET_KEY` | required | Encrypts the pseudonym key of every client. A URL-safe base64 text of 32 bytes ([install.md](install.md) shows how to make one). Losing it makes the stored keys unreadable. |
| `BASE_URL` | `http://localhost:8080` | The address people use. It must start with `http://` or `https://`. With `https://` the session cookie is `Secure` and responses carry `Strict-Transport-Security`. |
| `ROLE` | `all` | `web`, `worker` or `all` (web and worker as two processes of one container). See [operations.md](operations.md#roles). |
| `EVIDENCE_DIR` | `/data/evidence` | Where the kept files live. It must be on a volume that survives the container. |
| `RAW_RETENTION_DAYS` | `0` | How long a raw export is kept after it is read, 0 to 35 days. 0 deletes it as soon as it is parsed. A manual artefact is always kept. |
| `PACK_RETENTION_MONTHS` | `25` | How long snapshots and exported reports are kept, 1 to 120 months. |
| `IMPORT_MAX_BYTES` | `20971520` | The largest evidence file, in bytes (20 MiB), at most 1073741824. |
| `IMPORT_MAX_ROWS` | `200000` | The most rows of one imported file, at most 10000000. |
| `LOG_LEVEL` | `info` | `critical`, `error`, `warning`, `info` or `debug`. |
| `METRICS_TOKEN` | unset | Turns on `GET /metrics` (Prometheus format) behind `Authorization: Bearer`. Use at least 32 random characters: the path has no rate limit. Without it the path answers 404. |
| `SMTP_HOST` | unset | The mail relay for the expiry reminders. Reminders need `SMTP_HOST` and `SMTP_FROM`, and an address in **Settings**. The connection always uses STARTTLS and checks the certificate. |
| `SMTP_PORT` | `587` | The port of the relay, 1 to 65535. |
| `SMTP_USER` | unset | The login of the relay, if it wants one. |
| `SMTP_PASSWORD` | unset | The password of the relay. Never logged. |
| `SMTP_FROM` | unset | The sender address of the reminders. |
| `HEARTBEAT_URL` | unset | An `http://` or `https://` address of a dead-man's-switch service. The worker that holds the lock sends one plain `GET` a minute. It may hold a secret, so it is never logged. |
| `DNS_RESOLVER` | unset | Who answers the [public DNS check](dns-check.md): not set for the system resolvers, an IP address for one nameserver, or an `https://` URL for DNS over HTTPS. Anything else stops the start. |

Limits that are not settings (a request body of 1 MiB, 120 API requests a minute, five
failed sign-ins) are listed in [operations.md](operations.md#limits).

## Where to set them

**Compose.** `docker-compose.yml` reads `SECRET_KEY` and `FERNET_KEY` from `.env` and
sets `DATABASE_URL`, `BASE_URL` and `EVIDENCE_DIR` itself. To set the others, put them
in a file named `docker-compose.override.yml` next to it, which compose reads
automatically and merges with the first file. Set a variable for both `web` and
`worker`; a role ignores what it does not use:

```yaml
x-extra: &extra
  RAW_RETENTION_DAYS: "7"
  SMTP_HOST: smtp.example.com
  SMTP_FROM: revrook@example.com
  LOG_LEVEL: info

services:
  web:
    environment:
      <<: *extra
      METRICS_TOKEN: replace-with-at-least-32-random-characters
  worker:
    environment:
      <<: *extra
      SMTP_USER: revrook
      SMTP_PASSWORD: replace-me
```

To change `BASE_URL` (for the `https://` address behind a proxy), set it in the same file
for both services: a value there replaces the one in `docker-compose.yml`. Keep that file
out of version control when it holds a secret. Then `docker compose up -d` recreates the
services with the new values. Check the result with `docker compose config`, which prints
the merged file (it prints secrets too, so do not paste its output anywhere).

**One container.** Pass them as `-e NAME=value` ([install.md](install.md)).

## Reading a start error

The role exits with code 2 and one line such as
`invalid configuration: SECRET_KEY is required; FERNET_KEY must be a URL-safe base64
encoded 32-byte key`. Under compose, `docker compose logs web` shows it. The value of a
variable is never in the line.
