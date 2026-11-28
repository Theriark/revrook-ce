# CI/CD flow

The application exists since phase 0, so `STRICT` is `"true"`: every check runs and a skipped check fails the gate (see below). GitHub Actions itself builds, publishes and deploys, using the deployment model of the two reference repositories: one image built once, the immutable digest deployed to Dokploy.

**Development deployment is switched on by a repository variable.** The job `deploy-development` runs only when the repository variable `DEPLOY_DEVELOPMENT_ENABLED` is `true`; unset, a merge into `development` runs the gate and deploys nothing and pushes no image. The variable cannot be read from the repository files. At the time of writing (2026-10-21) the Development site (`ce-dev-revrook.theriark.dev`) is deployed by this job after every merge into `development`, so on this repository it is set; a repository admin set it after Core/IT confirmed the Development prerequisites of the dev work plan (host capacity, the Dokploy database, environment and volume, the GHCR package with Dokploy pull access). Setting the variable is a human action; no workflow sets it.

## The three workflows

This repository has exactly three workflows, the ones of the release standard: `CI`, `Promote - Stage` and `Release`. `Promote - Stage` and `Release` are one button each: `workflow_dispatch` on `development` with no required input and one optional boolean `dry_run` (default false). The approval to promote to Stage dispatches `promote-stage.yml`, and the release approval, given after human QA on Stage, dispatches `release.yml`; each approval is the human decision and no GitHub approval is added. The former `Release candidate` workflow (`prepare-rc.yml`, typed inputs) was folded into `Promote - Stage` and deleted on 2026-11-17. `tests/test_publishing_workflows.py` pins the set.

| Workflow | File | What it does |
|----------|------|--------------|
| `CI` | `ci.yml` | The merge gate (checks 1 to 9) on a pull request labelled `ci-go`; on push to `development` the same gate and then the job `deploy-development`; on `workflow_dispatch` with `mode=lock` ONLY the job `lock` that compiles the hashed requirement files. |
| `Promote - Stage` | `promote-stage.yml` | Takes the commit and digest Development runs, runs the test suite on that commit, tags the next release candidate, tags the same digest in GHCR, deploys it to Stage and verifies it (see "Flow"). It does not move `stage`. |
| `Release` | `release.yml` | Releases what Stage runs without a rebuild: GHCR tag of the version, annotated stable tag, GitHub Release (see "Release"). It does not move `main`. No Production deployment (CE). |

