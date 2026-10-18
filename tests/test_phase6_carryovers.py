"""Carry-overs from the review of phase 5, part 2 (THE-306 and THE-307).

* N-1: PC-ACC-01 counts a member whose `mfa_registered` or `mfa_capable` is False
  as a certain failure, even when the other flag is blank.
* N-2: the PC-BCK-01 vector that asserts a job of a non-server is not counted is
  named for what it asserts.

N-5 (the wall-clock assertion of tests/test_phase5_fixes.py) is relaxed in that file.
Not fixed here, recorded: the reason of a not-applicable decision (`NaReview`) is not
escaped; the reports of phase 8 escape every text they print.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from app.checks.engine import evaluate_control
from app.checks.library import load_library
from tools import make_vectors
from tools.vector_facts import build_evidence

LIBRARY = load_library()
CONTROL = LIBRARY.control("PC-ACC-01")
VECTOR_DIR = Path(__file__).parent / "vectors"


def members(*groups: tuple[int, dict[str, Any]]) -> dict[str, Any]:
    """Evidence of the registration export: (count, row) groups of members."""
    users = [
        {
            "repeat": count,
            "id_column": "user",
            "prefix": f"g{number}",
            "row": {"user_type": "member", **row},
        }
        for number, (count, row) in enumerate(groups)
    ]
    return {"sources": {"entra-registration": {"kinds": {"user": users}}}}


GOOD = {"mfa_registered": True, "mfa_capable": True}
CASES = [
    ("registered-false-capable-blank", {"mfa_registered": False, "mfa_capable": None}),
    ("capable-false-registered-blank", {"mfa_registered": None, "mfa_capable": False}),
    ("both-false", {"mfa_registered": False, "mfa_capable": False}),
]


@pytest.mark.parametrize(("name", "row"), CASES, ids=[name for name, _ in CASES])
def test_a_false_flag_with_the_other_blank_is_a_certain_failure(
    name: str, row: dict[str, Any]
) -> None:
    result = evaluate_control(LIBRARY, CONTROL, build_evidence(members((100, row))))
    assert result.status == "fail", result.detail
    assert (result.numerator, result.denominator) == (0, 100)


@pytest.mark.parametrize(("name", "row"), CASES, ids=[name for name, _ in CASES])
def test_such_members_are_failures_and_not_unresolved_rows(
    name: str, row: dict[str, Any]
) -> None:
    """97 good members and 3 of them: 97 of 100 is a partial, not an unknown."""
    evidence = build_evidence(members((97, GOOD), (3, row)))
    result = evaluate_control(LIBRARY, CONTROL, evidence)
    assert result.status == "partial", result.detail
    assert (result.numerator, result.denominator) == (97, 100)


def test_a_true_flag_with_the_other_blank_is_still_unresolved() -> None:
    blank = {"mfa_registered": True, "mfa_capable": None}
    result = evaluate_control(LIBRARY, CONTROL, build_evidence(members((100, blank))))
    assert (result.status, result.reason) == ("unknown", "licence_or_scope")
    mixed = build_evidence(members((98, GOOD), (2, blank)))
    result = evaluate_control(LIBRARY, CONTROL, mixed)
    assert result.status == "pass", "98 of 100 pass whatever the two blanks are"


def test_the_stored_acc_01_vectors_still_equal_the_generator() -> None:
    content = make_vectors.generate()["PC-ACC-01"]
    stored = (VECTOR_DIR / "PC-ACC-01.json").read_text(encoding="utf-8")
    assert stored == make_vectors.render(content)


# --- N-2 ----------------------------------------------------------------------------


def bck_01_vectors() -> list[dict[str, Any]]:
    text = (VECTOR_DIR / "PC-BCK-01.json").read_text(encoding="utf-8")
    vectors: list[dict[str, Any]] = json.loads(text)["vectors"]
    return vectors


def test_the_stale_vector_name_is_gone_from_the_bck_01_vectors() -> None:
    names = [vector["name"] for vector in bck_01_vectors()]
    assert "unknown-rows-left-out" not in names
    assert "job-of-a-non-server-not-counted" in names


def test_that_vector_asserts_a_job_of_a_non_server_is_not_counted() -> None:
    [vector] = [v for v in bck_01_vectors() if v["name"].startswith("job-of-a-non")]
    jobs = vector["evidence"]["sources"]["backup-export"]["kinds"]["job"]
    assert [item["prefix"] for item in jobs] == ["s", "other"]
    without = json.loads(json.dumps(vector["evidence"]))
    without["sources"]["backup-export"]["kinds"]["job"] = jobs[:1]
    control = LIBRARY.control("PC-BCK-01")
    both = evaluate_control(LIBRARY, control, build_evidence(vector["evidence"]))
    alone = evaluate_control(LIBRARY, control, build_evidence(without))
    expect = vector["expect"]
    assert (both.status, both.numerator, both.denominator) == (
        expect["status"],
        expect["numerator"],
        expect["denominator"],
    )
    assert (alone.status, alone.numerator, alone.denominator) == (
        both.status,
        both.numerator,
        both.denominator,
    )
