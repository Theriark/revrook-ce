"""Writes the golden snapshot of client B: tests/scoring_vectors/golden-snapshot-*.json.

    python3 tools/make_scoring_golden.py

The golden snapshot is an OLD snapshot on purpose: it is committed once for a ruleset
version and never rewritten while that version stands. The test
(tests/test_scoring_snapshot.py) regenerates it from its own stored inputs and
requires the same bytes, so a change of code that alters what a stored pack says
fails the test. Run this script only when the ruleset version changes, and keep the
old file next to the new one so the trend rules can be tested across versions.
"""

import sys
from collections.abc import Sequence

from app.checks.library import Library, load_library
from app.scoring.engine import domain_weights
from app.scoring.model import DEFAULT_THRESHOLDS
from app.scoring.snapshot import EvidenceRef, SnapshotInput, render_snapshot
from tools.score_inputs import (
    AS_OF,
    VECTOR_DIR,
    client_spec,
    inputs_for,
    load_clients,
)

GOLDEN = VECTOR_DIR / "golden-snapshot-client-b-pc-rules-0.1.json"
IMPORTER_VERSION = "importers-1"
EVIDENCE = (
    EvidenceRef("evidence-0001", "0123456789abcdef" * 4),
    EvidenceRef("evidence-0002", "fedcba9876543210" * 4),
    EvidenceRef("evidence-0003", "00ff" * 16),
)


def golden_input(library: Library) -> SnapshotInput:
    """The inputs of the golden snapshot: client B of the scoring vectors."""
    spec = client_spec(library, load_clients(), "B")
    return SnapshotInput(
        ruleset_id=library.ruleset_id,
        ruleset_version=library.version,
        importer_version=IMPORTER_VERSION,
        as_of=AS_OF,
        thresholds=DEFAULT_THRESHOLDS,
        domains=domain_weights(library),
        controls=inputs_for(library, spec),
        evidence=EVIDENCE,
    )


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    GOLDEN.write_bytes(render_snapshot(golden_input(load_library())))
    print(f"wrote {GOLDEN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
