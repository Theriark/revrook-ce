# Scoring: what part 2 of phase 5 decides, and the sensitivity result

The scoring engine itself (freshness, gate caps, coverage, bounds, bands, snapshots)
is phase 6. This page records what the check engine hands to it and the result of
the sensitivity harness, which belongs to phase 5.

## What the check engine hands over

For each control the engine returns a status (pass, partial, fail, unknown, na), the
evidence quality `q` (1 for an automatic export, 0.9 for a manual artefact with its
SHA-256, a named reviewer and a date, 0.6 for an attestation, 0 without evidence),
the age of the evidence and whether it is past its maximum age. `r x q` of the
scoring model is `app.checks.engine.control_score`: pass 1, partial a fixed one half,
fail, unknown and na 0. A control that only a manual artefact can show (the 8
manual-only controls) can therefore earn at most 0.9 of its weight, and a test says
so.

## The sensitivity harness

`tools/sensitivity.py` runs inside the normal test run (`tests/test_sensitivity.py`,
inside the existing checks, no new workflow). It writes
`build/sensitivity-report.json` and the end of the test output prints the summary
(`tests/conftest.py`). It asks two questions of the weights, which are our own
uncalibrated design choices:

1. How well do the published weights (3, 2 or 1 per control, and the domain weights)
   agree in ranking with equal weights (every control 1, every domain equal)? The
   answer is the Spearman rank correlation of the two overall scores.
2. Do 200 random perturbations of every control weight by one tier (1 to 2, 3 to 2,
   2 to 1 or 3) change the ranking? The answer is the Spearman correlation of each
   perturbed score with the published one.

The pre-registered thresholds (rnd-report-3 section 8, phase-plan-3) are 0.90 for
both. The clients are twelve synthetic sets of evidence drawn from a fixed seed
(20261018); every result comes from the real check engine run on a stored vector, and
each client has its own overall level and its own level per domain so that the weights
have something to disagree about. The score is the raw one of section 3.5 (weight x r
x q, no freshness, no gate cap).

### Result (ruleset PC-RULES v0.1, seed 20261018, 12 synthetic clients)

| Measure | Value | Threshold |
| --- | --- | --- |
| Spearman, published weights against equal weights | 0.993 | 0.90 |
| Spearman over 200 one-tier perturbations, minimum | 0.972 | 0.90 |
| Spearman over 200 one-tier perturbations, mean | 0.995 | 0.90 |
| Perturbations with a correlation of at least 0.90 | 1.0 (all) | |

Threshold against equal weights: met. Threshold under perturbation: met.

### What this does and does not show

- It shows that the harness and the arithmetic work and that, on these twelve
  synthetic clients, the ranking does not depend on whether a control counts 3, 2 or
  1. The result is deterministic: the same seed gives the same numbers.
- It does not calibrate anything. The clients are synthetic, twelve is few, and the
  raw score leaves out freshness and gates (phase 6). The other thresholds of the
  pre-registered experiment (two security-aware reviewers ranking real export sets,
  agreement of at least 0.70) need people and real or anonymised exports and have
  not been run.
- A result below 0.90 would still pass the ticket. It would be recorded here and in
  the ruleset note, and no weight would be changed to reach the number. The test
  `test_the_result_is_recorded_in_the_scoring_document` fails when this page does not
  state the numbers the harness prints, whatever they are.

### Running it

```bash
python3 tools/sensitivity.py            # writes build/sensitivity-report.json
python3 -m pytest tests/test_sensitivity.py -s
```

If a CI artifact upload of `build/sensitivity-report.json` is wanted, the workflow
needs one `actions/upload-artifact` step after the tests; workflow files belong to
Platform and part 2 does not edit them.
