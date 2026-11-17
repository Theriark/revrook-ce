# CI/CD flow

The application exists since phase 0, so `STRICT` is `"true"`: every check runs and a skipped check fails the gate (see below). GitHub Actions itself builds, publishes and deploys, using the deployment model of the two reference repositories: one image built once, the immutable digest deployed to Dokploy.

**Development deployment is switched on by a repository variable.** The job `deploy-development` runs only when the repository variable `DEPLOY_DEVELOPMENT_ENABLED` is `true`; unset, a merge into `development` runs the gate and deploys nothing and pushes no image. The variable cannot be read from the repository files. At the time of writing (2026-10-21) the Development site (`ce-dev-revrook.theriark.dev`) is deployed by this job after every merge into `development`, so on this repository it is set; a repository admin set it after Core/IT confirmed the Development prerequisites of the dev work plan (VM-09 capacity, the Dokploy database, environment and volume, the GHCR package with Dokploy pull access). Setting the variable is a human action; no workflow sets it.

## The three workflows

This repository has exactly three workflows, the ones of the release standard: `CI`, `Promote - Stage` and `Release`. `Promote - Stage` and `Release` are one button each: `workflow_dispatch` on `development` with no required input and one optional boolean `dry_run` (default false). Gate 2 approval dispatches `promote-stage.yml`, Gate 3 approval dispatches `release.yml`; the approval is the human decision and no GitHub approval is added. The former `Release candidate` workflow (`prepare-rc.yml`, typed inputs) was folded into `Promote - Stage` and deleted on 2026-11-17. `tests/test_publishing_workflows.py` pins the set.

| Workflow | File | What it does |
|----------|------|--------------|
| `CI` | `ci.yml` | The merge gate (checks 1 to 9) on a pull request labelled `ci-go`; on push to `development` the same gate and then the job `deploy-development`; on `workflow_dispatch` with `mode=lock` ONLY the job `lock` that compiles the hashed requirement files. |
| `Promote - Stage` | `promote-stage.yml` | Takes the commit and digest Development runs, runs the test suite on that commit, tags the next release candidate, tags the same digest in GHCR, deploys it to Stage, verifies it and moves `stage` (see "Flow"). |
| `Release` | `release.yml` | Releases what Stage runs without a rebuild: GHCR tag of the version, annotated stable tag, GitHub Release, merge commit of `stage` into `main` (see "Release"). No Production deployment (CE). |

With `dry_run=true` both workflows check every precondition and change nothing: no tag, no image tag, no deployment, no branch move, no release. Their run summary says what a real run does: the commit, the digest, the candidate tag, the release notes and the merge. The only traces of a dry run are the run itself, GitHub's record that the job used the `stage` environment (for the Dokploy read credentials) and, for `Release`, the tree and merge commit it builds on GitHub as unreferenced objects (no ref is created or moved, nothing points at them, GitHub prunes them).

## Flow

