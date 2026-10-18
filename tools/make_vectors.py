"""Writes tests/vectors/*.json: the check-engine vectors, from data/controls.yaml.

    python3 tools/make_vectors.py [OUTPUT_DIR]

One file per control that is evaluated from evidence (the 43 that are not
manual-only). A vector is a piece of evidence (see tools/vector_facts.py) and the
result the control must give, with at least six vectors per control: pass, partial
and fail at and around each threshold, unknown (an absent field, a missing source)
and an empty population.

The expected results do not come from the engine. A share or a count is worked out
here from the thresholds read straight from the control file (exact fractions); a
rule that is written out in words has its expected result written by hand from the
rule text. The test (tests/test_check_vectors.py) runs the engine on every vector
and also fails when the stored files differ from what this script writes now, so a
change of a threshold in the file cannot leave a stale vector behind.
"""

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.checks.library import CONTROLS_PATH, parse_yaml
from tools import vector_shares
from tools.vector_state import STATE_VECTORS
from tools.vector_support import Vector, ev, vec

OUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "vectors"
LOS = "licence_or_scope"


def unavailable_vectors() -> list[Vector]:
    """The controls CE cannot measure: whatever the evidence, unknown."""
    rich = vector_shares.rich_evidence()
    only_entra = {"entra-registration": rich["sources"]["entra-registration"]}
    only_inventory = {"device-inventory": rich["sources"]["device-inventory"]}
    only_exchange = {"exchange-export": rich["sources"]["exchange-export"]}
    empty = {name: {"kinds": {}} for name in rich["sources"]}
    return [
        vec("unknown-no-evidence", ev(), "unknown", LOS),
        vec("unknown-rich-evidence", rich, "unknown", LOS),
        vec("unknown-only-entra", ev(only_entra), "unknown", LOS),
        vec("unknown-only-inventory", ev(only_inventory), "unknown", LOS),
        vec("unknown-only-exchange", ev(only_exchange), "unknown", LOS),
        vec("empty-sources", ev(empty), "unknown", LOS),
    ]


def vectors_for(control: Mapping[str, Any]) -> list[Vector]:
    """The vectors of one control, from its entry of the control file."""
    control_id = control["id"]
    rule = control["rule"]
    if "automatic_unavailable" in control:
        return unavailable_vectors()
    if control_id in vector_shares.SPECS:
        return vector_shares.spec_vectors(control_id, rule)
    return STATE_VECTORS[control_id](control)


def generate() -> dict[str, dict[str, Any]]:
    """The content of every vector file, by control id."""
    document = parse_yaml(CONTROLS_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    files: dict[str, dict[str, Any]] = {}
    for control in document["controls"]:
        if control["manual_only"]:
            continue
        files[control["id"]] = {
            "control": control["id"],
            "ruleset": "PC-RULES " + document["ruleset"]["version"],
            "vectors": vectors_for(control),
        }
    return files


def render(content: Mapping[str, Any]) -> str:
    """The JSON text of a vector file: sorted keys, one vector to a line.

    A vector is a line of its own so that a change shows as a one-line difference
    and the file stays short; the text is still plain JSON.
    """
    lines = [json.dumps(vector, sort_keys=True) for vector in content["vectors"]]
    body = ",\n".join(f"    {line}" for line in lines)
    return (
        "{\n"
        f'  "control": {json.dumps(content["control"])},\n'
        f'  "ruleset": {json.dumps(content["ruleset"])},\n'
        '  "vectors": [\n'
        f"{body}\n"
        "  ]\n"
        "}\n"
    )


def write_all(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for control_id, content in sorted(generate().items()):
        path = directory / f"{control_id}.json"
        path.write_text(render(content), encoding="utf-8")
        written.append(path)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    directory = Path(arguments[0]) if arguments else OUT_DIR
    written = write_all(directory)
    print(f"wrote {len(written)} vector files to {directory}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
