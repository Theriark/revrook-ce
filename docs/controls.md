# The control library and the check engine (phase 5)

`data/controls.yaml` is ruleset PC-RULES v0.1: the 51 controls of rnd-report-3
section 3.4, in 8 domains (weights 22, 14, 10, 12, 16, 6, 8, 12, adding up to 100),
with 3 gate controls (PC-ACC-01, PC-ACC-02, PC-BCK-01) and 8 manual-only controls.
The wording, tests, weights and thresholds are our own, uncalibrated design
choices. Part 1 loads and validates the file; part 2 (below) evaluates a control
from stored facts.

## What a control carries

| Key | Meaning |
| --- | --- |
| `id`, `domain`, `title` | `PC-<domain>-<number>`, one of the 8 domain codes, our wording |
| `weight`, `gate` | 3 critical, 2 important, 1 baseline; a gate failure caps the overall score |
| `manual_only`, `artefact` | the control is judged from a dated manual artefact, which is named |
| `max_age_days` | freshness maximum age, `automatic` and `manual`; empty (null) where the report names none |
| `sources` | source codes G, X, R, B, N, D, T, H, M (see the file) |
| `fields` | the fields the rule reads; each is a key of `field_map` or `unavailable` |
| `rule` | `text` is the report's rule; `kind` share, count or manual add exact numbers (`pass`, `partial`), `state` is written out in `text` only |
| `automatic_unavailable` | CE cannot compute the automatic measure (licence tier, a permission outside the verified list, no importer): the control is unknown with reason `licence_or_scope`, never pass and never fail |
| `params` | the numbers and words a rule uses besides its `pass` and `partial` thresholds (a window in days, a share, the risky ports); the engine reads each one from here and holds no number of its own |
| `manual_alternative` | an automatic control accepts a dated manual artefact at quality 0.9 |
| `mappings` | external framework identifiers, identifiers only, each with `verified: false` |

`field_map` says which importer column carries each field, and `unavailable` lists
the fields no CE importer reads, with the reason. `tests/control_fields.yaml` (phase
4) must stay equal to the list derived from this file; `tests/test_control_fields.py`
fails on any difference and on an orphan field.

## Validation

`app/checks/controls.schema.json` is a JSON Schema (draft 2020-12) for the file. It
checks every key, type and allowed word, and the rules that follow from a control
being manual-only. `app/checks/library.py` then checks what a schema cannot: control
ids are unique and agree with their domain, domain weights add up to 100, every
field a control reads is declared and read by a control, and a pair of thresholds
is in order. A file that fails is refused with every problem named. The command

```bash
python -m app.cli verify-controls
```

loads the file and the NIST datasets (it needs no database and no keys) and prints
the counts. It exits non-zero unless the library has the numbers of rnd-report-3
section 3.4 (51 controls, 8 domains whose weights add up to 100, 3 gates and 8
manual-only controls), the check engine has a rule for exactly the controls that
are measured from facts and the file gives each rule exactly the parameters it
reads, and every NIST name has a mapping row and the other way round. The
end-to-end script `scripts/e2e/phase_05.sh` runs it inside the image.

## The check engine

`app/checks/engine.py` and the rule modules next to it (`identity.py`, `devices.py`,
`email.py`, `backup.py`, `network.py`, `monitoring.py`) are pure functions. They read
`Evidence` (`app/checks/model.py`): the stored facts of each source, the manual
evidence and not-applicable decisions a person recorded, the exceptions, the vendor
lifecycle table and the pack date as an injected value. They read no database, no
clock and no network, so the same evidence always gives the same results.

Of the 51 controls, 8 are manual-only, 36 are measured from facts by a rule and 7
are `automatic_unavailable` (PC-ACC-06, PC-ACC-07, PC-BCK-02, PC-DEV-06, PC-END-03,
PC-END-05, PC-GOV-06): 43 are evaluated from evidence, which is the number of
phase-plan-3. (The ticket text says 48 automatic controls; the control file and
phase-plan-3 give 43, and the vectors follow the file.)

### One result per control

`evaluate_control` returns a status (`pass`, `partial`, `fail`, `unknown`, `na`)
with a reason, the numerator and denominator the rule counted, the evidence quality,
the age of the evidence and whether it is past its maximum age. It decides in this
order:

1. A not-applicable decision with a reason and a named reviewer makes the control
   `na`. A GATE control needs a second reviewer who is another person; without one
   the decision is refused, a note says why, and the control is evaluated as if it
   had not been made.
2. A manual-only control is judged from its artefact. Without one it is `unknown`
   with the reason `no_artefact`.
3. An automatic control that CE cannot measure is `unknown` with the reason
   `licence_or_scope`. Otherwise its rule reads the facts. A field that is absent is
   never `pass` and never `fail`: it is `unknown` with `licence_or_scope`; so is an
   export that holds no row of the kind a rule reads. An empty population inside an
   export that does have the field is `unknown` with `empty_population` for a share
   rule, and `pass` for a rule where nothing is wanted (no administrator, no shared
   mailbox, no leaver past the grace period), as the report says.
   A value that cannot be told (a flag that is missing, a lookup that failed) is
   `unknown` with `unresolved_values` or `lookup_failed` and is never read kindly: it
   cannot lift a failure and cannot complete a pass.
   A share rule (PC-ACC-01, PC-DEV-02, 04, 05 and 07, PC-END-01, 02 and 04,
   PC-NET-05, PC-BCK-01 for a server whose successful job gives no schedule,
   PC-BCK-05, PC-LOG-06) keeps such rows in the denominator. It works the share out
   twice, with every row that cannot be told counted as a pass and as a fail, and
   the control has a status only when both ends give the same one; otherwise it is
   `unknown` with `unresolved_values`, as for a count rule. 100 members of whom 99
   have a blank `mfa_capable` are `unknown`, never a pass of 1 of 1. A row that is
   certainly not a pass (a failed backup job, an end-of-support firewall) still fails
   whatever its other values. PC-NET-04 treats a Wi-Fi security mode the importer did
   not recognise (`other`) like a missing one: unknown, not a pass.
4. When the automatic result is `unknown` and a person recorded a manual artefact or
   an attestation for the control, that judgement is used, at the quality of the
   manual evidence.
5. The open exceptions of the control are attached to the result.

A result is stale when the age of its evidence is past the maximum age of the
control (automatic or manual, from the file). The underlying status is kept; the
scoring engine of phase 6 decays it.

### Quality, the 0.9 cap and attestations

`q` is 1 for an automatic export with its capture time, 0.9 for a manual artefact
with its SHA-256, a named reviewer and a date (`manual_alternative_quality`), and
0.6 for an attestation without an artefact (`attestation_quality`); an artefact that
lacks its hash or its reviewer counts as an attestation. `control_score` is `r x q`
with `r` 1 for a pass, one half for a partial and 0 otherwise, so a manual-only
control can earn at most 0.9 of its weight (`contribution`). Both quality factors
are in the control file.

### The exceptions register

`app/exceptions.py` holds the data structure. An exception names the control, an
owner, a reason (at most 2000 characters), the compensating control (what the client
does instead, optional) and a review date. It is shown beside the result of its
control (`ControlResult.exceptions`) with an overdue flag when its review date is
before the pack date. **It never changes a status, never raises a score and never
counts as evidence**: a failed control with an exception is still a failed control,
and the exception tells the reader that someone accepted it and when to look again.
A closed exception is not passed to the engine. `exception_problems` says what an
entry lacks before it is saved. The register screens are phase 9.

### Vectors

`tests/vectors/<control>.json` holds the vectors of every control that is evaluated
from evidence (43 files, at least 6 vectors each: pass, partial and fail at and one
step either side of each threshold, an absent field, a missing source, an empty
population). They are written by `tools/make_vectors.py` from `data/controls.yaml`:
the expected share or count is worked out from the thresholds of the file with exact
fractions, not by the engine, and a rule written out in words has its expected
result written by hand from the rule text. `tests/test_check_vectors.py` runs the
engine on every vector and fails when a stored file differs from what the generator
writes now, so a changed threshold cannot leave a stale vector behind. To regenerate
after a deliberate change of the control file:

```bash
python3 tools/make_vectors.py
```

### Nothing external is rendered while it is unverified

