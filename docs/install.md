# Install

How to run revrook CE for real on a machine you administer. To try it first with demo
data, use the [quick start](quick-start.md).

revrook is pre-release. There is no released version and no published image; you build
the image from the repository, and the code is on the `development` branch until a
release exists. Everything below is what the repository does today.

## What runs

| Part | What it is |
| --- | --- |
| `web` | The web interface and the API, port 8080 inside the container. |
| `worker` | The scheduler: reminders, retention, DNS re-checks, snapshots. |
| `db` | PostgreSQL 16. The only database revrook supports. |
| `/data` | A volume for the kept files (exports of reports and, if you keep them, raw files). |

The image can also run web and worker as two processes of one container (`ROLE=all`,
the default of the image). The compose file runs them as two containers.

Needs: Docker with the compose plugin, about 1 GB of free memory for one installation,
and disk for the database and the evidence volume. The only outbound connections the
application is built to make are the DNS questions of the
[public DNS check](dns-check.md), the mail relay you configure for reminders and the
heartbeat address you configure, each only when you use it; the tests refuse any other
network use.

## 1. Keys that are yours

The compose file reads two keys from `.env`. `.env.example` holds throwaway values:
never reuse them. Make your own, once, and keep them somewhere other than the server
([operations.md](operations.md#backup) says why):

```bash
cp .env.example .env
SECRET_KEY="$(openssl rand -hex 32)"
FERNET_KEY="$(openssl rand -base64 32 | tr '+/' '-_')"
```

then put the two values on the `SECRET_KEY=` and `FERNET_KEY=` lines of `.env` with an
editor (do not paste them into a shared terminal log or a ticket).

- `SECRET_KEY` signs the session cookie. At least 16 characters.
- `FERNET_KEY` encrypts the pseudonym key of every client. It must be a URL-safe base64
  text of 32 bytes. **If you lose it, every stored pseudonym key is unreadable**, and a
  restored backup is useless without it.

The compose file also carries a database password, `local-dev-only-not-a-secret`, in
`POSTGRES_PASSWORD` and in `DATABASE_URL`. The database port is not published, so the
password is only reachable from the compose network, but change it to something of your
own in both places before the first start if other containers share that network.

## 2. Start

```bash
docker compose up --build --wait
curl -fsS http://localhost:8080/readyz
```

The web role brings the database schema up to date when it starts (a locked,
one-at-a-time step), so there is no separate migration command. The first start of a new
volume takes a little longer.

Then open the address and make the first account on the first-run page. The page works
only until the first account exists, and whoever reaches a new installation first can
claim it: start behind your network controls (a firewall rule, a private network or a
reverse proxy that asks for its own sign-in) before you open the page.

To use another host port, change the left number of the `ports` line of the `web`
service in `docker-compose.yml` (`"8080:8080"` publishes container port 8080 on host
port 8080) and set `BASE_URL` to the address people will use.

## 3. Put TLS in front of it

revrook speaks plain HTTP on 8080 and does not terminate TLS. Run a reverse proxy that
does (Caddy, nginx, Traefik or the one your host already has) and forward to port 8080.
Then set `BASE_URL` to the public address, with `https://`: the session cookie is then
marked `Secure` and every response carries `Strict-Transport-Security`. Forward the
request with its `Content-Length`; a proxy that streams a chunked request through gets a
411 ([operations.md](operations.md#limits)).

## 4. Settings

Everything else is set by environment variables: reminders by email, retention, limits,
metrics, the heartbeat, the DNS resolver. [configuration.md](configuration.md) lists
every one with its default and shows how to set them in compose. The business name that
goes on the cover of the reports is set in the web interface, under **Settings**.

## Running the image without compose

You can run the image against a PostgreSQL 16 database of your own. The compose stack is
what the merge gate tests; this command is the same image with the settings given by
hand, and nothing tests it, so try it on a spare database first.

```bash
docker build -t revrook-ce .
docker run -d --name revrook \
  --read-only --tmpfs /tmp \
  -p 8080:8080 \
  -v revrook-data:/data \
  -e DATABASE_URL='postgresql+asyncpg://USER:PASSWORD@HOST:5432/DATABASE' \
  -e SECRET_KEY="$SECRET_KEY" \
  -e FERNET_KEY="$FERNET_KEY" \
  -e BASE_URL='https://revrook.example.com' \
  revrook-ce
```

With `ROLE=all` (the default) the container is ready only when the database answers and a
worker has reported ([operations.md](operations.md#roles)). The URL must start with
`postgresql+asyncpg://`.

## What to back up

The database and the evidence folder, together, and the two keys. The commands, and a
script that proves a backup restores, are in [operations.md](operations.md#backup).
Upgrading is in [upgrade.md](upgrade.md).

## Checklist before real data

- The keys of step 1 are yours and stored away from the server.
- The database password is not the sample one.
- A reverse proxy with TLS is in front, and `BASE_URL` is its `https://` address.
- The first account was made by you, from a network only you can reach.
- A backup was taken and restored once on another machine
  ([operations.md](operations.md#checking-that-a-backup-restores)).
- You have read [security.md](security.md) and the accepted limits in
  [security-review.md](security-review.md): one organisation per installation, a few
  accounts that you made yourself, one web process.
