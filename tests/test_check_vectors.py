"""The check-engine vectors (phase 5, part 2).

tests/vectors holds one file per control that is evaluated from evidence (the 43
that are not manual-only). Each vector is a piece of evidence and the exact result
the control must give. The files are written by tools/make_vectors.py from
data/controls.yaml: the expected share or count is worked out from the thresholds
of the file, not by the engine. These tests run the engine on every vector, check
that each control has at least six of them with pass, partial, fail, unknown and
an empty population, that every threshold is hit exactly and one step either side,
and that the stored files are exactly what the generator writes now.
"""

import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from app.checks.engine import evaluate_control, has_rule
from app.checks.library import Control, Library, load_library
from tools import make_vectors
from tools.vector_facts import build_evidence

VECTOR_DIR = Path(__file__).parent / "vectors"
LIBRARY = load_library()
MINIMUM = 6
# Controls whose rule has no partial result.
NO_PARTIAL = {"PC-ACC-02", "PC-NET-03", "PC-NET-04", "PC-LOG-01"}


def load_files() -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(VECTOR_DIR.glob("*.json")):
        content = json.loads(path.read_text(encoding="utf-8"))
        assert content["control"] == path.stem
        files[path.stem] = content
    return files


FILES = load_files()


def all_vectors() -> list[Any]:
    return [
        pytest.param(control_id, vector, id=f"{control_id}-{vector['name']}")
        for control_id, content in FILES.items()
        for vector in content["vectors"]
    ]


def evaluated(library: Library) -> list[Control]:
    return [control for control in library.controls if not control.manual_only]


@pytest.mark.parametrize(("control_id", "vector"), all_vectors())
def test_the_engine_gives_exactly_the_expected_result(
    control_id: str, vector: dict[str, Any]
) -> None:
    control = LIBRARY.control(control_id)
    result = evaluate_control(LIBRARY, control, build_evidence(vector["evidence"]))
    expect = vector["expect"]
    assert result.status == expect["status"], result.detail
    assert result.reason == expect["reason"], result.detail
    assert result.control_id == control_id
    if "numerator" in expect:
        assert result.numerator == expect["numerator"], result.detail
    if "denominator" in expect:
        assert result.denominator == expect["denominator"], result.detail


def test_there_is_a_file_for_each_of_the_43_controls_that_are_not_manual_only() -> None:
    assert sorted(FILES) == sorted(control.id for control in evaluated(LIBRARY))
    assert len(FILES) == 43


def test_the_stored_files_are_exactly_what_the_generator_writes_now() -> None:
    generated = make_vectors.generate()
    assert sorted(generated) == sorted(FILES)
    for control_id, content in generated.items():
        stored = (VECTOR_DIR / f"{control_id}.json").read_text(encoding="utf-8")
        assert stored == make_vectors.render(content), control_id


@pytest.mark.parametrize("control", evaluated(LIBRARY), ids=lambda item: item.id)
def test_every_control_has_six_vectors_of_every_kind(control: Control) -> None:
    vectors = FILES[control.id]["vectors"]
    names = [vector["name"] for vector in vectors]
    assert len(vectors) >= MINIMUM
    assert len(set(names)) == len(names), "a vector name is used twice"
    statuses = {vector["expect"]["status"] for vector in vectors}
    if control.automatic_unavailable is not None:
        assert statuses == {"unknown"}
    else:
        assert has_rule(control)
        wanted = {"pass", "fail", "unknown"}
        if control.id not in NO_PARTIAL:
            wanted.add("partial")
        assert wanted <= statuses
    assert any(name.startswith("empty") for name in names)
    unknown = [v["expect"] for v in vectors if v["expect"]["status"] == "unknown"]
    assert any(expect["reason"] == "licence_or_scope" for expect in unknown)


@pytest.mark.parametrize("control", evaluated(LIBRARY), ids=lambda item: item.id)
def test_an_absent_field_is_never_pass_and_never_fail(control: Control) -> None:
    """With no evidence at all the control is unknown with licence_or_scope."""
    if not control.fields:
        pytest.skip("the control reads no field")
    result = evaluate_control(LIBRARY, control, build_evidence({}))
    assert result.status == "unknown"
    assert result.reason == "licence_or_scope"


def pairs(control_id: str) -> list[tuple[Fraction, str]]:
    found: list[tuple[Fraction, str]] = []
    for vector in FILES[control_id]["vectors"]:
        expect = vector["expect"]
        if expect.get("denominator") and expect.get("numerator") is not None:
            share = Fraction(expect["numerator"], expect["denominator"])
            found.append((share, expect["status"]))
    return found


SHARE_CONTROLS = [
    control
    for control in evaluated(LIBRARY)
    if control.rule.kind == "share" and has_rule(control)
]
COUNT_CONTROLS = [
    control
    for control in evaluated(LIBRARY)
    if control.rule.kind == "count" and has_rule(control)
]


@pytest.mark.parametrize("control", SHARE_CONTROLS, ids=lambda item: item.id)
def test_every_share_threshold_is_hit_exactly_and_one_step_either_side(
    control: Control,
) -> None:
    assert control.rule.pass_ is not None and control.rule.partial is not None
    assert control.rule.pass_.at_least is not None
    assert control.rule.partial.at_least is not None
    top = Fraction(control.rule.pass_.at_least)
    low = Fraction(control.rule.partial.at_least)
    found = pairs(control.id)
    assert (top, "pass") in found
    assert (low, "partial") in found
    assert any(share < top and status == "partial" for share, status in found)
    assert any(share < low and status == "fail" for share, status in found)
    for share, status in found:
        expected = "pass" if share >= top else ("partial" if share >= low else "fail")
        assert status == expected


@pytest.mark.parametrize("control", COUNT_CONTROLS, ids=lambda item: item.id)
def test_every_count_threshold_is_hit_exactly_and_one_step_either_side(
    control: Control,
) -> None:
    assert control.rule.pass_ is not None and control.rule.pass_.at_most is not None
    top = control.rule.pass_.at_most
    found = {
        (vector["expect"]["numerator"], vector["expect"]["status"])
        for vector in FILES[control.id]["vectors"]
        if vector["expect"].get("numerator") is not None
    }
    assert (top, "pass") in found
    beyond = "fail" if control.rule.partial is None else "partial"
    assert (top + 1, beyond) in found
    if control.rule.partial is not None:
        assert control.rule.partial.at_most is not None
        limit = control.rule.partial.at_most
        assert (limit, "partial") in found
        assert (limit + 1, "fail") in found


def test_no_vector_is_a_secret_or_a_real_person() -> None:
    text = "".join(path.read_text(encoding="utf-8") for path in VECTOR_DIR.glob("*"))
    assert "@" not in text
    assert "password" not in text.lower()