**No workflow moves `stage` or `main`.** GitHub refuses the Actions token (`GITHUB_TOKEN`) when it moves a branch to a commit that changes files under `.github/workflows`, and those moves would hit that every time a pull request changes a workflow. The gate script moves both branches with the operator token (release standard): after a successful `Promote - Stage` run it fast-forwards `stage` to the new candidate tag, and right before it dispatches `Release` it merges `stage` into `main` (a merge commit with Stage's files). `tests/test_publishing_workflows.py` fails if a workflow writes a branch ref, merges or pushes.

With `dry_run=true` both workflows check every precondition and change nothing: no tag, no image tag, no deployment, no release. Their run summary says what a real run does: the commit, the digest, the candidate tag and the release notes. The only traces of a dry run are the run itself and GitHub's record that the job used the `stage` environment (for the Dokploy read credentials).

## Flow

1. Feature branch `feat/revrook-ce-<task>` and a draft pull request into `development` (or into another feature branch when stacked).
2. `CI` runs the merge gate only when CI is explicitly requested for a pull request (see "How CI is started"); a push to a feature branch runs nothing. Superseded runs are cancelled.
3. Merge into `development` runs `CI` on the push: the whole gate, then, only when `DEPLOY_DEVELOPMENT_ENABLED` is `true`, the job `deploy-development` (environment `development`, only after the gate succeeded): one image tagged `sha-<full source SHA>` is built and pushed to GHCR, and its digest is deployed to the Development Dokploy application (`ce-dev-revrook.theriark.dev`) by `.github/actions/dokploy-deploy`. The run summary records the source SHA, the digest and the previous image (the rollback target).
4. `Promote - Stage`, once the promotion to Stage is approved. The job `plan` reads, from Dokploy, the digest the Development application runs; the commit is the `org.opencontainers.image.revision` label of that image. It checks that the commit is on `development`, that `sha-<commit>` is exactly that digest (built once, never rebuilt), that a successful `CI` push run on `development` for the commit has a successful `deploy-development` job, and that Development answers `/healthz`. It checks, read only, that the `stage` branch head is an ancestor of that commit, so the gate's fast-forward after the run will succeed; when `stage` is ahead or diverged the run fails here with a clear message, before the tests and any write (the `promote` job checks it again before its first write). It also reads what the Stage application runs, for the summary. `.github/scripts/release_tags.sh next` works out the candidate from the annotated tags: the open line is the highest `27.x.y` above the last stable tag that has `-rc.N` tags and no stable tag; with none open it is `27.0.0` before the first release and `27.<minor+1>.0` after it; a candidate of that line already on the commit sealing the digest is reused, otherwise the next number is minted. No other major is produced. A commit that already carries a stable tag fails: promoting a released commit again would open the next feature line with the same code, and a second release approval would publish a duplicate release. The jobs `test` (four PostgreSQL shards) and `coverage` run the test suite on that commit. Only then the job `promote` writes, in this order: the annotated tag (JSON message `sourceCommit`, `imageDigest`, `developmentRunId`, `workflowRunId`), the GHCR tag `<version>-rc.<n>` on the digest, the deployment of the digest to the Stage application (`ce-stg-revrook.theriark.dev`, title `Stage <full SHA>`), a check of `/healthz`, of the digest Dokploy reports and of the image revision, and the GHCR tag `stage`. Both the plan summary and the result summary print the candidate tag and its commit (`fast-forward stage to candidate v27.x.y-rc.N = commit <SHA>`). The gate script then fast-forwards `stage` to that candidate tag.
5. Rollback is not a button. Revert on `development`, let it deploy to Development, then promote again (a new candidate). Rollback never downgrades the database: name any irreversible migration or data-format change in the release notes.
6. Human QA follows Stage, and the release is approved after it. The gate merges `stage` into `main`, then `Release` releases what Stage runs. There is no Production deployment for CE: the release is the stable tag, the image tag and the GitHub Release.

### How a deployment is verified (`.github/actions/dokploy-deploy`)

It fails closed, in this order: the image must match `ghcr.io/theriark/revrook-ce@sha256:<64 hex>`; the Dokploy application must carry the expected domain (`domain.byApplicationId`) and return the given application id; the previous image is read and written to the step output and summary; `application.update` sets the digest and `application.deploy` starts the deployment (POST requests are never retried); the NEW Dokploy deployment must reach `done` (`error` or `cancelled` fails); the health URL must answer HTTP 200 twice in a row; Dokploy must report exactly the requested digest. When a deployment fails after the update, the previous image is redeployed (not for a rollback run). The Cloudflare Access headers and the Dokploy key come from the repository secrets `DOKPLOY_URL`, `DOKPLOY_API_KEY`, `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET`; nothing is created or deleted in Dokploy.

## Release (`release.yml`)

The release approval merges `stage` into `main` (the gate script, operator token) and then dispatches `Release` on `development`. It reads what Stage runs and never rebuilds: the commit is the `stage` branch head; the digest is what the Stage application reports in Dokploy, and it must equal `sha-<commit>` and carry the commit as its revision label; Stage must answer `/healthz`. `.github/scripts/release_tags.sh current` finds the candidate: the highest annotated `-rc.N` tag on that commit that seals the digest. The version is the candidate without `-rc.N`.

Each output is reconciled before it is written, so a re-run when everything exists succeeds and changes nothing: the GHCR tag `<version>` must be absent or already the digest; the annotated tag `v<version>` absent or already on the commit; the GitHub Release absent or already a published stable release. The release notes list the pull requests on `development`'s first-parent line since the last stable tag the commit contains (squash merges `<title> (#<n>)` and the older `Merge pull request #<n>` commits).

The writes of a real run come in this order, each skipped in a dry run: the GHCR tag, the annotated stable tag, the GitHub Release. `Release` moves no branch. A real run first checks, read only and before any write, that `main` already contains the `stage` head (the gate merged it); if not, it fails with a clear message and writes nothing, and it checks it again (GitHub compare of the `stage` head with `main`) right before the first write. A dry run only reports whether `main` contains the `stage` head: before the release approval the gate has not merged yet, so it reports false and still passes. `main` is never merged into `development`.

## How CI is started

No workflow runs on a push to a feature branch (`feat/**`, `feature/**`, `fix/**`, `chore/**` or any other). Pushing commits costs no Actions minutes.

- `CI` on a pull request has exactly one trigger: `pull_request` with `types: [labeled]`. A run does anything only when the added label is `ci-go`; every gate job hangs off `detect`, which carries the condition, and the summary job carries the same condition. Any other label produces a run whose jobs are all skipped. Pull request runs have their own concurrency group per ref (cancel-in-progress true), and a label other than `ci-go` gets a unique group, so it cannot cancel a `ci-go` run.
- The label `ci-go` is set only by the CI request broker (`python3 /opt/pi-crews/shared/theriark_crew_task_client.py --action ci_request --repo revrook-ce --branch <branch>`). It allows one request per commit, at most one per pull request every 3 minutes, 12 a day per pull request, and none while a run of the repository is queued or running. Publish a change as ONE commit first, then request CI once.
- `CI` also runs on push to `development` only (a merge) and on `workflow_dispatch`: `mode=ci` runs the gate by hand, `mode=lock` runs only the lock job.
- `Promote - Stage` and `Release` are `workflow_dispatch` only, from `development`.

## Merge gate (CI)

| # | Check | Runs when (STRICT false) | STRICT true |
|---|-------|-----------|----|
| 1 | ruff check and format | `pyproject.toml` exists | always runs |
| 2 | mypy | `pyproject.toml` exists | always runs |
| 3 | pytest, PostgreSQL 16, as four parallel shards (`TEST_SHARD=i/4` in `tests/conftest.py`: every 4th collected test, each shard with its own database); fails if any test is skipped or a shard runs none. The job `coverage` combines the four shards' data: coverage 80 percent overall, 95 percent core packages (aggregate, nested subpackages included) | `pyproject.toml` exists | always runs |
| 4 | alembic up, check, down, up | `alembic.ini` exists | always runs |
| 5 | pip-audit, fails on any known vulnerability (exceptions in `.pip-audit-exceptions`) | `pyproject.toml` exists | always runs |
| 6 | licence audit and psycopg grep | `tools/licence_audit.py` exists | always runs |
| 7 | content licence rows (exact path match) | `data/` exists | always runs, `LICENSES-CONTENT.md` required |
| 8 | docker build, non-root check (in parallel with checks 1 to 7: the image is only built and inspected, never pushed; nothing is deployed before the gate, which needs every check) | `Dockerfile` exists | always runs |
| 9 | compose smoke (`.env.ci` copied from `.env.example`, `/readyz` on port 8080, `scripts/e2e/phase_00.sh`, then `tests/e2e/run.sh` if present; with `CI=true` a missing docker or web container fails the script instead of skipping) | `docker-compose.yml` exists, check 8 succeeded | always runs |

### STRICT

`STRICT` is a literal `"true"` or `"false"` in the `env` block of `ci.yml`. It is `"true"` since phase 0, which added the application and every file the checks need (`requirements*.txt`, `alembic.ini`, `tools/licence_audit.py`, `LICENSES-CONTENT.md`, `Dockerfile`, `docker-compose.yml`). The `"false"` behaviour below is kept for reference and for a repository that starts without an application.

- `false`: a skipped check is reported as `skipped`, never a pass. `detect` fails if any application file already exists (tripwire), so the application cannot land while strict is off, and deleting one input cannot switch its check off.
- `true`: every check runs; a missing input makes its check fail. The `Merge gate summary` job fails on any result other than `success` for `detect` and checks 1 to 9, including an all-skipped run. Docs-only pull requests also run every check (no docs exemption).
- With STRICT `"true"` the `Merge gate summary` job must succeed before `deploy-development` can start, so nothing is deployed from an unverified commit.

### Branch protection and ownership (optional hardening, human action)

Branch protection cannot be set from YAML and has NOT been verified or changed. The two reference repositories have none, so nothing here blocks on it. A repository admin (human action, not done here) should also set required reviewers and a deployment-branch policy on the `development`, `stage` and `production` environments, so only the matching branch can deploy to each. Recommended for `development` and `main`:

- Require only the check `Merge gate summary`. Never require the individual jobs: a skipped required job counts as passing.
- Require a pull request and a code-owner review for changes under `.github/`, with a `.github/CODEOWNERS` entry `/.github/ @<owner>` (the owner handle or team must be supplied by a human; an unknown owner makes GitHub ignore the rule, so no file is added here).

## Guard rails

- GitHub-hosted `ubuntu-latest` only. No self-hosted runner, no paid overage.
- Least privilege: `contents: read`, plus `packages: write` only in the image build job (`deploy-development`), the `promote` job of `Promote - Stage` and `Release` (image tags) and `contents: write` only in the lock job, the `promote` job of `Promote - Stage` and `Release` (for tags and the release, never a branch; plus `actions: read` to verify earlier runs). `pull_request`, never `pull_request_target`; CI needs no secrets.
- PR runs: one group per ref with cancel-in-progress true (they build nothing that is published and deploy nothing, so cancelling them is safe). Every other run (merge to `development`, manual gate, lock, `Promote - Stage`, `Release`) uses the one group `revrook-ce-delivery` with cancel-in-progress false, so a running deployment is never cancelled and two deployments of this repository never overlap. This serializes this repository only; cross-repository serialization is not provided by this YAML.
- Queue depth is one. A concurrency group holds one running and one pending run; a newer pending run replaces the older pending one. Two quick merges can therefore leave the middle commit without an image. Promote only a source SHA whose `sha-<SHA>` image exists (`Promote - Stage` fails when it does not). A running deployment is never cancelled.
- A cancelled or missing run is uncertain. GitHub keeps only ONE pending run per concurrency group and cancels an older pending run when a newer one queues, so a queued `Promote - Stage` or `Release` dispatch can be cancelled by a later queued run of the repository without ever starting. Read the run, the tags, what Stage runs and `main` before deciding; never redispatch blindly. Both workflows reconcile what exists, so a re-run after a reconciled failure is safe.
- Deployment secrets are referenced only as `${{ secrets.NAME }}`, never printed, and passed to the composite action as inputs (masked by GitHub). Identity of the target (domain and application id) is checked before any write.
- There is no production workflow. Workflow files that are not on the default branch cannot be dispatched.
- CI-only database credentials are throwaway values that protect nothing.
- Dependabot (`.github/dependabot.yml`) proposes weekly GitHub Actions updates.
- GHCR: the `deploy-development` job publishes with the repository `GITHUB_TOKEN` only, one tag `sha-<full SHA>` (plus the aliases `<version>-rc.<n>` and `stage` from `Promote - Stage` and `<version>` from `Release`, all of the existing digest), never `latest`. The repository is public, so a package published from it may inherit public visibility; GITHUB_TOKEN cannot change package visibility, so a human checks the package settings. Dokploy must be able to pull the image (registry access configured in Dokploy); a pull failure shows as a failed Dokploy deployment.

## Lock files (the lock job of CI)

`requirements.txt` and `requirements-dev.txt` are generated by the `lock` job, not by hand and not on a developer machine: `pip-compile --generate-hashes --strip-extras --allow-unsafe` on `ubuntu-latest` with Python 3.12, runtime first, then development. Dispatch it with `gh workflow run ci.yml --ref <branch> -f mode=lock` (the lock tool of the crew does exactly that) after changing `requirements.in` or `requirements-dev.in`. In that mode nothing else of `CI` runs. It never runs on a push, skips `main`, `development`, `stage` and `production`, needs only the repository token (`contents: write` on that job), no secret, and does nothing for forks. It commits only when the compiled files differ; a push made with `GITHUB_TOKEN` does not start any push or `pull_request` workflow, so its commit can neither start itself again nor start CI.

The lock commit therefore does not start CI. Request one CI run for the new head with the CI request broker (label `ci-go`, see "How CI is started"). The job summary says so.

## Code security scanning (Datadog)

Since 2026-11-12, Datadog Code Security (EU site) scans this repository for
vulnerable libraries (SCA), code vulnerabilities (SAST), leaked secrets and
infrastructure as code (IaC). Datadog runs the scans itself through its GitHub
connection; nothing in the workflows runs them. Every push to a branch is
scanned. The results per branch are under Code Security, Repositories,
`theriark/revrook-ce`, using the branch selector. The default view shows `main`,
which holds only the workflow definitions, so read `development` for the
application. This adds to check 5 (`pip-audit`); it does not replace it.

The PostgreSQL image is pinned to a digest (`postgres:16@sha256:…`) in
`docker-compose.yml` and in the two service containers of `ci.yml`. Dependabot
(`docker-compose`) proposes a newer digest for the compose file; move the two `ci.yml`
lines to the same digest in that pull request, since Dependabot does not update service
containers of a workflow.

## Known gaps

- `Promote - Stage` and `Release` have run on GitHub only as dry runs. On 2026-11-17 (before this change) the `Release` dry run passed every read and plan step, and the `Promote - Stage` dry run stopped at its former check that `stage` could be moved without a workflow-file change; that check is gone, and only the read-only forward-only check remains. Their tag, image-tag, deployment and release steps are verified by `tests/test_publishing_workflows.py` (one-button inputs as the gate reads them, dry-run guards, concurrency, write order, no branch writes, bash syntax and the tag arithmetic of `.github/scripts/release_tags.sh` on throwaway repositories), not yet by a real run.
- Both workflows must exist on `main` to be dispatchable (the run itself uses the file on `development`). The workflow-only route of the private controller copies a workflow file from `development` to `main` once its latest change came from a merged pull request; its file list has `ci.yml`, `promote-stage.yml` and `release.yml` (all three registered on 2026-11-17). The route never deletes, so the old `prepare-rc.yml` stays on `main` as an unused definition.
- The branch moves depend on the gate script: if it does not fast-forward `stage` after a promotion, `Release` refuses (the Stage digest is not `sha-<stage head>`) until it does; if it does not merge `stage` into `main`, a real `Release` run refuses before any write (a dry run only reports it).
- Every `uses:` line in `.github/workflows` names a full 40-character commit SHA with the major version tag in a comment. Each SHA was resolved from the tag in the action's own repository; the comment records the major tag, not a patch release. Dependabot proposes updates.
- `pip-audit` is pinned to `==2.10.1` (upstream tag `v2.10.1`). The tag was verified in the pypa/pip-audit repository; publication of that version on PyPI was not checked directly and is first exercised by check 5 once the application exists.
- Plan check 6 "no development package in the final image" is implemented by `scripts/check_image_packages.sh`, which check 9 runs through `scripts/e2e/phase_00.sh`.
- Branch protection and `.github/CODEOWNERS` are optional hardening and need a human (see above).
- No `actionlint` or `shellcheck` run was available. The gate, lock and `deploy-development` jobs of `CI` and `.github/actions/dokploy-deploy` have run on GitHub (Development is deployed after every merge into `development`). The Dokploy API shapes (`application.one`, `application.update`, `application.deploy`, `deployment.allByType`, `domain.byApplicationId`) follow the reference repository helper; `sourceType` is sent as `docker` on update, and a rejected payload fails the run.
- `/healthz` returns only `{"status": "ok"}`; the application shows its source revision on the System page (`REVROOK_REVISION`), not there. `Promote - Stage` and `Release` read the revision label of the exact digest instead. The deployment check proves identity through the new Dokploy deployment reaching `done` and Dokploy reporting the exact digest, plus two healthy responses. If `/healthz` (or a version endpoint at the same URL) later returns `revision` or `source_sha`, the action compares it with the source SHA and fails on a mismatch. Adding that field is Backend work (follow-up for Delivery).
- Production: no production Dokploy application, GitHub environment use or deployment exists; no workflow deploys to production.
- The 95 percent coverage floor is an aggregate over the four core packages (nested subpackages included). A per-module floor for nested subpackages is not enforced.

## Workflow differences from the reference repositories

- Deployment follows the model of the two reference repositories (GitHub Actions builds, pushes to GHCR and deploys to Dokploy). Where they differ, the website reference version was chosen: the Stage image is the Development image with a `stage` tag, and `Promote - Stage` is one button that promotes what Development runs. Differences kept from the CE reference: the immutable digest (not a tag) is what Dokploy is configured with, and the image is verified through the Dokploy API.
- Not adopted: the CE reference's AWS ledger, its network-isolated Stage test run and its AWS role, because this product has none of them and no credential may be added here. The website reference's webhook-based Stage trigger is replaced by the Dokploy API call with the Cloudflare Access headers.
- Dokploy application ids and hosts are those registered for this product by the setup broker (`github_repo_status`); none is copied from another repository.
