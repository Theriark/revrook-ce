# Release candidate

Where revrook CE stands against the last phase of the plan, and what the release
workflows do. Read on 2026-10-19 against the `development` branch after phase 11 part 1
(commit `05874a7`). This page records findings only: nothing was dispatched, tagged or
released, and writing it authorises none of that.

## Status

- No version is released: there is no tag, no GitHub release and no published image.
  `pyproject.toml` and `app/__init__.py` both say `0.0.0.dev0` and the
  [CHANGELOG](../CHANGELOG.md) has only an Unreleased section.
- A release is a separate step with its own authorisation from the founders. The
  workflow that would run it fails closed until that approval enables it (finding R1).
- The Development environment runs the code of `development`. Stage and production are
  not touched by this work.

## The acceptance checks of phase 11

| # | Check of the plan | State | Where to see it |
| --- | --- | --- | --- |
| 1 | A new user follows the quick start and exports a demo quarterly review in under ten minutes | Run by the compose smoke test on every change, which fails at ten minutes; the log of the run prints the seconds | [quick-start.md](quick-start.md), `scripts/e2e/phase_11.sh` |
| 2 | No open high or medium security finding | The findings table of the review lists every finding; every finding of Medium severity is fixed and the accepted ones are Low or Info | [security-review.md](security-review.md) |
| 3 | The extension API is documented and frozen | Documented as version 1, with contract tests for every extension point | [extension-api.md](extension-api.md), `tests/test_extension_api.py` |
| 4 | The same image digest is deployed to Development and promoted to Stage in a dry run | **Not done.** It needs an explicit Stage authorisation and a dispatch, which this task may not do (finding R6) | [ci-cd.md](ci-cd.md) |
| 5 | The README states that scores are uncalibrated, that mappings are unverified unless marked and that nothing is a certification | Done; `tests/test_docs.py` fails if a statement is removed | [README](../README.md) |

The plan also asks for an upgrade test from the previous tag. No tag exists, so
`tests/test_upgrade.py` upgrades a database from each earlier schema revision instead
([upgrade.md](upgrade.md)); the test from a previous tag can be added with the first one
(finding R7).

## Mapping verification

There are 321 mapping rows and none is verified, so no report prints an outside
identifier. `python -m app.cli verify-mappings` shows the state, and checks every NIST
identifier against the pinned names extract. That is a consistency check, not a
comparison with the full NIST catalog: the extract holds the 32 CSF and 26 SP 800-171
identifiers that the control file maps, transcribed from the catalog at the recorded
commit, and its fidelity to the catalog is not re-checked here. CIS, ISO/IEC 27001,
Cyber Essentials and NIS2 have no pinned source and need a person to read the
publisher's page ([mapping-verification.md](mapping-verification.md)). The plan says the
crew marks the rows it confirmed. This phase built the command and the register and
marked no row, because a row is marked by someone who has read the source against the
control. Whether a first release waits for some verified rows is a decision for the
maintainers, and `verify-mappings --strict` is the gate if they want one.

## Release workflow check

Read from `.github/workflows/ci.yml`, `promote-stage.yml`, `finalize-release.yml` and
`promote-production.yml` and compared with the release pipeline of the plan.
`.github/workflows` holds exactly those four files; `finalize-release.yml` and the
`prepare-rc` job of `ci.yml` were added for the publishing contract (see
[ci-cd.md](ci-cd.md)), and `promote-production.yml` is unchanged.

| What the plan says | What the workflows do | Match |
| --- | --- | --- |
| Tests run before the image is built | `docker-build` needs the checks 1 to 7 to have succeeded and does not run after a failure | Yes |
| The image is built once, tagged with the commit SHA, pushed, and its digest recorded | `deploy-development` (a merge to `development`, after the whole gate, and only while the repository variable `DEPLOY_DEVELOPMENT_ENABLED` is `true`) builds once, pushes only `sha-<commit>` (never `latest`) and writes the digest into the run summary | Yes (R5) |
| Development deploys that digest | The `dokploy-deploy` action deploys `image@digest`, checks the host and the health URL and records the previous image | Yes |
| Stage promotes the same digest on explicit request | `promote-stage.yml` is `workflow_dispatch` only, needs the current head of `development`, resolves the digest of `sha-<commit>`, confirms that Development runs exactly it, deploys it to Stage without a rebuild, tags `stage` and fast-forwards the `stage` branch | Yes |
| Rollback redeploys the previous approved digest | `promote-stage.yml` with an earlier commit, its digest and its earlier RC: it refuses a digest that is not the image of that commit, creates no tag, and the database is not downgraded | Yes |
| Production only after the founders authorise it | `promote-production.yml`: a guard fails while `PRODUCTION_ENABLED` is `false`; it must be dispatched from `stage`, the `stage` branch must be the source commit and Stage must run the digest; it then aliases `v<version>`, fast-forwards `main` and creates the GitHub release | Yes (R1, R2) |
| One delivery run at a time, none cancelled while live | All four share the group `revrook-ce-delivery` with cancel-in-progress off for every run except a pull request; pull request runs have their own group, which supersedes older runs | Yes |
| The plan names a `release.yml` | There is none; its steps are in the four files above, as `docs/ci-cd.md` states | Deviation, accepted (R3) |