1. Feature branch `feat/revrook-ce-<task>` and a draft pull request into `development` (or into another feature branch when stacked).
2. `CI` runs the merge gate only when CI is explicitly requested for a pull request (see "How CI is started"); a push to a feature branch runs nothing. Superseded runs are cancelled.
3. Merge into `development` runs `CI` on the push: the whole gate, then, only when `DEPLOY_DEVELOPMENT_ENABLED` is `true`, the job `deploy-development` (environment `development`, only after the gate succeeded): one image tagged `sha-<full source SHA>` is built and pushed to GHCR, and its digest is deployed to the Development Dokploy application (`ce-dev-revrook.theriark.dev`) by `.github/actions/dokploy-deploy`. The run summary records the source SHA, the digest and the previous image (the rollback target).
4. `Promote - Stage` (Gate 2). The job `plan` reads, from Dokploy, the digest the Development application runs; the commit is the `org.opencontainers.image.revision` label of that image. It checks that the commit is on `development`, that `sha-<commit>` is exactly that digest (built once, never rebuilt), that a successful `CI` push run on `development` for the commit has a successful `deploy-development` job, and that Development answers `/healthz`. It checks that `stage` exists and moves only forward (fast-forward or already there) and without any change under `.github/workflows` (see Known gaps). `.github/scripts/release_tags.sh next` works out the candidate from the annotated tags: the open line is the highest `27.x.y` above the last stable tag that has `-rc.N` tags and no stable tag; with none open it is `27.0.0` before the first release and `27.<minor+1>.0` after it; a candidate of that line already on the commit sealing the digest is reused, otherwise the next number is minted. No other major is produced. A commit that already carries a stable tag fails: promoting a released commit again would open the next feature line with the same code, and a second Gate 3 would publish a duplicate release. The jobs `test` (four PostgreSQL shards) and `coverage` run the test suite on that commit. Only then the job `promote` writes, in this order: the annotated tag (JSON message `sourceCommit`, `imageDigest`, `developmentRunId`, `workflowRunId`), the GHCR tag `<version>-rc.<n>` on the digest, the deployment of the digest to the Stage application (`ce-stg-revrook.theriark.dev`, title `Stage <full SHA>`), a check of `/healthz`, of the digest Dokploy reports and of the image revision, the GHCR tag `stage`, and the fast-forward of `stage` to the commit.
5. Rollback is not a button. Revert on `development`, let it deploy to Development, then promote again (a new candidate). Rollback never downgrades the database: name any irreversible migration or data-format change in the release notes.
6. Human QA in Jira follows Stage (Gate 3). `Release` then releases what Stage runs. There is no Production deployment for CE; the production Dokploy application on VM-10 does not exist. Development and Stage run on VM-09.

### How stage gets new workflow files

`stage` must hold the same files under `.github/workflows` as the commit being promoted, because `GITHUB_TOKEN` cannot move a branch across a workflow-file change and no credential with `workflows` permission is available to Actions in this repository (see Known gaps). Every pull request that changes `.github/workflows` brings this back at the next promotion.

- Never commit the workflow files onto `stage`. `stage` would then hold a commit that `development` lacks, the forward-only check of `Promote - Stage` refuses every promotion from then on, and only a forced move of `stage` (a human rollback of the branch) undoes it.
- The one route that passes both checks: at Gate 2, before `Promote - Stage` is dispatched, an operator with `workflows` permission fast-forwards `stage` (no force) to exactly the commit Development runs, the commit the promotion takes and the one named in the error below. `Promote - Stage` then runs as usual: `stage` is already at the commit, so the plan passes, the job tests, tags and deploys, and the branch move is skipped as already done.
- From that move until the promotion has deployed, the `stage` head is ahead of what the Stage application runs. `Release` refuses in that state (the Stage digest is not `sha-<stage head>`), so nothing can be released from it. Do it only once the open Gate 3 is decided, never while Stage holds a candidate under QA. If the promotion fails before it deploys, re-run it; `Release` stays refused until it succeeds.

What a `Promote - Stage` dry run reports today. On 2026-11-17 the product is at Gate 3: Stage runs the candidate of `d31fd03b76679898c59c3d56f194524ec6ba5d86`, which is also the `stage` head, and Stage keeps it until Gate 3 is decided. `stage` holds `ci.yml`, `promote-stage.yml` and `prepare-rc.yml` as of that commit. Once this change is merged into `development` and deployed to Development, a dry run fails in the job `plan`, step "Check that stage can move to the commit", with `moving stage from d31fd03… to <commit Development runs> changes workflow files (.github/workflows/ci.yml, .github/workflows/prepare-rc.yml, .github/workflows/promote-stage.yml, .github/workflows/release.yml); GITHUB_TOKEN cannot do that`, followed by the route above. The candidate is not worked out, the jobs `test`, `coverage` and `promote` are skipped, and nothing is written. That is the expected result until the next Gate 2 alignment; it says nothing about the candidate Stage runs now.

### How a deployment is verified (`.github/actions/dokploy-deploy`)

