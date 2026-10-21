# CI/CD flow

The application exists since phase 0, so `STRICT` is `"true"`: every check runs and a skipped check fails the gate (see below). GitHub Actions itself builds, publishes and deploys, using the deployment model of the two reference repositories: one image built once, the immutable digest deployed to Dokploy.

**Development deployment is switched on by a repository variable.** The job `deploy-development` runs only when the repository variable `DEPLOY_DEVELOPMENT_ENABLED` is `true`; unset, a merge into `development` runs the gate and deploys nothing and pushes no image. The variable cannot be read from the repository files. At the time of writing (2026-10-21) the Development site (`ce-dev-revrook.theriark.dev`) is deployed by this job after every merge into `development`, so on this repository it is set; a repository admin set it after Core/IT confirmed the Development prerequisites of the dev work plan (VM-09 capacity, the Dokploy database, environment and volume, the GHCR package with Dokploy pull access). Setting the variable is a human action; no workflow sets it.

## The three workflows

This repository has exactly three workflows, and the GitHub Actions menu shows exactly these: `CI`, `Promote - Stage` and `Promote - Production`. No other workflow file may be added; a missing capability is reported, not solved with a new workflow.

| Workflow | File | What it does |
|----------|------|--------------|
| `CI` | `ci.yml` | The merge gate (checks 1 to 9) on a pull request labelled `ci-go`; on push to `development` the same gate and then the job `deploy-development`; on `workflow_dispatch` with `mode=lock` ONLY the job `lock` that compiles the hashed requirement files. |
| `Promote - Stage` | `promote-stage.yml` | `workflow_dispatch`, environment `stage`: promotes the Development digest to Stage, or rolls Stage back when an earlier approved digest is given. |
| `Promote - Production` | `promote-production.yml` | `workflow_dispatch`, environment `production`, separately approved: version alias, `main` fast-forward and GitHub release for the digest Stage runs. DISABLED until a production release is approved. |

## Flow

1. Feature branch `feat/revrook-ce-<phase>` and a draft pull request into `development` (or into another feature branch when stacked).
2. `CI` runs the merge gate only when CI is explicitly requested for a pull request (see "How CI is started"); a push to a feature branch runs nothing. Superseded runs are cancelled.
3. Merge into `development` runs `CI` on the push: the whole gate, then, only when `DEPLOY_DEVELOPMENT_ENABLED` is `true`, the job `deploy-development` (environment `development`, only after the gate succeeded): one image tagged `sha-<full source SHA>` is built and pushed to GHCR, and its digest is deployed to the Development Dokploy application (`ce-dev-revrook.theriark.dev`) by `.github/actions/dokploy-deploy`. The run summary records the source SHA, the digest and the previous image (the rollback target).
4. `Promote - Stage` (input `source_sha`, optional `digest`) with the digest left empty: `source_sha` must be the current `development` head; the `stage` branch must exist and advancing it must be a fast-forward (checked before any Stage write); the digest published for it is resolved (no rebuild), Development must run exactly that digest, it is deployed to the Stage application (`ce-stg-revrook.theriark.dev`) and verified, the image is tagged `stage` and the `stage` branch is advanced to the same SHA. A human approves Stage promotion before dispatching it.
5. Rollback is not a workflow. Running `Promote - Stage` with an earlier approved `source_sha` AND its `digest` redeploys that digest to Stage: `source_sha` must be an earlier commit of `development`, the image tag `sha-<source_sha>` must resolve to exactly that digest, the deployed digest is verified, `stage` is re-tagged and the `stage` branch moves back to `source_sha` (only when the current `stage` head descends from it, checked before any Stage write). The same rule holds for `Promote - Production` once its deployment step exists. A rollback to Development is a merge or revert on `development`. Rollback never downgrades the database: name any irreversible migration or data-format change in the release notes before rolling back.
6. Human QA in Jira follows Stage. `Promote - Production` is disabled until a release is separately approved; the production Dokploy application on VM-10 does not exist yet. Development and Stage run on VM-09.

### How a deployment is verified (`.github/actions/dokploy-deploy`)

It fails closed, in this order: the image must match `ghcr.io/theriark/revrook-ce@sha256:<64 hex>`; the Dokploy application must carry the expected domain (`domain.byApplicationId`) and return the given application id; the previous image is read and written to the step output and summary; `application.update` sets the digest and `application.deploy` starts the deployment (POST requests are never retried); the NEW Dokploy deployment must reach `done` (`error` or `cancelled` fails); the health URL must answer HTTP 200 twice in a row; Dokploy must report exactly the requested digest. When a deployment fails after the update, the previous image is redeployed (not for a rollback run). The Cloudflare Access headers and the Dokploy key come from the repository secrets `DOKPLOY_URL`, `DOKPLOY_API_KEY`, `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET`; nothing is created or deleted in Dokploy.

## How CI is started

No workflow runs on a push to a feature branch (`feat/**`, `feature/**`, `fix/**`, `chore/**` or any other). Pushing commits costs no Actions minutes.

