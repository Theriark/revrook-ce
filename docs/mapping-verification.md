# Mapping verification and mapping policy

Each control of `data/controls.yaml` can carry rows that point to an identifier in an
outside framework: a NIST CSF 2.0 subcategory, a NIST SP 800-171 Rev 3 requirement, a
CIS Controls safeguard, an ISO/IEC 27001 Annex A control, a Cyber Essentials theme or a
NIS2 letter. The rows are navigation aids to our own wording. Nothing from CIS, the
Secure Controls Framework, the ISO text, the CSA CCM or SIG is copied into the
repository.

## The policy

1. **A row is an identifier and nothing more.** The wording, the test, the weight and
   the threshold of every control are our own. A row says "a reader who knows this
   identifier may want to look here", never "this control satisfies it".
2. **A row ships unverified.** Every row of the control file has `verified: false`.
3. **An unverified row never reaches a report.** `app/checks/library.py`
   (`visible_mappings`) hands out only verified rows, and `app/checks/render.py` is the
   one place that prints them. The NIST name and its credit are printed with a row,
   never without one. `tests/test_mapping_verification.py` renders the quarterly review
   and the insurance pack of the three worked clients and looks for the NIST and ISO
   identifiers of the unverified rows and for the NIST credit (the CIS, Cyber
   Essentials and NIS2 identifiers are too short or too common to search for).
4. **Only a person marks a row verified.** That person has read the control in
   `data/controls.yaml` and the statement of the identifier in its primary source, and
   agrees that the pointer is useful and not misleading. A row recalled with doubt
   carries `uncertain: true` (the `[U]` of the report); it needs the same reading.
5. **A verified row leaves a trace.** It has a line in the register below with the
   source and its version, the date it was read and the person who read it.
   `python -m app.cli verify-mappings` fails when a verified row has no line and when a
   line has no verified row.
6. **Nothing is a certification.** A mapping never means that a client complies with a
   framework, and the reports say so in their disclaimer.

## Where things stand

At the release candidate there are 321 mapping rows: csf 67, sp800-171 47, cis 61,
iso27001 63, cyber-essentials 28, nis2 55. None is verified, and 63 of them are marked
uncertain. No report prints any of them. The release candidate does not need verified
rows (the README says that mappings are unverified unless marked); whether a later
release waits for some is a decision for the maintainers.

## The two checks

`python -m app.cli verify-mappings` reads the control file, the two NIST datasets and
this page. It needs no database, no key and no network.

```bash
python -m app.cli verify-mappings            # counts, source versions, problems
python -m app.cli verify-mappings --list     # also every unverified row
python -m app.cli verify-mappings --strict   # exit 1 while any row is unverified
```

**The primary-source check** covers the two NIST frameworks. Every identifier of every
row is looked up in the pinned copy of the NIST catalog under `data/nist`, and the
command prints how many of them the catalog knows, with the commit and the catalog
version of the copy. This proves that an identifier exists in the version we cite and
that its name is the one NIST publishes there. It does not prove that the control
belongs under it; that is the judgement of the person who verifies the row.

**The register check** compares the verified rows of the control file with the
register below.

For CIS, ISO/IEC 27001, Cyber Essentials and NIS2 the repository holds no copy of the
source, so the command says that no primary source is pinned. A person reads the
publisher's own page and records its version in the register.

## Source versions

| Dataset | Primary source file | Pinned at | Catalog version |
| --- | --- | --- | --- |
| NIST CSF 2.0 | `nist.gov/CSF/v2.0/json/NIST_CSF_v2.0_catalog-min.json` | commit `78650f02ad9321bb7b817846f8fbd4f2bcd620de` of github.com/usnistgov/oscal-content | 1.2.0 (OSCAL v1.2.2) |
| NIST SP 800-171 Rev 3 | `nist.gov/SP800-171/rev3/json/NIST_SP800-171_rev3_catalog-min.json` | commit `78650f02ad9321bb7b817846f8fbd4f2bcd620de` of github.com/usnistgov/oscal-content | 1.1.0 (OSCAL v1.2.2) |

The licence of both datasets is CC0 1.0 (a work of the US government); the rows of
`LICENSES-CONTENT.md` give the date the licence text was read and the SHA-256 of each
file. The command fails when this page stops naming the commit or the version of a
dataset, so a new pin cannot be made without recording it here.

## Verifying a row

1. Read the control in `data/controls.yaml` and the statement of the identifier at its
   source (for a NIST row, the name in `data/nist`, then the publisher's text).
2. Decide. When in doubt, leave the row unverified.
3. Set `verified: true` on the row in `data/controls.yaml`.
4. Add a line to the register below.
5. Replace the SHA-256 of `data/controls.yaml` in `LICENSES-CONTENT.md` (the content
   licence test fails on a stale hash) and run `python -m app.cli verify-mappings`.
6. Open a pull request. A second person reads the register line against the source.

## Register of verified rows

The table sits between two marker comments that the command reads. It is empty: no row
has been verified yet.

<!-- register:start -->
| Control | Framework | Identifier | Source and version | Date read | Confirmed by |
| --- | --- | --- | --- | --- | --- |
<!-- register:end -->
