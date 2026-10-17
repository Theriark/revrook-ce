# CI/CD flow

The application exists since phase 0, so `STRICT` is `"true"`: every check runs and a skipped check fails the gate (see below). GitHub Actions itself builds, publishes and deploys, using the deployment model of the Theriark Website and Nowlert CE repositories: one image built once, the immutable digest deployed to Dokploy. `deploy-development.yml`, `promote-stage.yml` and `rollback.yml` are real, working definitions; `release.yml` is the release recipe and stays disabled until a release is separately approved. None of the deployment jobs has run yet; the first one runs after a merge into `development`.

## Flow

1. Feature branch `feat/revrook-ce-<phase>` and a draft pull request into `development` (or into another feature branch when stacked).
2. `ci.yml` runs the merge gate only when CI is explicitly requested for a pull request (see "How CI is started"); a push to a feature branch runs nothing. Superseded runs are cancelled.
3. Merge into `development` runs `deploy-development.yml`: the whole gate (`ci.yml` as a reusable workflow), then the job `deploy-development` (environment `development`): one image tagged `sha-<full source SHA>` is built and pushed to GHCR, and its digest is deployed to the Development Dokploy application (`ce-dev-revrook.theriark.dev`) by `.github/actions/dokploy-deploy`. The run summary records the source SHA, the digest and the previous image (the rollback target).
4. `promote-stage.yml` (`workflow_dispatch`, input `source_sha`, environment `stage`) resolves the digest published for that SHA (no rebuild), confirms Development runs exactly that digest, deploys it to the Stage application (`ce-stg-revrook.theriark.dev`), verifies it, tags the image `stage` and advances the `stage` branch to the same SHA. A human approves Stage promotion before dispatching it.
5. `rollback.yml` (`workflow_dispatch`, inputs environment and a previously recorded digest) redeploys that digest to the Development or Stage application and verifies it. It does not downgrade the database.
6. Human QA in Jira follows Stage. `release.yml` (version alias, `main` fast-forward, GitHub release, no rebuild) is disabled until a release is separately approved; the production Dokploy application on VM-10 does not exist yet. Development and Stage run on VM-09.

### How a deployment is verified (`.github/actions/dokploy-deploy`)

It fails closed, in this order: the image must match `ghcr.io/theriark/revrook-ce@sha256:<64 hex>`; the Dokploy application must carry the expected domain (`domain.byApplicationId`) and return the given application id; the previous image is read and written to the step output and summary; `application.update` sets the digest and `application.deploy` starts the deployment (POST requests are never retried); the NEW Dokploy deployment must reach `done` (`error` or `cancelled` fails); the health URL must answer HTTP 200 twice in a row; Dokploy must report exactly the requested digest. When a deployment fails after the update, the previous image is redeployed (not in `rollback.yml`). The Cloudflare Access headers and the Dokploy key come from the repository secrets `DOKPLOY_URL`, `DOKPLOY_API_KEY`, `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET`; nothing is created or deleted in Dokploy.

## How CI is started

No workflow runs on a push to a feature branch (`feat/**`, `feature/**`, `fix/**`, `chore/**` or any other). Pushing commits costs no Actions minutes.

- `ci.yml` on a pull request has exactly one trigger: `pull_request` with `types: [labeled]`. A run does anything only when the added label is `ci-go`; every job hangs off `detect`, which carries `if: github.event.label.name == 'ci-go'`, and the summary job carries the same condition. Any other label produces a run whose jobs are all skipped. It also has its own concurrency group, so it cannot cancel a `ci-go` run.
- The label `ci-go` is set only by the CI request broker (`python3 /opt/pi-crews/shared/theriark_crew_task_client.py --action ci_request --repo revrook-ce --branch <branch>`). It allows one request per commit, at most one per pull request every 3 minutes, 12 a day per pull request, and none while a run of the repository is queued or running. Publish a change as ONE commit first, then request CI once.
- `ci.yml` also keeps `workflow_dispatch` (manual) and `workflow_call` (used by `deploy-development.yml`).
- `deploy-development.yml` runs on push to `development` only (a merge): the gate, then the build and the Development deployment. `promote-stage.yml`, `rollback.yml`, `release.yml` and `lock-requirements.yml` are `workflow_dispatch` only.

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
- With STRICT `"true"` the called `ci.yml` run (including its `gate` job) must succeed before the `deploy-development` job can start, so nothing is deployed from an unverified commit.

### Branch protection and ownership (human action, not set by this repository)

Branch protection cannot be set from YAML and has NOT been verified or changed. Required configuration for `development` and `main`:

- Require only the PR-run check `Merge gate summary` (through `deploy-development.yml` it appears as `Tests (merge gate) / Merge gate summary`, which is not the one to require). Never require the individual jobs: a skipped required job counts as passing.
- Require a pull request and a code-owner review for changes under `.github/`.
- Add `.github/CODEOWNERS` with `/.github/ @<owner>`. The owner handle or team must be supplied by a human; none could be verified, and an unknown owner makes GitHub ignore the rule, so no file is added here.

## Guard rails