It fails closed, in this order: the image must match `ghcr.io/theriark/revrook-ce@sha256:<64 hex>`; the Dokploy application must carry the expected domain (`domain.byApplicationId`) and return the given application id; the previous image is read and written to the step output and summary; `application.update` sets the digest and `application.deploy` starts the deployment (POST requests are never retried); the NEW Dokploy deployment must reach `done` (`error` or `cancelled` fails); the health URL must answer HTTP 200 twice in a row; Dokploy must report exactly the requested digest. When a deployment fails after the update, the previous image is redeployed (not for a rollback run). The Cloudflare Access headers and the Dokploy key come from the repository secrets `DOKPLOY_URL`, `DOKPLOY_API_KEY`, `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET`; nothing is created or deleted in Dokploy.

## Release (`release.yml`)

Gate 3 approval dispatches `Release` on `development`. It reads what Stage runs and never rebuilds: the commit is the `stage` branch head; the digest is what the Stage application reports in Dokploy, and it must equal `sha-<commit>` and carry the commit as its revision label; Stage must answer `/healthz`. `.github/scripts/release_tags.sh current` finds the candidate: the highest annotated `-rc.N` tag on that commit that seals the digest. The version is the candidate without `-rc.N`.

Each output is reconciled before it is written, so a re-run when everything exists succeeds and changes nothing: the GHCR tag `<version>` must be absent or already the digest; the annotated tag `v<version>` absent or already on the commit; the GitHub Release absent or already a published stable release. The release notes list the pull requests on `development`'s first-parent line since the last stable tag the commit contains (squash merges `<title> (#<n>)` and the older `Merge pull request #<n>` commits).

The merge of `stage` into `main` is a real merge commit with the parents `[main, stage head]` in that order, never a fast-forward of `main` to `stage`: `main` has commits of its own (the workflow registrations), 11 on 2026-11-17. `.github/scripts/release_merge.sh` plans it in the runner: its tree is Stage's tree except `.github/workflows`, which keeps `main`'s own workflow definitions (`GITHUB_TOKEN` cannot change workflow files, and they reach `main` through the workflow-only route), and it writes the two Git data API payloads. In every run, the dry run included, the plan step then reads what could refuse the move of `main`: the branch protection of `main` (`branches/main`; the token cannot read its details, so any protection fails the run) and the ruleset rules that apply to `main` (`rules/branches/main`; any rule other than `creation`, `deletion` and `non_fast_forward` fails the run). The next step builds the tree and the merge commit on GitHub, checks that GitHub's tree is the planned one and that the parents are `[main, stage]`, and leaves both unreferenced. When the `stage` head is already in `main` nothing is merged. `main` is never merged into `development`.

The writes of a real run come in this order: the move of `main` to the merge commit (fast-forward only, it fails if `main` moved), the GHCR tag, the annotated stable tag, the GitHub Release. `main` goes first because it is the write GitHub is most likely to refuse; a refusal leaves nothing published, and a re-run after the cause is settled continues because every step skips what already exists.

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
- Least privilege: `contents: read`, plus `packages: write` only in the image build job (`deploy-development`) and `contents: write` only in the lock job, the `promote` job of `Promote - Stage` and `Release` (plus `actions: read` to verify earlier runs). `pull_request`, never `pull_request_target`; CI needs no secrets.
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

