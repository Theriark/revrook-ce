# Development guide (phase 0)

## Dependency locks (hashes)

`requirements.in` and `requirements-dev.in` are the inputs. The hashed locks
`requirements.txt` and `requirements-dev.txt` are generated, never edited by
hand. The `Lock requirements` workflow (`.github/workflows/lock-requirements.yml`)
does it for you: push a change to either `.in` file and it commits the locks to
your branch (see `docs/ci-cd.md`). To generate them yourself, use Linux with
Python 3.12 so environment markers match CI:

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install "pip==25.1.1" "pip-tools==7.5.0"   # the versions the workflow uses
pip-compile --generate-hashes --strip-extras --allow-unsafe --output-file requirements.txt requirements.in
pip-compile --generate-hashes --strip-extras --allow-unsafe --output-file requirements-dev.txt requirements-dev.in
```

Compile `requirements.txt` first: the dev input uses it as a constraint file.
`--allow-unsafe` is needed because pip-tools depends on setuptools, which
pip-compile otherwise leaves out of the lock; `pip install --require-hashes`
then fails on it.
Then install and run the checks:

```bash
pip install --require-hashes -r requirements-dev.txt
ruff check . && ruff format --check .
mypy app
```

## Tests

The tests need a PostgreSQL 16 database. Start one and point `DATABASE_URL` at it:

```bash
docker compose up -d db
export DATABASE_URL=postgresql+asyncpg://revrook:local-dev-only-not-a-secret@localhost:5432/revrook
```

Compose does not publish the database port; add a `ports` entry to the `db`
service in a local override file if you run the tests from the host.

```bash
pytest -q --cov=app --cov-report=term-missing
```

Without `DATABASE_URL` the database tests are skipped, so a local run proves
less than CI. A socket guard in `tests/conftest.py` fails any test that opens a
connection to anything but loopback or the database host.

## Run the stack

```bash
cp .env.example .env     # throwaway values, never reuse them in a deployment
docker compose up --build --wait
curl -fsS http://localhost:8080/readyz
bash scripts/e2e/phase_00.sh
docker compose down -v
```

The image starts `python -m app.cli`. `ROLE=web`, `ROLE=worker` or the default
`ROLE=all` (web and worker as two processes) choose what runs. The `revrook`
console script is defined in `pyproject.toml` for a development install
(`pip install -e .`) and offers the same subcommands.

## Licence audit

```bash
pip install --require-hashes -r requirements.txt   # in a clean environment
python tools/licence_audit.py
```

See `docs/licences.md` for the policy and for how ambiguous packages are
recorded in `licence-exceptions.txt`.
