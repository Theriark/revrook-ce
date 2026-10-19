# Upgrade

How to move an installation to a newer version without losing data, and how to go back.
revrook is pre-release and has no released version yet, so the steps below use the
`development` branch; with a release they use its tag.

## What an upgrade does

A newer image brings the database schema up to date by itself. The web role runs
`alembic upgrade head` when it starts, holding a lock in the database, so two processes
that start together migrate one after the other and a second one finds nothing left to
do. `python -m app.cli migrate` does the same step on its own (under compose:
`docker compose run --rm web migrate`). The worker starts after the web role is healthy,
so it never runs against a schema that is half done.

A migration only adds: a column with a default or one that may be empty, a table, a
trigger. It does not remove or rename a column in the same release that stops using it.
That is the rule for new migrations, and it is why the image of the release before can
still read an upgraded database for one release, which keeps a rollback of the image
possible. The current migrations follow it.

## Before you start

1. Read the [CHANGELOG](../CHANGELOG.md) for what changed, and in particular for any
   change that cannot be undone.
2. Take a backup and keep it ([operations.md](operations.md#backup)): the database, the
   evidence folder and your two keys. A restore is the way back, so make sure you have
   restored one at least once ([operations.md](operations.md#checking-that-a-backup-restores)).
3. Check that the installation is healthy: `curl -fsS http://localhost:8080/readyz` and
   `docker compose ps`.

## Steps with compose

```bash
git fetch origin
git checkout development      # with a release: the tag of the version
git pull --ff-only
docker compose build
docker compose up -d
docker compose logs --tail 50 web
docker compose run --rm web verify-chain
curl -fsS http://localhost:8080/readyz
```

`docker compose up -d` recreates the services whose image changed and leaves the
database and the evidence volume alone. The log of the web role shows the migrations it
ran. `verify-chain` reads the hash chain of every client and must say `intact` for each
([operations.md](operations.md#restore) explains the output). `/readyz` is the last
word: it answers 200 when the database answers. A process that runs both roles
(`ROLE=all`) also needs a worker to have reported; the compose web service runs
`ROLE=web` and does not wait for one, so check the worker with `docker compose ps`.

With a different setup the steps are the same in spirit: stop the old container, start
the new image with the same environment and the same volumes, watch the log, run
`verify-chain`.

## Going back

Do not run `alembic downgrade` on an installation that holds data. Every migration has a
downgrade and the test suite goes down and up again, but a downgrade drops what the
migration added, with the data in it: the mail domains of a DNS check schedule and the
record of which reminder was sent are examples.

To go back, stop the services, restore the backup you took before the upgrade
([operations.md](operations.md#restore)), and start the previous image. An image that is
one release older than the schema can still run on it, but restoring is the path that
leaves nothing to reason about. `docs/ci-cd.md` states the same rule for the images of
Development and Stage: a rollback never downgrades the database.

## How upgrades are tested

- `tests/test_upgrade.py` builds a scratch database at each earlier revision that holds
  tables, puts one row into every table, upgrades it to the newest revision and checks
  that no row is lost, that the schema equals the models (`alembic check`), that the
  application reads the old rows, that the append-only and immutable guards of the
  database still refuse a change, and that going down to the old revision and up again
  keeps every row.
- The merge gate runs `alembic upgrade head`, `alembic check`, a downgrade and an
  upgrade again on an empty database (check 4).
- `scripts/restore_check.sh` proves that a dump restores into a second database with
  equal row counts and an intact hash chain, and it runs on every change.

These tests prove that data survives and that the schema is the one the code expects.
They do not run an old image against a new schema; the rule above is what promises that.

## The version number

The version of the package in `pyproject.toml` and the constant `__version__` in
`app/__init__.py` are both `0.0.0.dev0` until a release is authorised.
`revrook_build_info{version}` on the [metrics](operations.md#watching-it) page shows the
second one, not `pyproject.toml`, and `tests/test_packages.py` pins both and fails when
they differ. The release that sets both to `0.1.0` is a separate step, and it changes
that test with them ([release-candidate.md](release-candidate.md)).