- `Promote - Stage` and `Release` have not run on GitHub yet. They are verified by `tests/test_publishing_workflows.py` (one-button inputs as the gate reads them, dry-run guards, concurrency, write order, bash syntax, the tag arithmetic of `.github/scripts/release_tags.sh` and the merge plan of `.github/scripts/release_merge.sh` on throwaway repositories) and by local runs of the release-notes step and of `release_merge.sh` against the real `stage` and `main`. A `dry_run` of each is the next step.
- Both workflows must exist on `main` to be dispatchable (the run itself uses the file on `development`). The workflow-only route of the private controller copies a workflow file from `development` to `main` once its latest change came from a merged pull request. On 2026-11-17 its file list had `ci.yml`, `promote-stage.yml` and `prepare-rc.yml` for this repository; the operator reported in the review of this change that `release.yml` has been added (not verified from this repository). The route never deletes, so the old `prepare-rc.yml` stays on `main` as an unused definition.
- `stage` must hold the same files under `.github/workflows` as the promoted commit. Until an operator aligns it at the next Gate 2, every `Promote - Stage` run, dry or real, stops in `plan` before any write (see "How stage gets new workflow files").
- Every `uses:` line in `.github/workflows` names a full 40-character commit SHA with the major version tag in a comment. Each SHA was resolved from the tag in the action's own repository; the comment records the major tag, not a patch release. Dependabot proposes updates.
- `pip-audit` is pinned to `==2.10.1` (upstream tag `v2.10.1`). The tag was verified in the pypa/pip-audit repository; publication of that version on PyPI was not checked directly and is first exercised by check 5 once the application exists.
- Plan check 6 "no development package in the final image" is implemented by `scripts/check_image_packages.sh`, which check 9 runs through `scripts/e2e/phase_00.sh`.
- Branch protection and `.github/CODEOWNERS` are optional hardening and need a human (see above).
- No `actionlint` or `shellcheck` run was available. The gate, lock and `deploy-development` jobs of `CI` and `.github/actions/dokploy-deploy` have run on GitHub (Development is deployed after every merge into `development`); `Promote - Stage` and `Release` have not run, so their Dokploy read, tag, image-tag, release and branch steps are untested on GitHub. The Dokploy API shapes (`application.one`, `application.update`, `application.deploy`, `deployment.allByType`, `domain.byApplicationId`) follow the reference repository helper; `sourceType` is sent as `docker` on update, and a rejected payload fails the run.
- No credential with `workflows` permission is available to Actions for the ref moves (checked 2026-11-17). The workflows of this repository use only `GITHUB_TOKEN` and the Dokploy and Cloudflare Access secrets, no workflow of the organisation that GitHub code search indexes uses another token or a GitHub App token, and the workflow-only route runs outside Actions. The Actions secret list itself cannot be read with the crew's tools, so a secret that no workflow uses yet would not show. None was created. Consequences: (1) `stage` is aligned by an operator at every Gate 2 that follows a workflow change; (2) `GITHUB_TOKEN` is refused by GitHub when a ref move changes files under `.github/workflows`. `Promote - Stage` checks this before any write. `Release` builds the merge commit with `main`'s own workflow files, so the move of `main` changes no workflow file, but `stage` brings commits that touch `.github/workflows` (33 that `main` lacks on 2026-11-17); whether GitHub refuses the token for those is only known when `main` moves. That move is the first write, so a refusal publishes nothing: an operator with `workflows` permission moves `main` (fast-forward) to the merge commit named in the error, or the credential is added, and a re-run publishes the rest. The fix that removes both operator steps is a GitHub App or fine-grained token with Contents and Workflows write on this repository, held in the `stage` environment and used only by the two ref moves. The `stage` environment has no deployment-branch policy today (2026-11-17), so it would first need one that admits only `development`. Adding the credential is a decision for Ruben.
- The application does not yet report its source revision: `/healthz` returns only `{"status": "ok"}`. `Promote - Stage` and `Release` read the revision label of the exact digest instead. The deployment check proves identity through the new Dokploy deployment reaching `done` and Dokploy reporting the exact digest, plus two healthy responses. If `/healthz` (or a version endpoint at the same URL) later returns `revision` or `source_sha`, the action compares it with the source SHA and fails on a mismatch. Adding that field is Backend work (follow-up for Delivery).
- Production: no production Dokploy application, GitHub environment use or deployment exists; no workflow deploys to production.
- The 95 percent coverage floor is an aggregate over the four core packages (nested subpackages included). A per-module floor for nested subpackages is not enforced.

## Workflow differences from the reference repositories

- Deployment follows the model of the two reference repositories (GitHub Actions builds, pushes to GHCR and deploys to Dokploy). Where they differ, the website reference version was chosen: the Stage image is the Development image with a `stage` tag and a fast-forward of the `stage` branch, and `Promote - Stage` is one button that promotes what Development runs. Differences kept from the CE reference: the immutable digest (not a tag) is what Dokploy is configured with, and the image is verified through the Dokploy API.
- Not adopted: the CE reference's AWS ledger, its network-isolated Stage test run and its AWS role, because this product has none of them and no credential may be added here. The website reference's webhook-based Stage trigger is replaced by the Dokploy API call with the Cloudflare Access headers.
- Dokploy application ids and hosts are those registered for this product by the setup broker (`github_repo_status`); none is copied from another repository.
