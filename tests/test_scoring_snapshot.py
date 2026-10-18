"""Snapshots: byte-for-byte regeneration, tampering and trends (phase 6).

tests/scoring_vectors/golden-snapshot-client-b-pc-rules-0.1.json is an old snapshot
(client B under ruleset PC-RULES 0.1). It is committed once and never rewritten
while that ruleset version stands: regenerating it must give the same bytes
whatever else in the code has changed.
"""

import copy
import dataclasses
import hashlib
import json
from dataclasses import replace
from fractions import Fraction
from typing import Any

import pytest

from app.checks.engine import evaluate_all
from app.checks.library import load_library
from app.checks.model import Evidence
from app.scoring.engine import domain_weights, score_inputs
from app.scoring.snapshot import (
    EvidenceRef,
    SnapshotError,
    comparable,
    parse_snapshot,
    regenerate,
    render_snapshot,
    ruleset_major,
    score_snapshot,
    snapshot_document,
    snapshot_input,
    trend,
    verify_snapshot,
)
from tools.make_scoring_golden import GOLDEN, IMPORTER_VERSION, golden_input
from tools.score_inputs import AS_OF, client_spec, inputs_for, load_clients

LIBRARY = load_library()
DATA = GOLDEN.read_bytes()


def document() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(DATA)
    return loaded


def canonical(value: dict[str, Any]) -> bytes:
    text = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return text.encode("ascii")


def resign(changed: dict[str, Any]) -> bytes:
    """The document with a valid digest again, so that only its content is wrong."""
    body = {key: value for key, value in changed.items() if key != "sha256"}
    signed = {**body, "sha256": hashlib.sha256(canonical(body)).hexdigest()}
    return canonical(signed) + b"\n"


# --- an old snapshot regenerates byte for byte --------------------------------------


def test_an_old_snapshot_regenerates_byte_for_byte() -> None:
    assert regenerate(DATA) == DATA
    verify_snapshot(DATA)


def test_the_golden_snapshot_is_what_the_code_writes_for_its_own_inputs() -> None:
    """If this fails the scoring changed: bump the ruleset version, keep this file."""
    assert render_snapshot(golden_input(LIBRARY)) == DATA


def test_regeneration_reads_only_the_stored_inputs() -> None:
    """A control file that changed weights does not change a pack already made."""
    heavier = [replace(item, weight=item.weight + 1) for item in LIBRARY.controls]
    changed = dataclasses.replace(LIBRARY, controls=tuple(heavier))
    spec = client_spec(changed, load_clients(), "B")
    live = score_inputs(inputs_for(changed, spec), domain_weights(changed), AS_OF)
    assert live.raw != Fraction(23308771, 510510), "the live file does score B apart"
    assert regenerate(DATA) == DATA


def test_the_snapshot_is_canonical_ascii_json_without_a_float() -> None:
    assert DATA.isascii() and DATA.endswith(b"\n") and DATA.count(b"\n") == 1

    def refuse(text: str) -> float:
        raise AssertionError(f"a float was stored: {text}")

    loaded = json.loads(DATA, parse_float=refuse)
    assert list(loaded) == sorted(loaded)
    assert canonical(loaded) + b"\n" == DATA


def test_the_snapshot_stamps_the_ruleset_importers_inputs_and_thresholds() -> None:
    stored = document()
    assert stored["ruleset"] == {"id": "PC-RULES", "version": "0.1"}
    assert stored["importer_version"] == IMPORTER_VERSION
    assert stored["as_of"] == "2026-10-17T08:00:00+00:00"
    assert stored["thresholds"]["cap_fail"] == 49
    assert stored["thresholds"]["cap_partial"] == 69
    assert stored["thresholds"]["min_coverage"] == "3/5"
    assert [ref["id"] for ref in stored["evidence"]] == [
        "evidence-0001",
        "evidence-0002",
        "evidence-0003",
    ]
    assert len(stored["evidence"][0]["sha256"]) == 64
    assert len(stored["controls"]) == 51
    assert len(stored["results"]["controls"]) == 51
    assert stored["results"]["display"] == {
        "best_case": "69.0",
        "coverage_percent": "71",
        "raw": "45.7",
        "score": "45.7",
    }


def test_the_stored_results_are_what_the_stored_inputs_score_to() -> None:
    result = score_snapshot(parse_snapshot(DATA))
    assert result.raw == Fraction(23308771, 510510)
    assert result.coverage == Fraction(70, 99)
    assert snapshot_document(parse_snapshot(DATA)) == document()


def test_rendering_does_not_depend_on_the_order_of_the_evidence_items() -> None:
    results = evaluate_all(LIBRARY, Evidence(as_of=AS_OF))
    refs = [EvidenceRef("b", "1" * 64), EvidenceRef("a", "2" * 64)]
    first = snapshot_input(LIBRARY, results, AS_OF, refs, "importers-1")
    second = snapshot_input(LIBRARY, results, AS_OF, refs[::-1], "importers-1")
    assert render_snapshot(first) == render_snapshot(second)
    assert [ref.evidence_id for ref in first.evidence] == ["a", "b"]
    verify_snapshot(render_snapshot(first))


def test_a_snapshot_of_naive_time_cannot_be_made() -> None:
    results = evaluate_all(LIBRARY, Evidence(as_of=AS_OF))
    naive = AS_OF.replace(tzinfo=None)
    with pytest.raises(ValueError, match="as_of must carry a timezone"):
        snapshot_input(LIBRARY, results, naive, [], "importers-1")


