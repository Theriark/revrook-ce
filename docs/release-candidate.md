# Release candidate

Where revrook CE stands against the last phase of the plan, and what the release
workflows do. Read on 2026-10-19 against the `development` branch after phase 11 part 1
(commit `05874a7`). This page records findings only: nothing was dispatched, tagged or
released, and writing it authorises none of that.

## Update of 2026-10-28 (application build `2e6b540e`, documented and captured from `ab870e4d`)

Read on 2026-10-27 and 2026-10-28 from the deployment receipt of the Development
environment, before and after each of the three capture sessions of the screenshots of
the [guides](guides/README.md); each pair of reads gave the same facts. Later
documentation-only commits are deployed on top with the same application code; the
deployed head is read from the deployment receipt and the package manifest.

| Fact | Value |
| --- | --- |
| Application build documented and captured | application build `2e6b540ecde7561141b897e3be471ba311e53e04` (merge of pull request #86), which adds one style rule (the links of a chosen client row let its tint through) to commit `f6fc70857e776629e13edb04e75a353bee6682fe` (merge of pull request #84, image `sha256:49ab77bf0718d3ee37cb477da54a1a1fd5ea9d2ceedd51fc406f952351e6045a`, CI run 40449848051, Dokploy deployment `aPd-602wN_fXPbHuzopgJ`, deployed 2026-10-27T04:41:02Z), which adds style rules only to commit `d0a2e9fe8c769bb3fdb8ee884a3c16199dcc57a5` (merge of pull request #83, image `sha256:91c6b72cb44ddd4aba33b1c04c0b2b27283311ebab5f752eba92faa5b67183ef`, CI run 40337009384, Dokploy deployment `l4TQ87N-4OEwvBzVw-XR5`, deployed 2026-10-26T14:27:34Z). The pictures were captured from the deployment of documentation commit `ab870e4dd8af940747344544be459f84d773227e` (merge of pull request #87 on that application build; it changes documentation only, so it runs the same application code), image `ghcr.io/theriark/revrook-ce@sha256:2b49e1635a8ebaccd629c65be3bf0ebc59ac20b9b954844626a178379deedf1b`, CI run 40671216666, Dokploy deployment `Om7IcLYGTMyOP2eIlEGmZ`, deployed 2026-10-28T10:37:26Z on VM-09, the revision label of the image checked against the commit |
| Screenshot capture source | 45 pictures taken on `d0a2e9fe` on 2026-10-27 between 01:56 and 02:32 Europe/Lisbon (UTC+00:00, so the same as UTC); 5 that showed a layout finding fixed by pull request #84 taken again on `f6fc7085` between 04:53 and 05:02; the 4 that show chosen rows taken again on `ab870e4d` on 2026-10-28 between 10:51 and 10:53; the 2 of the sign-in page kept after a byte-for-byte comparison with a fresh capture ([capture manifest](images/README.md)) |
| Browser acceptance of that build | the revamp was checked live by its authors and tested independently on its own heads (pull requests #76 to #84); independent documentation QA follows this documentation |
| Release candidate tags | `v27.0.0-rc.1` (commit `3d9c598e`), `v27.0.0-rc.2` (commit `742c2663`), `v27.0.0-rc.3` (commit `bf22681a`) and `v27.0.0-rc.4` (commit `8aa84591`) exist as annotated tags made by the `prepare-rc` job; none names this candidate. The tag of this candidate is minted by that job after the independent review of this documentation, not by this page |
| Documentation package | the review copy in Nextcloud under the product folder, `Documentation/<label>/`, with its own `manifest.json`; its label is set by the release crew and recorded in that manifest, not on this page |

## Update of 2026-10-25 (application build documented and captured, `b4634182`)

Read on 2026-10-25 from the deployment receipt of the Development environment, before
and after the screenshots of the [guides](guides/README.md) were captured again; both
reads gave the same facts. Later documentation-only commits are deployed on top with the
same application code; the deployed head is read from the deployment receipt and the
package manifest.

| Fact | Value |
| --- | --- |
| Application build documented and captured | commit `b4634182e0fd68d760c209fcc6051ff9adceea2e` (merge of pull request #74), image `ghcr.io/theriark/revrook-ce@sha256:cfcb12a8a3979bc10957ca220c59e26b28bbc7742669b868373a7451192ea7d5`, CI run 40184907364, Dokploy deployment `ogG86UI70qyy2DI07CqAu`, deployed 2026-10-25T10:45:58Z on VM-09, the revision label of the image checked against the commit |
| Screenshot capture source | the same commit and image: 53 pictures taken on 2026-10-25 between 11:03 and 11:43 Europe/Lisbon (UTC+00:00 after that morning's clock change, so the same as UTC), after that deployment and before any later one; the 2 of the sign-in page kept after a byte-for-byte comparison with a fresh capture; 1 picture of the profile editor kept from the set of 2026-10-24 and marked so ([capture manifest](images/README.md)) |
| Browser acceptance of that build | the live acceptance of the changed flows by their author on the same commit and image; independent documentation QA follows this documentation |
| Release candidate tags | `v27.0.0-rc.1` (commit `3d9c598e`), `v27.0.0-rc.2` (commit `742c2663`) and `v27.0.0-rc.3` (commit `bf22681a`) exist as annotated tags made by the `prepare-rc` job; none names this candidate. The tag of this candidate is minted by that job after the independent review of this documentation, not by this page |
| Documentation package | the review copy in Nextcloud under the product folder, `Documentation/<label>/`, with its own `manifest.json`; its label is set by the release crew and recorded in that manifest, not on this page |

## Update of 2026-10-24 (application build documented and captured, `314d239c`)

This section is history: the candidate of 2026-10-24.

Read on 2026-10-24 from the deployment receipt of the Development environment, before
and after the screenshots of the [guides](guides/README.md) were captured again; both
reads gave the same facts. Later documentation-only commits are deployed on top with the
same application code; the deployed head is read from the deployment receipt and the
package manifest.

| Fact | Value |
| --- | --- |
| Application build documented and captured | commit `314d239c38965e5ea503ba6526c62d0d2ea7b523` (merge of pull request #62), image `ghcr.io/theriark/revrook-ce@sha256:30bf7d9727764d91b490a73d7b621d4284fc18397ac140e648290c4336581ca6`, CI run 40079874064, Dokploy deployment `MygUWlGK_ouH3Bd-moY7T`, deployed 2026-10-24T09:11:03Z on VM-09, the revision label of the image checked against the commit |
| Screenshot capture source | the same commit and image: all 44 pictures were taken on 2026-10-24 between 11:01 and 11:10 Europe/Lisbon (10:01 to 10:10 UTC), after that deployment and before any later one ([capture manifest](images/README.md)) |
| Browser acceptance of that build | passed on the same commit and image before the captures |
| Release candidate tags | `v27.0.0-rc.1` (commit `3d9c598e`) and `v27.0.0-rc.2` (commit `742c2663`) exist as annotated tags made by the `prepare-rc` job; neither names this candidate. The tag of this candidate is minted by that job after the independent review of this documentation, not by this page |
| Documentation package | the review copy in Nextcloud under the product folder, `Documentation/<label>/`, with its own `manifest.json`; its label is set by the release crew and recorded in that manifest, not on this page |

Everything below this section is kept as it was written, as the history of earlier
readings.

## Update of 2026-10-21 (read against commit `c41125fd`)

This section is history: it describes the candidate of 2026-10-21 and the state of the
tags on that day.

Read again on 2026-10-21 against commit `c41125fd4d2676e7bbed7e1bc5aee14c39c8bdac`,
the head of `development` at the time of that reading. Two sets of facts from that day
are recorded here and must not be confused:

| Fact | Commit | Image digest | How it was read |
| --- | --- | --- | --- |
| Capture-time facts (this reading, the screenshots of the [guides](guides/README.md) and their [capture manifest](images/README.md)) | `c41125fd4d2676e7bbed7e1bc5aee14c39c8bdac` | `sha256:d7be83099de1fd230c5997461b28e785348d69b57fe24dce710df268c9a13333` | the pages of the Development site linked the stylesheets with the version query of this commit; the digest is the one the registry returned for the tag `sha-c41125fd...` on that day. Four pictures (Settings, the preview page and the two of the rendered review) were captured again between 20:31 and 20:33 Europe/Lisbon while the deployed candidate below was running; the manifest marks them with its commit and digest, read from the receipt |
| Deployed Development candidate (later the same day) | `f143e3db58fced1d8c993fe891174a8bb6f12873` | `sha256:b5d6faed26e29c9137851f6fcbc45aa892a96788baec97ceebb7527dd923e2a0` | the deployment receipt of the Development environment (CI run 39601882209, deployed 2026-10-21T12:55:26Z); re-read on 2026-10-21 |

The capture-time commit and digest are what the site ran when the pictures were taken.
The deployed candidate is a later `development` commit with its own image; the two are
different identities and no match between them is claimed. The documentation commits
merged after the candidate have no CI push run and no image of their own in the
deployment receipt (observed; the cause is not verified here), so nothing was
redeployed for them. The commit and the digest that become the first release
candidate are fixed only when the release candidate step runs, and are read then, not
from this page. The findings below stand; what changed since the first reading:

- Development is deployed automatically after every merge into `development` that
  changes the application ([ci-cd.md](ci-cd.md)), so finding R5 is answered for that
  day by the live site: the pages link the stylesheets with the version query of the
  commit they run.
- The release path now has a release candidate step, on `development`: after the
  Development checks, the complete documentation set
  ([release-notes.md](release-notes.md), the [guides](guides/README.md) and the capture
  manifest of the screenshots), the Nextcloud copy of that set and its independent
  review, the `prepare-rc` job of `ci.yml` creates an annotated tag
  `v27.<minor>.<patch>-rc.<n>` and a GitHub prerelease for the exact tested commit and
  image, without deploying Stage or publishing a stable version; `promote-stage.yml`
  consumes that tag and `finalize-release.yml` turns it into the stable tag (the
  "Release workflow check" below and [ci-cd.md](ci-cd.md)). No such tag exists in the
  repository (checked on 2026-10-21): the labels `v27.0.0-rc.<n>` name the review
  folders of the documentation package in Nextcloud, not tags, and none of these three
  workflows has been executed. Stage promotion and the stable release stay separate
  decisions with their own approval.
- The known limits of the candidate are listed in [release-notes.md](release-notes.md):
  321 unverified mapping rows, no importer for `PC-END-03` and `PC-END-05`, no PDF
  export, the open copyright holder name of the MIT licence, and the open branch
  protection (finding R9 and the hardening note of [ci-cd.md](ci-cd.md)).

## Status

- No version is released: there is no stable tag, no stable GitHub release and no
  released image (each image named in the updates above is the build of one
  `development` commit, deployed to the Development environment only). The release
  candidate tags of the update of 2026-10-24 mark Development candidates, not releases.
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

The plan also asks for an upgrade test from the previous tag. No released tag exists
(the release candidate tags are not releases), so
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