- GitHub-hosted `ubuntu-latest` only. No self-hosted runner, no paid overage.
- Least privilege: `contents: read`, plus `packages: write` only in the image build job. `pull_request`, never `pull_request_target`; CI needs no secrets.
- PR runs: one group per ref with cancel-in-progress true (they build nothing that is published and deploy nothing, so cancelling them is safe). The deploying workflows (`deploy-development.yml`, `promote-stage.yml`, `rollback.yml`, `release.yml`) and `lock-requirements.yml` use the one group `revrook-ce-delivery` with cancel-in-progress false, so a running deployment is never cancelled and two deployments of this repository never overlap. PR CI cannot join that group: it would cancel a live deployment, and `deploy-development.yml` calls `ci.yml` inside that group. This serializes this repository only; cross-repository serialization is not provided by this YAML.
- Queue depth is one. A concurrency group holds one running and one pending run; a newer pending run replaces the older pending one. Two quick merges can therefore leave the middle commit without an image. Promote only a source SHA whose `sha-<SHA>` image exists (`promote-stage.yml` fails when it does not). A running deployment is never cancelled.
- Deployment secrets are referenced only as `${{ secrets.NAME }}` from the `development` and `stage` GitHub environments, never printed, and passed to the composite action as inputs (masked by GitHub). Identity of the target (domain and application id) is checked before any write.
- `release.yml` fails at its guard while `RELEASE_ENABLED` is `"false"`. Workflow files that are not on the default branch cannot be dispatched, which is a second barrier.
- CI-only database credentials are throwaway values that protect nothing.
- Dependabot (`.github/dependabot.yml`) proposes weekly GitHub Actions updates.
- GHCR: `deploy-development.yml` publishes with the repository `GITHUB_TOKEN` only, one tag `sha-<full SHA>` (plus `stage` and `v<version>` aliases of an existing digest later), never `latest`. The repository is public, so a package published from it may inherit public visibility; GITHUB_TOKEN cannot change package visibility, so a human checks the package settings. Dokploy must be able to pull the image (registry access configured in Dokploy); a pull failure shows as a failed Dokploy deployment.

## Lock files (lock-requirements.yml)

`requirements.txt` and `requirements-dev.txt` are generated by `lock-requirements.yml`, not by hand and not on a developer machine: `pip-compile --generate-hashes --strip-extras` on `ubuntu-latest` with Python 3.12, runtime first, then development. The workflow is `workflow_dispatch` only: it never runs on a push (`gh workflow run lock-requirements.yml --ref <branch>` after changing `requirements.in` or `requirements-dev.in`; it skips `main`, `development`, `stage` and `production`). It needs only the repository token (`contents: write`), no secret, and does nothing for forks. It commits only when the compiled files differ, and it has no push trigger, so its commit cannot start it again; a push made with `GITHUB_TOKEN` does not start any push or `pull_request` workflow.

The lock commit therefore does not start CI. Request one CI run for the new head with the CI request broker (label `ci-go`, see "How CI is started"). The workflow summary says so.

## Known gaps

- Every `uses:` line in `.github/workflows` names a full 40-character commit SHA with the major version tag in a comment. Each SHA was resolved from the tag in the action's own repository; the comment records the major tag, not a patch release. Dependabot proposes updates.
- `pip-audit` is pinned to `==2.10.1` (upstream tag `v2.10.1`). The tag was verified in the pypa/pip-audit repository; publication of that version on PyPI was not checked directly and is first exercised by check 5 once the application exists.
- Plan check 6 "no development package in the final image" is implemented by `scripts/check_image_packages.sh`, which check 9 runs through `scripts/e2e/phase_00.sh`.
- Branch protection and `.github/CODEOWNERS` need a human (see above).
- No `actionlint` or `shellcheck` run was available. `ci.yml` and `lock-requirements.yml` have run on GitHub; `deploy-development.yml`, `promote-stage.yml`, `rollback.yml`, `release.yml` and `.github/actions/dokploy-deploy` have never been executed (the first deployment happens after a merge into `development`). The Dokploy API shapes (`application.one`, `application.update`, `application.deploy`, `deployment.allByType`, `domain.byApplicationId`) follow the Nowlert CE helper; `sourceType` is sent as `docker` on update, and a rejected payload fails the run.
- The application does not yet report its source revision: `/healthz` returns only `{"status": "ok"}`. The deployment check therefore proves identity through the new Dokploy deployment reaching `done` and Dokploy reporting the exact digest, plus two healthy responses. If `/healthz` (or a version endpoint at the same URL) later returns `revision` or `source_sha`, the action compares it with the source SHA and fails on a mismatch. Adding that field is Backend work (follow-up for Delivery).
- Production: no production Dokploy application, GitHub environment use or deployment exists; `release.yml` performs no production deployment.
- Phase 0 must add a test that fails when a module in a nested subpackage such as `app/checks/<pkg>/<module>.py` is below 95 percent coverage.

## Known differences from the reference repositories

- Deployment follows the Theriark Website and Nowlert CE model (GitHub Actions builds, pushes to GHCR and deploys to Dokploy). Where they differ, the Website version was chosen: the Stage image is the Development image with a `stage` tag and a fast-forward of the `stage` branch, `promote-stage.yml` takes only the source SHA, and the Stage candidate must be the current `development` head. Differences kept from Nowlert CE: the immutable digest (not a tag) is what Dokploy is configured with, and the image is verified through the Dokploy API.
- Not adopted: Nowlert CE's AWS ledger, its network-isolated Stage test run and its AWS role, because this product has none of them and no credential may be added here. The Website's webhook-based Stage trigger is replaced by the Dokploy API call with the Cloudflare Access headers.
- Dokploy application ids and hosts are those registered for this product by the setup broker (`github_repo_status`); none is copied from another repository.
