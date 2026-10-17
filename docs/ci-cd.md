# CI/CD flow

Definitions only. The application code does not exist yet (phase 0 creates it), so most checks skip today. That is allowed only while `STRICT` is `"false"` (see below).

## Flow

1. Feature branch `feat/revrook-ce-<phase>` and a draft pull request into `development` (or into another feature branch when stacked).
2. `ci.yml` runs the merge gate on every pull request (superseded runs are cancelled).
3. Merge into `development` triggers `release.yml`: tests first, then one image tagged `sha-<full source SHA>` is pushed to GHCR and its immutable digest is recorded in the run summary and a `release-record-<sha>` artifact.
4. Development deployment is a request to the existing private controller. It is a documented placeholder and sends nothing yet. Image publication is not deployment proof: the target must report the same source SHA and digest.
5. Stage promotion (`promote-stage.yml`) and rollback (`rollback.yml`) are `workflow_dispatch` definitions that are disabled. They take an explicit digest and never rebuild.
6. Human QA in Jira follows Stage. Production is a separate authorised step on VM-10. Development and Stage run on VM-09.

## Merge gate (ci.yml)

| # | Check | Runs when (STRICT false) | STRICT true |
|---|-------|-----------|----|
| 1 | ruff check and format | `pyproject.toml` exists | always runs |
| 2 | mypy | `pyproject.toml` exists | always runs |
| 3 | pytest, PostgreSQL 16, coverage 80 percent overall, 95 percent core packages (nested subpackages included) | `pyproject.toml` exists | always runs |
| 4 | alembic up, check, down, up | `alembic.ini` exists | always runs |
| 5 | pip-audit, fails on any known vulnerability (exceptions in `.pip-audit-exceptions`) | `pyproject.toml` exists | always runs |
| 6 | licence audit and psycopg grep | `scripts/licence_audit.py` exists | always runs |
| 7 | content licence rows (exact path match) | `data/` exists | always runs, `LICENSES-CONTENT.md` required |
| 8 | docker build, non-root check | `Dockerfile` exists, lint, typecheck, test and audit succeeded | always runs, every prerequisite must succeed |
| 9 | compose smoke (`/readyz`, then `tests/e2e/run.sh` if present) | `docker-compose.yml` exists, check 8 succeeded | always runs |

### STRICT

`STRICT` is a literal `"true"` or `"false"` in the `env` block of `ci.yml` (same style as `PROMOTION_ENABLED`). It is `"false"` now because there is no application. The phase 0 pull request that adds the application MUST set it to `"true"` and add every file the checks need (`requirements*.txt`, `alembic.ini`, `scripts/licence_audit.py`, `LICENSES-CONTENT.md`, `Dockerfile`, `docker-compose.yml`).

- `false`: a skipped check is reported as `skipped`, never a pass. `detect` fails if any application file already exists (tripwire), so the application cannot land while strict is off, and deleting one input cannot switch its check off.
- `true`: every check runs; a missing input makes its check fail. The `Merge gate summary` job fails on any result other than `success` for `detect` and checks 1 to 9, including an all-skipped run. Docs-only pull requests also run every check (no docs exemption).
- `release.yml` reads the value from the `ci.yml` run it just called and fails when the Dockerfile is missing and STRICT is not `"false"`.

### Branch protection and ownership (human action, not set by this repository)

Branch protection cannot be set from YAML and has NOT been verified or changed. Required configuration for `development` and `main`:

- Require only the PR-run check `Merge gate summary` (through `release.yml` it appears as `Tests (merge gate) / Merge gate summary`, which is not the one to require). Never require the individual jobs: a skipped required job counts as passing.
- Require a pull request and a code-owner review for changes under `.github/`.
- Add `.github/CODEOWNERS` with `/.github/ @<owner>`. The owner handle or team must be supplied by a human; none could be verified, and an unknown owner makes GitHub ignore the rule, so no file is added here.

## Guard rails

- GitHub-hosted `ubuntu-latest` only. No self-hosted runner, no paid overage.
- Least privilege: `contents: read`, plus `packages: write` only in the image build job. `pull_request`, never `pull_request_target`; CI needs no secrets.
- PR runs: one group per ref with cancel-in-progress true. Build uses the group `revrook-ce-delivery` with cancel-in-progress false. This serializes this repository only. Cross-repository serialization is the controller's job and is not verified by YAML.
- Queue depth is one. A concurrency group holds one running and one pending run; a newer pending run replaces the older pending one. Two quick merges can therefore leave the middle commit without an image. The controller must tolerate source SHAs that have no image, and promote only a digest that exists in a `release-record-<sha>` artifact or the GHCR registry. A running deployment is never cancelled.
- `promote-stage.yml` and `rollback.yml` use a separate group `revrook-ce-delivery-disabled`, so a stray dispatch cannot displace a pending release. The change that enables either workflow must move it into `revrook-ce-delivery` (or rely on the controller lock) as part of its own approval.
- `promote-stage.yml` and `rollback.yml` fail at the guard while their `*_ENABLED` constant is `"false"`, and reference no secrets or environments. Workflow files that are not on the default branch cannot be dispatched, which is a second barrier.
- CI-only database credentials are throwaway values that protect nothing.
- Dependabot (`.github/dependabot.yml`) proposes weekly GitHub Actions updates.

## Known gaps

- Actions are pinned to mutable version tags, not commit SHAs. SHAs could not be verified from a primary source with the tools of this run; pin them (with a version comment) in a follow-up and let Dependabot maintain them.
- `pip-audit` is bounded to major version 2, not pinned exactly (exact version not verified from PyPI in this run).
- Plan check 6 "no development package in the final image" is not implemented; it needs the real Dockerfile (phase 0).
- Branch protection and `.github/CODEOWNERS` need a human (see above).
- No `actionlint`, `shellcheck` or coverage run was available; `release.yml`, `promote-stage.yml` and `rollback.yml` have never been executed.
- Phase 0 must add a test that fails when a module in a nested subpackage such as `app/checks/<pkg>/<module>.py` is below 95 percent coverage.

## Known differences from the reference repositories

- Release trigger is push to `development` (task scope); phase-plan-3 words it as merge to `main`.
- Dokploy IDs, health URLs and secrets are intentionally not copied from Nowlert CE.