- `CI` on a pull request has exactly one trigger: `pull_request` with `types: [labeled]`. A run does anything only when the added label is `ci-go`; every gate job hangs off `detect`, which carries the condition, and the summary job carries the same condition. Any other label produces a run whose jobs are all skipped. Pull request runs have their own concurrency group per ref (cancel-in-progress true), and a label other than `ci-go` gets a unique group, so it cannot cancel a `ci-go` run.
- The label `ci-go` is set only by the CI request broker (`python3 /opt/pi-crews/shared/theriark_crew_task_client.py --action ci_request --repo revrook-ce --branch <branch>`). It allows one request per commit, at most one per pull request every 3 minutes, 12 a day per pull request, and none while a run of the repository is queued or running. Publish a change as ONE commit first, then request CI once.
- `CI` also runs on push to `development` only (a merge) and on `workflow_dispatch`: `mode=ci` runs the gate by hand, `mode=lock` runs only the lock job.
- `Promote - Stage` and `Promote - Production` are `workflow_dispatch` only.

## Merge gate (CI)

| # | Check | Runs when (STRICT false) | STRICT true |
|---|-------|-----------|----|
| 1 | ruff check and format | `pyproject.toml` exists | always runs |
| 2 | mypy | `pyproject.toml` exists | always runs |
| 3 | pytest, PostgreSQL 16, coverage 80 percent overall, 95 percent core packages (aggregate, nested subpackages included); fails if any test is skipped | `pyproject.toml` exists | always runs |
| 4 | alembic up, check, down, up | `alembic.ini` exists | always runs |
| 5 | pip-audit, fails on any known vulnerability (exceptions in `.pip-audit-exceptions`) | `pyproject.toml` exists | always runs |
| 6 | licence audit and psycopg grep | `tools/licence_audit.py` exists | always runs |
| 7 | content licence rows (exact path match) | `data/` exists | always runs, `LICENSES-CONTENT.md` required |
| 8 | docker build, non-root check | `Dockerfile` exists, lint, typecheck, test and audit succeeded | always runs, every prerequisite must succeed |
| 9 | compose smoke (`.env.ci` copied from `.env.example`, `/readyz` on port 8080, `scripts/e2e/phase_00.sh`, then `tests/e2e/run.sh` if present; with `CI=true` a missing docker or web container fails the script instead of skipping) | `docker-compose.yml` exists, check 8 succeeded | always runs |

### STRICT

`STRICT` is a literal `"true"` or `"false"` in the `env` block of `ci.yml` (same style as `PRODUCTION_ENABLED`). It is `"true"` since phase 0, which added the application and every file the checks need (`requirements*.txt`, `alembic.ini`, `tools/licence_audit.py`, `LICENSES-CONTENT.md`, `Dockerfile`, `docker-compose.yml`). The `"false"` behaviour below is kept for reference and for a repository that starts without an application.

- `false`: a skipped check is reported as `skipped`, never a pass. `detect` fails if any application file already exists (tripwire), so the application cannot land while strict is off, and deleting one input cannot switch its check off.
- `true`: every check runs; a missing input makes its check fail. The `Merge gate summary` job fails on any result other than `success` for `detect` and checks 1 to 9, including an all-skipped run. Docs-only pull requests also run every check (no docs exemption).
- With STRICT `"true"` the `Merge gate summary` job must succeed before `deploy-development` can start, so nothing is deployed from an unverified commit.

### Branch protection and ownership (optional hardening, human action)

Branch protection cannot be set from YAML and has NOT been verified or changed. The two reference repositories have none, so nothing here blocks on it. A repository admin (human action, not done here) should also set required reviewers and a deployment-branch policy on the `development`, `stage` and `production` environments, so only the matching branch can deploy to each. Recommended for `development` and `main`:

- Require only the check `Merge gate summary`. Never require the individual jobs: a skipped required job counts as passing.
- Require a pull request and a code-owner review for changes under `.github/`, with a `.github/CODEOWNERS` entry `/.github/ @<owner>` (the owner handle or team must be supplied by a human; an unknown owner makes GitHub ignore the rule, so no file is added here).

## Guard rails

- GitHub-hosted `ubuntu-latest` only. No self-hosted runner, no paid overage.
- Least privilege: `contents: read`, plus `packages: write` only in the image build job (`deploy-development`) and `contents: write` only in the lock job and the two promotion workflows. `pull_request`, never `pull_request_target`; CI needs no secrets.
- PR runs: one group per ref with cancel-in-progress true (they build nothing that is published and deploy nothing, so cancelling them is safe). Every other run (merge to `development`, manual gate, lock, `Promote - Stage`, `Promote - Production`) uses the one group `revrook-ce-delivery` with cancel-in-progress false, so a running deployment is never cancelled and two deployments of this repository never overlap. This serializes this repository only; cross-repository serialization is not provided by this YAML.
- Queue depth is one. A concurrency group holds one running and one pending run; a newer pending run replaces the older pending one. Two quick merges can therefore leave the middle commit without an image. Promote only a source SHA whose `sha-<SHA>` image exists (`Promote - Stage` fails when it does not). A running deployment is never cancelled.
- Deployment secrets are referenced only as `${{ secrets.NAME }}`, never printed, and passed to the composite action as inputs (masked by GitHub). Identity of the target (domain and application id) is checked before any write.
- `Promote - Production` fails at its guard while `PRODUCTION_ENABLED` is `"false"`. Workflow files that are not on the default branch cannot be dispatched, which is a second barrier.
- CI-only database credentials are throwaway values that protect nothing.
- Dependabot (`.github/dependabot.yml`) proposes weekly GitHub Actions updates.
- GHCR: the `deploy-development` job publishes with the repository `GITHUB_TOKEN` only, one tag `sha-<full SHA>` (plus `stage` and `v<version>` aliases of an existing digest later), never `latest`. The repository is public, so a package published from it may inherit public visibility; GITHUB_TOKEN cannot change package visibility, so a human checks the package settings. Dokploy must be able to pull the image (registry access configured in Dokploy); a pull failure shows as a failed Dokploy deployment.