`app/checks/render.py` is the one place that prints a control for a report. It takes
the external identifiers from `app.checks.library.visible_mappings` and prints only
the rows a person marked `verified: true`, with the NIST name and credit for those
rows. A row that is still `verified: false` never reaches the output: not its
identifier, not its framework label, not its NIST name or credit. A test renders all
51 controls and looks for all of them.

## External frameworks

CIS Controls, ISO 27001, Cyber Essentials, NIS2 and the NIST identifiers are
navigation aids to our own wording. Nothing from CIS, the Secure Controls Framework,
ISO text, the CSA CCM or SIG is embedded. Every mapping row ships `verified: false`
(`uncertain: true` is the report's [U] marker). A report prints an external
identifier only for a row a person has verified, and must take its identifiers from
`app.checks.library.visible_mappings`.

NIST CSF 2.0 and NIST SP 800-171 Rev 3 names come from the NIST OSCAL content
repository (public domain, and CC0 1.0): `data/nist/nist-csf-2.0-names.json` and
`data/nist/nist-sp800-171r3-names.json`, each with its credit, source file, commit
and licence, and a row in `LICENSES-CONTENT.md`. Only the identifiers the file maps
to are included. A NIST name is shown only for a verified row, with the credit
(`app.checks.reference.credit_lines`).

## Open points for R&D

- Where the report names one freshness age for an automatic control (for example F7)
  it does not name the manual age; the file leaves it empty.
- `PC-ACC-07` and `PC-BCK-02` are marked `automatic_unavailable` because their
  measure needs a field no CE importer reads (guest sign-in activity and the
  invitation setting; the licensed mailbox and site counts). R&D should confirm.
- `PC-END-03` needs `R.threats` and `PC-END-05` needs `R.installed_software`; no
  importer yields them and none was invented. Both are unknown with
  `licence_or_scope` until R&D decides whether to add an importer. The reason on the
  *field* `R.installed_software` is `shipped_list` (it would be compared with a table
  we ship) while the reason on the *control* is `licence_or_scope` (no importer): the
  two describe different things, rnd-report-3 section 3.4 names neither word, and the
  current behaviour is kept. Question for R&D: should the control carry the field's
  reason?
- `PC-BCK-01` (a GATE) lists the licensed mailboxes `G.licensedMailboxes` among its
  fields, which no CE importer reads, and is not flagged unavailable. The engine
  reads the servers of the RMM inventory as the in-scope assets and leaves mailboxes
  out; the GATE can therefore pass without any mailbox being backed up. rnd-report-3
  says "in-scope assets from R servers and G licensed mailboxes". Question for R&D:
  keep servers only in CE, or make the control unknown until the mailbox count is
  imported?
- `PC-LOG-02` reads no import field: it reads our own versioned log-retention table
  (passed to the engine as `licence_log_retention_days`) and a manual artefact. That
  table does not exist yet; without it and without an artefact the control is
  unknown.
- The vendor end-of-support table that `PC-DEV-03` needs is shipped data that does
  not exist yet; the engine takes it as `Evidence.lifecycle` and is unknown without
  it.
- PC-EML-01 to 03 read the facts of our own DNS check (phase 7), in the shape
  documented in `app/checks/email.py`. A client that has never been checked has
  these three controls unknown with `licence_or_scope`. Phase 7 stores a check as
  evidence of the source `dns-check` (`app/dns_service.py`); a lookup that timed out
  or failed is stored as `lookup_failed` with its reason and the controls are then
  unknown with `lookup_failed`, never a fail. See `docs/dns-check.md`.

## Known gaps (not fixed in phase 5)

- A naive `Evidence.as_of` (no time zone) raises `TypeError` when it is compared
  with a capture time, which is always timezone aware. Whoever builds the evidence
  must pass an aware `as_of`; the phase 6 scoring step builds it and is the place
  to reject a naive one with a clear error.
- The reason and the reviewer of a not-applicable decision (`NaReview`) have no
  length limit and the reason is copied into `result.detail`. Phase 8 must escape it
  when it renders HTML or a PDF, and should cap it where it is saved.
- A firewall rule source such as `0.0.0.0/0 - LAN` (an address and a name around a
  spaced dash) is read as one word and is unknown. This is not fail-open (an unknown
  source never counts as restricted), but it is less exact than before the spaces
  around the dash of a range were joined.