# --- an edited or unreadable snapshot is refused ------------------------------------


def test_an_edited_snapshot_is_refused_by_its_digest() -> None:
    edited = DATA.replace(b'"status":"partial"', b'"status":"pass"', 1)
    assert edited != DATA
    with pytest.raises(SnapshotError, match="digest does not match"):
        parse_snapshot(edited)


def test_a_snapshot_with_forged_results_and_a_valid_digest_does_not_verify() -> None:
    stored = document()
    stored["results"]["display"]["score"] = "99.9"
    forged = resign(stored)
    assert parse_snapshot(forged) == parse_snapshot(DATA)
    with pytest.raises(SnapshotError, match="does not give its bytes"):
        verify_snapshot(forged)


def test_a_snapshot_written_with_other_whitespace_is_not_the_stored_bytes() -> None:
    pretty = json.dumps(document(), sort_keys=True, indent=2).encode("ascii")
    assert parse_snapshot(pretty) == parse_snapshot(DATA)
    with pytest.raises(SnapshotError, match="does not give its bytes"):
        verify_snapshot(pretty)


def mutated(change: Any) -> bytes:
    stored = copy.deepcopy(document())
    change(stored)
    return resign(stored)


def set_path(*path: Any, value: Any) -> Any:
    def change(stored: dict[str, Any]) -> None:
        target: Any = stored
        for step in path[:-1]:
            target = target[step]
        target[path[-1]] = value

    return change


BAD_DOCUMENTS = [
    ("schema", mutated(set_path("schema", value=2)), "schema 2 is not 1"),
    ("status", mutated(set_path("controls", 0, "status", value="x")), "not a status"),
    ("fraction", mutated(set_path("controls", 0, "quality", value="0.5")), "lowest"),
    ("zero", mutated(set_path("controls", 0, "quality", value="1/0")), "Fraction"),
    ("weight", mutated(set_path("controls", 0, "weight", value="3")), "whole number"),
    ("gate", mutated(set_path("controls", 0, "gate", value=1)), "true or false"),
    ("id", mutated(set_path("controls", 0, "id", value=5)), "text was expected"),
    ("domains", mutated(set_path("domains", value={})), "list was expected"),
    ("ruleset", mutated(set_path("ruleset", value=[])), "object was expected"),
    ("band", mutated(set_path("thresholds", "bands", value=[["Strong"]])), "index"),
    ("naive", mutated(set_path("as_of", value="2026-10-17T08:00:00")), "timezone"),
    ("time", mutated(set_path("as_of", value="yesterday")), "Invalid isoformat"),
    ("missing", mutated(set_path("controls", 0, value={})), "evidence_at"),
    ("not json", b"not json", "Expecting value"),
    ("not text", b"\xff\xfe", "codec"),
    ("list", b"[]", "object was expected"),
    ("no digest", b"{}", "'sha256'"),
]


@pytest.mark.parametrize(
    ("data", "message"),
    [(data, message) for _, data, message in BAD_DOCUMENTS],
    ids=[name for name, _, _ in BAD_DOCUMENTS],
)
def test_a_snapshot_that_is_not_valid_is_refused_with_a_snapshot_error(
    data: bytes, message: str
) -> None:
    with pytest.raises(SnapshotError, match=message):
        parse_snapshot(data)
    with pytest.raises(ValueError, match="cannot be read"):
        regenerate(data)


# --- trends only within the same ruleset major version ------------------------------


@pytest.mark.parametrize(
    ("version", "major"),
    [
        ("0.1", "0.1"),
        ("0.2", "0.2"),
        ("0", "0"),
        ("1.0", "1"),
        ("1.4.2", "1"),
        ("2", "2"),
    ],
)
def test_the_ruleset_major_version_counts_the_minor_number_while_it_is_zero(
    version: str, major: str
) -> None:
    assert ruleset_major(version) == major


@pytest.mark.parametrize("version", ["", "x", "1.a", "1..2", "v1"])
def test_a_ruleset_version_must_be_numbers_separated_by_dots(version: str) -> None:
    with pytest.raises(ValueError, match="not a version"):
        ruleset_major(version)


def test_only_packs_of_the_same_ruleset_major_version_compare() -> None:
    old = parse_snapshot(DATA)
    assert comparable(old, replace(old))
    assert not comparable(old, replace(old, ruleset_version="0.2"))
    assert not comparable(old, replace(old, ruleset_id="OTHER-RULES"))
    first = replace(old, ruleset_version="1.0")
    assert comparable(first, replace(first, ruleset_version="1.7"))
    assert not comparable(first, replace(first, ruleset_version="2.0"))


def test_a_trend_keeps_the_score_and_the_coverage_apart() -> None:
    before = parse_snapshot(DATA)
    spec = client_spec(LIBRARY, load_clients(), "A")
    after = replace(before, controls=inputs_for(LIBRARY, spec))
    change = trend(before, after)
    assert change is not None
    gain = score_snapshot(after).score - score_snapshot(before).score
    assert change.score_change == gain
    assert change.coverage_change == Fraction(97, 98) - Fraction(70, 99)
    assert change.score_change > 0 and change.coverage_change > 0
    assert trend(before, replace(after, ruleset_version="0.2")) is None
    assert trend(before, replace(after, ruleset_id="OTHER-RULES")) is None
