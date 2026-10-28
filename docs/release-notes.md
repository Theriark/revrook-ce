# Release notes

The notes of the release candidates of revrook CE built from `development`. revrook CE
has no released version yet: there is no stable tag, no stable GitHub release and no
released image (the only image is the one built for each `development` commit and
deployed to the Development environment, named below by its digest), and the version
the application reports is `0.0.0.dev0`
([release-candidate.md](release-candidate.md)). The newest candidate comes first; the
earlier ones are kept below as history. The full list of changes is the
[CHANGELOG](../CHANGELOG.md).

## Candidate of 2026-10-27

| Fact | Value |
| --- | --- |
| Application build documented and captured | commit `d0a2e9fe8c769bb3fdb8ee884a3c16199dcc57a5` (merge of pull request #83), image `ghcr.io/theriark/revrook-ce@sha256:91c6b72cb44ddd4aba33b1c04c0b2b27283311ebab5f752eba92faa5b67183ef` (deployment receipt of the Development environment: CI run 40337009384, Dokploy deployment `l4TQ87N-4OEwvBzVw-XR5`, deployed 2026-10-26T14:27:34Z, read before and after the captures). Later documentation-only commits are deployed on top with the same application code; the deployed head is read from the deployment receipt and the package manifest. |
| Layout fixes on top | commit `f6fc70857e776629e13edb04e75a353bee6682fe` (merge of pull request #84), image `ghcr.io/theriark/revrook-ce@sha256:49ab77bf0718d3ee37cb477da54a1a1fd5ea9d2ceedd51fc406f952351e6045a` (CI run 40449848051, Dokploy deployment `aPd-602wN_fXPbHuzopgJ`, deployed 2026-10-27T04:41:02Z): style rules only, fixing the five layout findings of the first capture |
| Chosen-row fix on top | application build `2e6b540ecde7561141b897e3be471ba311e53e04` (merge of pull request #86): one style rule, the links of a chosen client row let its tint through. Its pictures were captured from the deployment of documentation commit `ab870e4dd8af940747344544be459f84d773227e` (merge of pull request #87 on that build; documentation only, so the same application code), image `ghcr.io/theriark/revrook-ce@sha256:2b49e1635a8ebaccd629c65be3bf0ebc59ac20b9b954844626a178379deedf1b` (CI run 40671216666, Dokploy deployment `Om7IcLYGTMyOP2eIlEGmZ`, deployed 2026-10-28T10:37:26Z) |
| Screenshot capture source | every picture of a signed-in page was captured again, and the set of 56 holds them as the manifest counts them: 45 taken on 2026-10-27 between 01:56 and 02:32 Europe/Lisbon (UTC+00:00, so the same as UTC) on `d0a2e9fe`, the picture of the profile editor after reading a file included; 5 that showed a layout finding taken between 04:53 and 05:02 on `f6fc7085`; the 4 that show chosen rows taken on 2026-10-28 between 10:51 and 10:53 on `ab870e4d`; the two of the sign-in page were compared byte for byte with a fresh capture and kept ([capture manifest](images/README.md)) |
| Release candidate label | set by the `prepare-rc` job after the independent review of this documentation; the tags `v27.0.0-rc.1` to `v27.0.0-rc.4` name earlier candidates (`v27.0.0-rc.4` is commit `8aa84591`, before the revamp) |
| Documentation | the [guides](guides/README.md) and the README preview, every picture taken from the revamped interface |

### What changed since the candidate of 2026-10-25

The revamp of the interface: the keep, a charcoal band with the battlement of the mark
that carries the title, the purpose, the one primary action and the tabs of a client on
every page, and a stone rail in the light theme; on Home the stat cards as one ledger,
the rookery in a keep panel beside a gauge of the mean score, and the dashboard in two
columns from 1280 px; the checklist grouped by domain in library order and a control
that names the sources it reads; the exceptions register with a horizon of the coming
year; the report builder as three steps joined by a rail, with the reports made before
and the score over time beside them; the preview as a white sheet in the keep; the
export history as a ledger with the seal of each SHA-256; the settings with the cover
line of a report beside the form; the system page as tiles; the glossary with an index;
chart end labels fitted by their drawn width and tied to their lines; the navigation
wrapped on two rows from 600 to 1023 px and a cue on the scrolling strips of a phone;
and a note in the stage when the browser refuses a WebGL context. The CHANGELOG lists
each of them.

### Known limits of this candidate

The limits 1 to 8 and 10 to 13 of the earlier candidates below still hold. No limit is
added. The five layout findings of the first capture (white strips behind the labels
of a chosen card, an empty band beside the folded rail at 1440 px, the wrapped facts of
the control drawer, a broken date in the checklist at 768 px and an owner broken inside
a word) are fixed by pull request #84, and the pale highlight behind the name of a
chosen client card on a phone, which that capture also showed, is fixed by pull request
#86; the pictures that showed them were captured again on the build that carries each
fix ([capture manifest](images/README.md#known-limits-of-this-set)).

## Candidate of 2026-10-25

This section is history: the candidate of 2026-10-25.

| Fact | Value |
| --- | --- |
| Application build documented and captured | commit `b4634182e0fd68d760c209fcc6051ff9adceea2e`, image `ghcr.io/theriark/revrook-ce@sha256:cfcb12a8a3979bc10957ca220c59e26b28bbc7742669b868373a7451192ea7d5` (deployment receipt of the Development environment: CI run 40184907364, Dokploy deployment `ogG86UI70qyy2DI07CqAu`, deployed 2026-10-25T10:45:58Z, read before and after the captures). Later documentation-only commits are deployed on top with the same application code; the deployed head is read from the deployment receipt and the package manifest. |
| Screenshot capture source | the same commit and image: every picture of a signed-in page but one was captured again on 2026-10-25, between 11:03 and 11:43 Europe/Lisbon (UTC+00:00 after that morning's clock change), and the two of the sign-in page were compared byte for byte with a fresh capture; the picture of the profile editor after reading a file is still the one of 2026-10-24, without the top bar ([capture manifest](images/README.md#known-limits-of-this-set)) |
| Release candidate label | set by the `prepare-rc` job after the independent review of this documentation; the tags `v27.0.0-rc.1`, `v27.0.0-rc.2` and `v27.0.0-rc.3` name earlier candidates |
| Documentation | the [guides](guides/README.md), with the new [guide 9](guides/09-top-bar-filters-and-bulk-actions.md) for the top bar, the filters in use and the bulk actions, and the README preview |

### What changed since the candidate of 2026-10-24

The top bar of every signed-in page, with the breadcrumb and a search of the clients
that the / key reaches; the search, Status menu and Order menu of the checklist; on
Home, the score drivers (what moves the score) in place of the ring per client, and a
score chart that says when a range holds one report or none instead of drawing an empty
plot; on the clients list, the filters in use as removable chips and the bulk actions
(select, download as CSV, make reports, delete with the exact names); a report that fits
a phone, its tables scrolling in their own frames; the domain keep fitted to its stage
at every width; and the edition badge kept clear of the wordmark at 768 px. The
CHANGELOG lists each of them.

### Known limits of this candidate

The limits 1 to 8, 10 and 11 of the candidate of 2026-10-24 below still hold. Limit 9
(the keep at 768 px) is fixed: the view is fitted from the corners of every block
([guide 8](guides/08-scenes-rail-and-explorer.md)). In addition:

12. **The bulk actions run one client after another in the browser.** They use the
    report builder's and the System page's own forms, so a long selection takes as long
    as the same steps by hand, and leaving the page stops the remaining clients; the
    result card says which were done. A deletion asks for every name and takes at most
    ten clients at a time.
13. **The score drivers explain the score of today.** They are read from the evidence as
    it is now, like the checklist; the score of a stored report, on the clients list and
    in Score over time, can differ until a new report is made.

## Candidate of 2026-10-24

This section is history: the candidate of 2026-10-24.

| Fact | Value |
| --- | --- |
| Application build documented and captured | commit `314d239c38965e5ea503ba6526c62d0d2ea7b523`, image `ghcr.io/theriark/revrook-ce@sha256:30bf7d9727764d91b490a73d7b621d4284fc18397ac140e648290c4336581ca6` (deployment receipt of the Development environment: CI run 40079874064, deployed 2026-10-24T09:11:03Z, read before and after the captures). Later documentation-only commits are deployed on top with the same application code; the deployed head is read from the deployment receipt and the package manifest. |
| Screenshot capture source | the same commit and image: every picture of the guides was captured again on 2026-10-24, 11:01 to 11:10 Europe/Lisbon ([capture manifest](images/README.md)) |
| Release candidate label | set by the `prepare-rc` job after the independent review of this documentation; the tags `v27.0.0-rc.1` and `v27.0.0-rc.2` name earlier candidates |
| Documentation | the [guides](guides/README.md), with the new [guide 8](guides/08-scenes-rail-and-explorer.md) for the scenes, the folded rail, the theme switch and the Evidence Explorer, and the README preview |

### What changed since the candidate of 2026-10-21

The scenes of the interface: the rookery skyline on Home, the domain keep on a client
overview and the rookery wall of the Evidence Explorer, all drawn from facts the page
already shows, with a button that hides them in a browser; the rail that folds to its
icons from 1024 px; the Evidence Explorer as a page of the Evidence group; the dark
theme and the theme switch; the control drawer; the interactive charts; and the
synthetic seed data of the Development site. The CHANGELOG lists each of them.

### Known limits of this candidate

The limits 1 to 7 of the candidate of 2026-10-21 below still hold. In addition:

8. **The scenes were measured with a software renderer only.** The rookery, the keep
   and the wall were checked in a headless Chrome with SwiftShader on the Development
   site; no hardware GPU, phone or touch screen has been measured.
9. **At 768 px the keep can draw its front right block past the bottom of its stage**,
   depending on the angle; the bars under it are not affected
   ([guide 8](guides/08-scenes-rail-and-explorer.md#known-limits)).
10. **A preview reads the open exceptions of today.** A file is made from the stored
    snapshot together with the details, the open exceptions and the generation date at
    the time it is made, so a later preview of an older report prints an exception
    recorded after its snapshot ([reports.md](reports.md)); the export history keeps
    each exported file as it was sent.
11. **The Development site holds a second sign-in account**, created by its seed
    (`DEV_SEED_ACCOUNTS`, `app/devseed.py`); Settings lists it under Users and mappings
    and the audit trail names it. Limit 7 (one account by design) describes the
    product; the pictures keep that account out.

## Candidate of 2026-10-21

This section is history: the candidate of 2026-10-21 and the state of the tags on that
day.

| Fact | Value |
| --- | --- |
| Deployed Development candidate on 2026-10-21 | commit `f143e3db58fced1d8c993fe891174a8bb6f12873`, image `ghcr.io/theriark/revrook-ce@sha256:b5d6faed26e29c9137851f6fcbc45aa892a96788baec97ceebb7527dd923e2a0` (the deployment receipt of the Development environment: CI run 39601882209, deployed 2026-10-21T12:55:26Z, re-read on 2026-10-21) |
| Screenshot capture source | commit `c41125fd4d2676e7bbed7e1bc5aee14c39c8bdac`, image `sha256:d7be83099de1fd230c5997461b28e785348d69b57fe24dce710df268c9a13333`: what the Development site ran when the pictures of the guides were taken, earlier the same day. A different identity from the deployed candidate; no match between the two is claimed ([release-candidate.md](release-candidate.md)). Four pictures (Settings, the preview page and the two of the rendered quarterly review) were captured again later that day while the deployed candidate was running; the capture manifest marks them with its commit and digest, read from the receipt |
| Release candidate label | No tag exists in the repository (checked on 2026-10-21). The planned form is `v27.<minor>.<patch>-rc.<n>`, minted by the automatic candidate step; the labels `v27.0.0-rc.<n>` used so far name the review folders of the documentation package in Nextcloud, not tags |
| Documentation | The [guides](guides/README.md) with the live screenshots of the Development site and their [capture manifest](images/README.md) |

### What the candidate holds

Everything under Unreleased in the [CHANGELOG](../CHANGELOG.md): the sign-in and the
one administrator account, the evidence store with its hash chain, the importers for
the Microsoft 365 and the six generic exports with the profile editor, the library of
51 controls with the check engine and the exceptions register, the scoring engine with
its stored snapshots, the public DNS check, the quarterly security review and the
cyber insurance evidence pack as HTML files with an export history, the web interface
with its design system, the worker with reminders and retention, the data export, the
metrics, the extension API version 1 and the documentation set.

### Known limits of this candidate

These are visible in the product and in the documentation; none is hidden by a label.

1. **321 mapping rows are unverified.** The controls carry pointers to NIST CSF 2.0,
   NIST SP 800-171, CIS Controls, ISO/IEC 27001, Cyber Essentials and NIS2 identifiers.
   No row has been verified by a person, so no report prints an outside identifier
   ([mapping-verification.md](mapping-verification.md)).
2. **No importer for `PC-END-03` and `PC-END-05`.** They need the threat list and the
   installed software of a device, which no Community Edition importer reads; both are
   Not checked until an importer exists ([controls.md](controls.md#open-points-for-rd),
   [importers.md](importers.md#fields-no-ce-importer-reads)).
3. **No PDF export.** Both reports are one HTML file with a print stylesheet; print it to
   PDF from the browser ([pdf-spike.md](pdf-spike.md)).
4. **The copyright holder of the MIT licence is still open.** The [LICENSE](../LICENSE)
   names "Theriark"; the final legal name of the holder is a decision of the founders
   that has not been taken.
5. **Branch protection is open.** Branch protection and `.github/CODEOWNERS` on the
   repository are a human action that has not been done
   ([ci-cd.md](ci-cd.md#branch-protection-and-ownership-optional-hardening-human-action)).
6. **Scores are uncalibrated design choices** and nothing in revrook is a certification,
   audit or legal advice ([README](../README.md)).
7. The web interface has no page to create, list or revoke API tokens
   ([security.md](security.md#api-tokens)), and the Community Edition has one account
   and no user management by design.

### Before a first release

The steps are listed in [release-candidate.md](release-candidate.md#before-a-first-release):
the founders' authorisation, the decision on verified mapping rows, the version guard
and the production deployment step, the protected `production` environment, the
licence page and the version number.
