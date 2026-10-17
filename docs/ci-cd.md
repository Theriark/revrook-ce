# CI/CD flow

The application exists since phase 0, so `STRICT` is `"true"`: every check runs and a skipped check fails the gate (see below). The delivery workflows (`release.yml`, `promote-stage.yml`, `rollback.yml`) are definitions that have not run yet; `release.yml` first runs after a merge into `development`.

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
| 6 | licence audit and psycopg grep | `tools/licence_audit.py` exists | always runs |
| 7 | content licence rows (exact path match) | `data/` exists | always runs, `LICENSES-CONTENT.md` required |
| 8 | docker build, non-root check | `Dockerfile` exists, lint, typecheck, test and audit succeeded | always runs, every prerequisite must succeed |
| 9 | compose smoke (`.env.ci` copied from `.env.example`, `/readyz` on port 8080, `scripts/e2e/phase_00.sh`, then `tests/e2e/run.sh` if present) | `docker-compose.yml` exists, check 8 succeeded | always runs |

### STRICT

`STRICT` is a literal `"true"` or `"false"` in the `env` block of `ci.yml` (same style as `PROMOTION_ENABLED`). It is `"true"` since phase 0, which added the application and every file the checks need (`requirements*.txt`, `alembic.ini`, `tools/licence_audit.py`, `LICENSES-CONTENT.md`, `Dockerfile`, `docker-compose.yml`). The `"false"` behaviour below is kept for reference and for a repository that starts without an application.

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
- `release.yml`, `promote-stage.yml` and `rollback.yml` all use the one group `revrook-ce-delivery` with cancel-in-progress false. Trade-off: a stray dispatch of a disabled workflow can replace a pending (not running) release run, because a group keeps one running and one pending run. Re-run the replaced release from the Actions page if that happens.
- `promote-stage.yml` and `rollback.yml` fail at the guard while their `*_ENABLED` constant is `"false"`, and reference no secrets or environments. Workflow files that are not on the default branch cannot be dispatched, which is a second barrier.
- CI-only database credentials are throwaway values that protect nothing.
- Dependabot (`.github/dependabot.yml`) proposes weekly GitHub Actions updates.
- GHCR: `release.yml` publishes with the repository `GITHUB_TOKEN` only, one tag `sha-<full SHA>`, never `latest`. The package must stay private; the workflow fails if the API reports it public. GITHUB_TOKEN cannot change visibility and may not be able to read it, in which case the run warns and a human checks the package settings.

## Lock files (lock-requirements.yml)

`requirements.txt` and `requirements-dev.txt` are generated by `lock-requirements.yml`, not by hand and not on a developer machine: `pip-compile --generate-hashes --strip-extras` on `ubuntu-latest` with Python 3.12, runtime first, then development. The workflow runs on a push that changes `requirements.in` or `requirements-dev.in` (never on `main`, `development`, `stage` or `production`) and on manual dispatch of a branch. It needs only the repository token (`contents: write`, `actions: write`), no secret, and does nothing for forks. It commits only when the compiled files differ, so it cannot loop; its commit does not match its own trigger paths.

A push made with `GITHUB_TOKEN` does not start the `pull_request` run. The workflow therefore dispatches `ci.yml` (`workflow_dispatch` is the exception GitHub allows) on the branch and waits until a run exists on the new head. That run is not a `pull_request` run: if branch protection later requires the `pull_request` check, push an empty commit or re-run from the pull request page after the lock commit.

## Known gaps

- Every `uses:` line in `.github/workflows` names a full 40-character commit SHA with the major version tag in a comment. Each SHA was resolved from the tag in the action's own repository; the comment records the major tag, not a patch release. Dependabot proposes updates.
- `pip-audit` is pinned to `==2.10.1` (upstream tag `v2.10.1`). The tag was verified in the pypa/pip-audit repository; publication of that version on PyPI was not checked directly and is first exercised by check 5 once the application exists.
- Plan check 6 "no development package in the final image" is implemented by `scripts/check_image_packages.sh`, which check 9 runs through `scripts/e2e/phase_00.sh`.
- Branch protection and `.github/CODEOWNERS` need a human (see above).
- No `actionlint` or `shellcheck` run was available. `ci.yml` and `lock-requirements.yml` have run on GitHub; `release.yml`, `promote-stage.yml` and `rollback.yml` have never been executed (`release.yml` first runs after a merge into `development`).
- Phase 0 must add a test that fails when a module in a nested subpackage such as `app/checks/<pkg>/<module>.py` is below 95 percent coverage.

## Known differences from the reference repositories

- Release trigger is push to `development` (task scope); phase-plan-3 words it as merge to `main`.
- Dokploy IDs, health URLs and secrets are intentionally not copied from any other repository.