## Lock files (the lock job of CI)

`requirements.txt` and `requirements-dev.txt` are generated by the `lock` job, not by hand and not on a developer machine: `pip-compile --generate-hashes --strip-extras --allow-unsafe` on `ubuntu-latest` with Python 3.12, runtime first, then development. Dispatch it with `gh workflow run ci.yml --ref <branch> -f mode=lock` (the lock tool of the crew does exactly that) after changing `requirements.in` or `requirements-dev.in`. In that mode nothing else of `CI` runs. It never runs on a push, skips `main`, `development`, `stage` and `production`, needs only the repository token (`contents: write` on that job), no secret, and does nothing for forks. It commits only when the compiled files differ; a push made with `GITHUB_TOKEN` does not start any push or `pull_request` workflow, so its commit can neither start itself again nor start CI.

The lock commit therefore does not start CI. Request one CI run for the new head with the CI request broker (label `ci-go`, see "How CI is started"). The job summary says so.

## Known gaps

- Every `uses:` line in `.github/workflows` names a full 40-character commit SHA with the major version tag in a comment. Each SHA was resolved from the tag in the action's own repository; the comment records the major tag, not a patch release. Dependabot proposes updates.
- `pip-audit` is pinned to `==2.10.1` (upstream tag `v2.10.1`). The tag was verified in the pypa/pip-audit repository; publication of that version on PyPI was not checked directly and is first exercised by check 5 once the application exists.
- Plan check 6 "no development package in the final image" is implemented by `scripts/check_image_packages.sh`, which check 9 runs through `scripts/e2e/phase_00.sh`.
- Branch protection and `.github/CODEOWNERS` are optional hardening and need a human (see above).
- No `actionlint` or `shellcheck` run was available. The gate, lock and `deploy-development` jobs of `CI` and `.github/actions/dokploy-deploy` have run on GitHub (Development is deployed after every merge into `development`); `Promote - Stage` and `Promote - Production` have never been executed, so their Dokploy and branch steps are untested. The Dokploy API shapes (`application.one`, `application.update`, `application.deploy`, `deployment.allByType`, `domain.byApplicationId`) follow the reference repository helper; `sourceType` is sent as `docker` on update, and a rejected payload fails the run.
- Advancing or moving the `stage` and `main` branches through the API with `GITHUB_TOKEN` is rejected by GitHub if the update would change files under `.github/workflows` (the token has no `workflows` permission). That would fail the promotion after the Stage deployment; it has not been exercised. Promote while the workflow files are identical on `stage` and the promoted commit, or report the failure.
- The application does not yet report its source revision: `/healthz` returns only `{"status": "ok"}`. The deployment check therefore proves identity through the new Dokploy deployment reaching `done` and Dokploy reporting the exact digest, plus two healthy responses. If `/healthz` (or a version endpoint at the same URL) later returns `revision` or `source_sha`, the action compares it with the source SHA and fails on a mismatch. Adding that field is Backend work (follow-up for Delivery).
- Production: no production Dokploy application, GitHub environment use or deployment exists; `Promote - Production` performs no production deployment and has no rollback step until one exists.
- The 95 percent coverage floor is an aggregate over the four core packages (nested subpackages included). A per-module floor for nested subpackages is not enforced.

## Workflow differences from the reference repositories

- Deployment follows the model of the two reference repositories (GitHub Actions builds, pushes to GHCR and deploys to Dokploy). Where they differ, the website reference version was chosen: the Stage image is the Development image with a `stage` tag and a fast-forward of the `stage` branch, `Promote - Stage` takes the source SHA (plus an optional earlier digest for a rollback), and the Stage candidate must be the current `development` head. Differences kept from the CE reference: the immutable digest (not a tag) is what Dokploy is configured with, and the image is verified through the Dokploy API.
- Not adopted: the CE reference's AWS ledger, its network-isolated Stage test run and its AWS role, because this product has none of them and no credential may be added here. The website reference's webhook-based Stage trigger is replaced by the Dokploy API call with the Cloudflare Access headers.
- Dokploy application ids and hosts are those registered for this product by the setup broker (`github_repo_status`); none is copied from another repository.