Findings. None is fixed here: the workflow files belong to the platform engineer.

- **R1, no production deployment step.** `promote-production.yml` aliases the image,
  moves `main` and creates the release, but it does not deploy to production: the
  production application and the GitHub `production` environment do not exist yet and
  `PRODUCTION_ENABLED` is `false`. This matches `docs/ci-cd.md`. The deployment step is
  written when production is authorised.
- **R2, the version is not checked.** The workflow checks the shape of the version input
  only. The version of the package is in `pyproject.toml`, but the version the
  application reports comes from a separate constant, `__version__` in
  `app/__init__.py`, and that is what `revrook_build_info` shows. `tests/test_packages.py`
  pins both to `0.0.0.dev0` and fails when they differ. Dispatched as `0.1.0` while the
  commit still says `0.0.0.dev0` in these files, it would tag an image whose
  `revrook_build_info` says `0.0.0.dev0`. Suggested: a guard step that reads both files
  at the source commit and fails when either differs from the input.
- **R3, no `release.yml`.** The repository has exactly four workflows by decision, so
  the build, the digest and the release candidate live in `ci.yml` (the `prepare-rc`
  job), the Stage promotion in `promote-stage.yml`, the stable tag in
  `finalize-release.yml` and the production recipe in `promote-production.yml`. No
  change needed.
- **R4, a known limit that was never exercised.** Moving `main` or `stage` with the
  workflow token is refused by GitHub when the move changes a file under
  `.github/workflows` (`docs/ci-cd.md`). In the production workflow the alias is written
  before `main` moves, so such a refusal would leave the alias behind.
- **R5, the Development switch is not visible from the files.** `deploy-development`
  runs only while the repository variable `DEPLOY_DEVELOPMENT_ENABLED` is `true`. Its
  value cannot be read from the repository, so this check could not confirm that
  Development runs the digest of the newest commit.
- **R6, the dry run was not made.** Acceptance check 4 needs `Promote - Stage` to be
  dispatched, which needs the explicit Stage authorisation.
- **R7, no earlier tag.** The upgrade test from a previous tag cannot exist before the
  first tag does.
- **R8, the licence page is behind.** `docs/licences.md` still lists packages as not read
  (for example openpyxl, hypothesis and the PDF libraries) and an open decision about
  certifi. Bring it up to date or close each item before a release.
- **R9, the `production` environment must be protected before the switch.**
  `promote-production.yml` runs in the GitHub environment `production`. GitHub creates a
  missing environment without any protection rule the first time a workflow uses it, so
  create the environment with required reviewers before `PRODUCTION_ENABLED` is set to
  `true`; otherwise the workflow would run without a human approval.

## Before a first release

1. The founders authorise the release, and the Stage promotion for the dry run (R6).
2. The maintainers decide whether some mapping rows must be verified first.
3. The platform engineer adds the version guard (R2) and the production deployment step
   (R1) when production is authorised.
4. The `production` environment is created with required reviewers before
   `PRODUCTION_ENABLED` is set to `true` (R9).
5. `docs/licences.md` is brought up to date (R8).
6. The version is set in both `pyproject.toml` and `app/__init__.py` (the application
   reports the second; `tests/test_packages.py` pins both, so that test changes with
   them) in a reviewed change, and the Unreleased section of the
   [CHANGELOG](../CHANGELOG.md) becomes the section of that version.
7. `Promote - Stage` is run from `development` with the digest that CI recorded, the
   human QA of the product follows, and only then the production workflow.
