# The control library (phase 5, part 1)

`data/controls.yaml` is ruleset PC-RULES v0.1: the 51 controls of rnd-report-3
section 3.4, in 8 domains (weights 22, 14, 10, 12, 16, 6, 8, 12, adding up to 100),
with 3 gate controls (PC-ACC-01, PC-ACC-02, PC-BCK-01) and 8 manual-only controls.
The wording, tests, weights and thresholds are our own, uncalibrated design
choices. This part loads and validates the file; the check engine that evaluates a
control is part 2.

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
the counts. The end-to-end script `scripts/e2e/phase_05.sh` runs it inside the image.

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

## Open points for part 2 and R&D

- Where the report names one freshness age for an automatic control (for example F7)
  it does not name the manual age; the file leaves it empty.
- `PC-ACC-07` and `PC-BCK-02` are marked `automatic_unavailable` because their
  measure needs a field no CE importer reads (guest sign-in activity and the
  invitation setting; the licensed mailbox and site counts). R&D should confirm.
- `PC-END-03` needs `R.threats` and `PC-END-05` needs `R.installed_software`; no
  importer yields them and none was invented. Both are unknown with
  `licence_or_scope` until R&D decides whether to add an importer.
- `PC-LOG-02` reads no import field: it reads our own versioned log-retention table
  and a manual artefact. That table does not exist yet.
