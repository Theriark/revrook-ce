# Release notes

The notes of the release candidate that the Development environment runs. revrook CE
has no released version yet: there is no tag, no GitHub release and no released image
(the only image is the one built for each `development` commit and deployed to the
Development environment, named below by its digest), and the version the application
reports is `0.0.0.dev0`
([release-candidate.md](release-candidate.md)). This page is kept for the first
candidate and grows with each one; the full list of changes is the
[CHANGELOG](../CHANGELOG.md).

## Candidate of 2026-10-21

| Fact | Value |
| --- | --- |
| Source commit (`development`) | `c41125fd4d2676e7bbed7e1bc5aee14c39c8bdac` |
| Image deployed to Development | `ghcr.io/theriark/revrook-ce@sha256:d7be83099de1fd230c5997461b28e785348d69b57fe24dce710df268c9a13333` (the manifest digest that the registry returns for the tag `sha-c41125fd...` of that commit, read on 2026-10-21; the Development deployment job deploys the image by the digest of that build) |
| Release candidate label | Not minted. The planned form is `v27.<minor>.<patch>-rc.<n>`; no tag exists yet, so the first label is pending until the automatic candidate step creates it |
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
