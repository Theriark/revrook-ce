# CI/CD flow

Definitions only. The application code does not exist yet (phase 0 creates it), so most checks skip today.

## Flow

1. Feature branch `feat/revrook-ce-<phase>` and a draft pull request into `development`.
2. `ci.yml` runs the merge gate on every pull request (superseded runs are cancelled).
3. Merge into `development` triggers `release.yml`: tests first, then one image tagged `sha-<full source SHA>` is pushed to GHCR and its immutable digest is recorded in the run summary and a `release-record-<sha>` artifact.
4. Development deployment is a request to the existing private controller. It is a documented placeholder and sends nothing yet. Image publication is not deployment proof: the target must report the same source SHA and digest.
5. Stage promotion (`promote-stage.yml`) and rollback (`rollback.yml`) are `workflow_dispatch` definitions that are disabled. They take an explicit digest and never rebuild.
6. Human QA in Jira follows Stage. Production is a separate authorised step on VM-10. Development and Stage run on VM-09.

## Merge gate (ci.yml)

| # | Check | Runs when |
|---|-------|-----------|
| 1 | ruff check and format | `pyproject.toml` exists |
| 2 | mypy | `pyproject.toml` exists |
| 3 | pytest, PostgreSQL 16, coverage 80 percent overall, 95 percent core packages | `pyproject.toml` exists |
| 4 | alembic up, check, down, up | `alembic.ini` exists |
| 5 | pip-audit (exceptions in `.pip-audit-exceptions`) | `pyproject.toml` exists |
| 6 | licence audit and psycopg grep | `scripts/licence_audit.py` exists |
| 7 | content licence rows | `data/` exists |
| 8 | docker build, non-root check | `Dockerfile` exists, needs 1 to 7 |
| 9 | compose smoke | `tests/e2e/run.sh` exists, needs 8 |

A skipped check is reported as `skipped` in the "Merge gate summary" job, never as a pass. Tests precede the build through `needs`. Phase 0 must create the files named above, or change the names here and in `ci.yml` together.

## Guard rails

- GitHub-hosted `ubuntu-latest` only. No self-hosted runner, no paid overage.
- Least privilege: `contents: read`, plus `packages: write` only in the image build job.
- PR runs: one group per ref with cancel-in-progress true. Build, promotion and rollback share the group `revrook-ce-delivery` with cancel-in-progress false. This serializes this repository only. Cross-repository serialization is the controller's job and is not verified by YAML.
- `promote-stage.yml` and `rollback.yml` fail at the guard while their `*_ENABLED` constant is `"false"`, and reference no secrets or environments. Workflow files other than on the default branch cannot be dispatched, which is a second barrier.
- CI-only database credentials are throwaway values that protect nothing.

## Known differences from the reference repositories

- Release trigger is push to `development` (task scope); phase-plan-3 words it as merge to `main`.
- Dokploy IDs, health URLs and secrets are intentionally not copied from Nowlert CE.
