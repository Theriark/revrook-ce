"""The check engine around its rules (phase 5, part 2).

The rules themselves are tested by the vectors (tests/test_check_vectors.py). Here:
manual-only controls and manual alternatives and their quality, NA with a second
reviewer for a GATE control, the exceptions register, ages, the agreement between
the control file and the engine, the counts that `revrook verify-controls` enforces,
and the rule that no framework identifier is rendered for a row nobody verified.
"""

import dataclasses
import json
from datetime import date
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from app.checks.engine import (
    RULES,
    contribution,
    control_score,
    engine_problems,
    evaluate_all,
    evaluate_control,
    manual_status,
    na_problem,
)
from app.checks.library import (
    Control,
    Library,
    MappingRow,
    count_problems,
    load_library,
    visible_mappings,
)
from app.checks.model import Evidence, ManualItem, NaReview
from app.checks.reference import load_reference_names
from app.checks.render import (
    FRAMEWORK_LABELS,
    STATUS_LABELS,
    credit_lines,
    reference_lines,
    render_control,
)
from app.exceptions import (
    MAX_REASON_LENGTH,
    ExceptionEntry,
    exception_problems,
    notes_for,
)
from tools.vector_facts import AS_OF, build_evidence

VECTOR_DIR = Path(__file__).parent / "vectors"
LIBRARY = load_library()
REFERENCES = load_reference_names()
SHA = "a" * 64
MANUAL_ONLY = [control for control in LIBRARY.controls if control.manual_only]
GATES = list(LIBRARY.gates)
NINE_TENTHS = Fraction(9, 10)


def vector_evidence(control_id: str, status: str) -> dict[str, Any]:
    """The evidence of the first stored vector of the control with this status."""
    content = json.loads((VECTOR_DIR / f"{control_id}.json").read_text("utf-8"))
    for vector in content["vectors"]:
        if vector["expect"]["status"] == status:
            evidence: dict[str, Any] = vector["evidence"]
            return evidence
    raise AssertionError(f"{control_id} has no {status} vector")


def item(
    assurance: str = "manual-artefact",
    outcome: str | None = "pass",
    *,
    reviewer: str = "A. Reviewer",
    sha256: str | None = SHA,
    components: dict[str, bool] | None = None,
) -> ManualItem:
    return ManualItem(
        assurance=assurance,  # type: ignore[arg-type]
        outcome=outcome,  # type: ignore[arg-type]
        reviewer=reviewer,
        reviewed_on=date(2026, 10, 1),
        sha256=sha256,
        components=components or {},
    )


def with_manual(control_id: str, manual: ManualItem) -> Evidence:
    return Evidence(as_of=AS_OF, manual={control_id: manual})


# --- manual-only controls ----------------------------------------------------------


def test_the_library_has_eight_manual_only_controls() -> None:
    assert len(MANUAL_ONLY) == 8


@pytest.mark.parametrize("control", MANUAL_ONLY, ids=lambda control: control.id)
def test_a_manual_only_control_scores_at_most_nine_tenths_of_its_weight(
    control: Control,
) -> None:
    artefact = evaluate_control(LIBRARY, control, with_manual(control.id, item()))
    assert artefact.status == "pass"
    assert artefact.assurance == "manual-artefact"
    assert artefact.quality == Decimal("0.9")
    assert contribution(control, artefact) == NINE_TENTHS * control.weight
    attestation = item("attestation", sha256=None)
    claimed = evaluate_control(LIBRARY, control, with_manual(control.id, attestation))
    assert claimed.assurance == "attestation"
    assert claimed.quality == Decimal("0.6")
    assert contribution(control, claimed) == Fraction(3, 5) * control.weight
    for result in (artefact, claimed):
        assert contribution(control, result) <= NINE_TENTHS * control.weight


@pytest.mark.parametrize("control", MANUAL_ONLY, ids=lambda control: control.id)
def test_a_manual_only_control_without_an_artefact_is_unknown_and_earns_nothing(
    control: Control,
) -> None:
    result = evaluate_control(LIBRARY, control, Evidence(as_of=AS_OF))
    assert result.status == "unknown"
    assert result.reason == "no_artefact"
    assert result.assurance is None
    assert contribution(control, result) == 0


@pytest.mark.parametrize("control", MANUAL_ONLY, ids=lambda control: control.id)
def test_a_manual_only_partial_earns_half_of_nine_tenths(control: Control) -> None:
    manual = item(outcome="partial")
    result = evaluate_control(LIBRARY, control, with_manual(control.id, manual))
    assert result.status == "partial"
    assert contribution(control, result) == Fraction(9, 20) * control.weight


@pytest.mark.parametrize(
    "manual",
    [
        item(sha256=None),
        item(sha256=""),
        item(reviewer=""),
        item(reviewer="   "),
    ],
    ids=["no-sha", "empty-sha", "no-reviewer", "blank-reviewer"],
)
def test_an_artefact_without_its_hash_or_a_reviewer_is_only_an_attestation(
    manual: ManualItem,
) -> None:
    control = LIBRARY.control("PC-GOV-01")
    result = evaluate_control(LIBRARY, control, with_manual(control.id, manual))
    assert result.assurance == "attestation"
    assert result.quality == Decimal("0.6")


def test_a_manual_item_without_a_judgement_is_unknown_and_says_so() -> None:
    control = LIBRARY.control("PC-GOV-01")
    manual = item(outcome=None)
    result = evaluate_control(LIBRARY, control, with_manual(control.id, manual))
    assert result.status == "unknown"
    assert result.quality == 0
    assert any("no outcome was judged" in note for note in result.notes)


@pytest.mark.parametrize(
    ("components", "expected"),
    [
        ({"plan": True, "exercise": True}, "pass"),
        ({"plan": True, "exercise": False}, "partial"),
        ({"plan": False, "exercise": True}, "fail"),
        ({"plan": False, "exercise": False}, "fail"),
    ],
)
def test_the_incident_plan_needs_both_parts_for_a_pass(
    components: dict[str, bool], expected: str
) -> None:
    manual = item(outcome=None, components=components)
    assert manual_status(manual) == expected
    control = LIBRARY.control("PC-GOV-05")
    result = evaluate_control(LIBRARY, control, with_manual(control.id, manual))
    assert result.status == expected


def test_a_manual_artefact_is_a_dated_judgement_with_an_age() -> None:
    control = LIBRARY.control("PC-GOV-01")
    result = evaluate_control(LIBRARY, control, with_manual(control.id, item()))
    assert result.evidence_at is not None
    assert result.evidence_at.date() == date(2026, 10, 1)
    assert result.age_days == 16
    assert result.max_age_days == control.max_age_days.manual
    assert result.stale is False


# --- manual alternatives of automatic controls -----------------------------------


def test_an_automatic_control_without_facts_accepts_a_manual_artefact_at_0_9() -> None:
    control = LIBRARY.control("PC-ACC-01")
    assert control.manual_alternative
    empty = evaluate_control(LIBRARY, control, Evidence(as_of=AS_OF))
    assert (empty.status, empty.reason) == ("unknown", "licence_or_scope")
    result = evaluate_control(LIBRARY, control, with_manual(control.id, item()))
    assert result.status == "pass"
    assert result.assurance == "manual-artefact"
    assert result.quality == Decimal("0.9")
    assert contribution(control, result) == NINE_TENTHS * control.weight


def test_a_control_ce_cannot_measure_can_still_be_judged_by_a_person() -> None:
    control = LIBRARY.control("PC-END-03")
    assert control.automatic_unavailable == "licence_or_scope"
    bare = evaluate_control(LIBRARY, control, Evidence(as_of=AS_OF))
    assert (bare.status, bare.reason) == ("unknown", "licence_or_scope")
    result = evaluate_control(LIBRARY, control, with_manual(control.id, item()))
    assert result.status == "pass"
    assert result.quality == Decimal("0.9")


def test_a_manual_item_never_overrides_a_measured_result() -> None:
    control = LIBRARY.control("PC-ACC-02")
    evidence = build_evidence(vector_evidence(control.id, "fail"))
    evidence = dataclasses.replace(evidence, manual={control.id: item()})
    result = evaluate_control(LIBRARY, control, evidence)
    assert result.status == "fail"
    assert result.assurance == "automatic-export"
    assert result.quality == 1


def test_an_absent_field_with_a_manual_attestation_is_worth_0_6() -> None:
    control = LIBRARY.control("PC-ACC-01")
    manual = item("attestation", sha256=None)
    result = evaluate_control(LIBRARY, control, with_manual(control.id, manual))
    assert result.status == "pass"
    assert result.quality == Decimal("0.6")
    assert contribution(control, result) == Fraction(3, 5) * control.weight


# --- NA and the second reviewer --------------------------------------------------


def na(
    reason: str = "no wireless network", reviewer: str = "A. Reviewer", **more: Any
) -> NaReview:
    return NaReview(reason=reason, reviewer=reviewer, **more)


def with_na(control_id: str, review: NaReview) -> Evidence:
    return Evidence(as_of=AS_OF, reviews={control_id: review})


def test_the_library_has_three_gates() -> None:
    assert [control.id for control in GATES] == [
        "PC-ACC-01",
        "PC-ACC-02",
        "PC-BCK-01",
    ]


def test_a_not_applicable_decision_with_a_reason_and_a_reviewer_stands() -> None:
    control = LIBRARY.control("PC-NET-04")
    result = evaluate_control(LIBRARY, control, with_na(control.id, na()))
    assert result.status == "na"
    assert result.detail == "Not applicable: no wireless network"
    assert result.quality == 0
    assert contribution(control, result) == 0
    assert result.notes == ()


@pytest.mark.parametrize(
    ("review", "problem"),
    [
        (na(reason=""), "the reason is empty"),
        (na(reason="   "), "the reason is empty"),
        (na(reviewer=""), "no reviewer is named"),
        (na(reviewer=" "), "no reviewer is named"),
    ],
)
def test_a_not_applicable_decision_without_reason_or_reviewer_is_refused(
    review: NaReview, problem: str
) -> None:
    control = LIBRARY.control("PC-NET-04")
    assert na_problem(control, review) == problem
    result = evaluate_control(LIBRARY, control, with_na(control.id, review))
    assert result.status == "unknown"
    assert result.notes == (f"A not-applicable decision was refused: {problem}.",)


@pytest.mark.parametrize("control", GATES, ids=lambda control: control.id)
def test_a_gate_control_needs_a_second_reviewer_for_not_applicable(
    control: Control,
) -> None:
    alone = evaluate_control(LIBRARY, control, with_na(control.id, na()))
    assert alone.status == "unknown"
    assert alone.reason == "licence_or_scope"
    assert "a gate control needs a second reviewer" in alone.notes[0]
    blank = na(second_reviewer="  ")
    assert evaluate_control(LIBRARY, control, with_na(control.id, blank)).status != "na"


@pytest.mark.parametrize("control", GATES, ids=lambda control: control.id)
def test_the_second_reviewer_must_be_another_person(control: Control) -> None:
    for second in ("A. Reviewer", "  a. reviewer ", "A. REVIEWER"):
        review = na(second_reviewer=second)
        assert (
            na_problem(control, review) == "the second reviewer must be another person"
        )
        result = evaluate_control(LIBRARY, control, with_na(control.id, review))
        assert result.status == "unknown"


@pytest.mark.parametrize("control", GATES, ids=lambda control: control.id)
def test_a_gate_control_is_not_applicable_with_two_different_reviewers(
    control: Control,
) -> None:
    review = na(second_reviewer="B. Second")
    assert na_problem(control, review) is None
    result = evaluate_control(LIBRARY, control, with_na(control.id, review))
    assert result.status == "na"
    assert result.notes == ()


def test_a_refused_decision_leaves_the_measured_result_in_place() -> None:
    control = LIBRARY.control("PC-ACC-02")
    evidence = build_evidence(vector_evidence(control.id, "fail"))
    evidence = dataclasses.replace(evidence, reviews={control.id: na()})
    result = evaluate_control(LIBRARY, control, evidence)
    assert result.status == "fail"
    assert "a gate control needs a second reviewer" in result.notes[0]


# --- exceptions ------------------------------------------------------------------


def entry(control_id: str = "PC-ACC-02", **more: Any) -> ExceptionEntry:
    values: dict[str, Any] = {
        "control_id": control_id,
        "owner": "Client owner",
        "reason": "Break-glass account kept without MFA by decision",
        "compensating_control": "Sealed credentials, alert on every sign-in",
        "review_date": date(2026, 12, 1),
    }
    values.update(more)
    return ExceptionEntry(**values)


def test_an_exception_is_shown_beside_a_result_and_never_changes_it() -> None:
    control = LIBRARY.control("PC-ACC-02")
    plain = build_evidence(vector_evidence(control.id, "fail"))
    before = evaluate_control(LIBRARY, control, plain)
    excepted = dataclasses.replace(plain, exceptions=[entry()])
    after = evaluate_control(LIBRARY, control, excepted)
    assert before.status == after.status == "fail"
    assert before.quality == after.quality
    assert contribution(control, before) == contribution(control, after) == 0
    assert before.exceptions == ()
    assert len(after.exceptions) == 1
    note = after.exceptions[0]
    assert note.owner == "Client owner"
    assert note.compensating_control == "Sealed credentials, alert on every sign-in"
    assert note.overdue is False


def test_an_exception_is_overdue_once_its_review_date_has_passed() -> None:
    assert AS_OF.date() == date(2026, 10, 17)
    control = LIBRARY.control("PC-ACC-02")
    base = build_evidence(vector_evidence(control.id, "pass"))
    for review_date, overdue in (
        (date(2026, 10, 16), True),
        (date(2026, 10, 17), False),
        (date(2026, 10, 18), False),
    ):
        evidence = dataclasses.replace(
            base, exceptions=[entry(review_date=review_date)]
        )
        note = evaluate_control(LIBRARY, control, evidence).exceptions[0]
        assert note.overdue is overdue, review_date


def test_an_exception_belongs_to_its_own_control_only() -> None:
    control = LIBRARY.control("PC-ACC-02")
    evidence = dataclasses.replace(
        build_evidence(vector_evidence(control.id, "pass")),
        exceptions=[entry("PC-ACC-01"), entry("PC-NET-02")],
    )
    assert evaluate_control(LIBRARY, control, evidence).exceptions == ()


def test_the_exceptions_of_a_control_are_listed_oldest_review_first() -> None:
    entries = [
        entry(owner="B", review_date=date(2026, 11, 1)),
        entry(owner="A", review_date=date(2026, 11, 1)),
        entry(owner="C", review_date=date(2026, 9, 1)),
        entry("PC-ACC-01", owner="Z"),
    ]
    notes = notes_for(entries, "PC-ACC-02", AS_OF)
    assert [note.owner for note in notes] == ["C", "A", "B"]
    assert [note.overdue for note in notes] == [True, False, False]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, []),
        ({"compensating_control": None}, []),
        ({"owner": " "}, ["an exception needs an owner"]),
        ({"reason": ""}, ["an exception needs a reason"]),
        (
            {"reason": "x" * (MAX_REASON_LENGTH + 1)},
            [f"the reason is longer than {MAX_REASON_LENGTH} characters"],
        ),
        (
            {"compensating_control": "  "},
            ["the compensating control is empty: give it or leave it out"],
        ),
        (
            {"owner": "", "reason": ""},
            ["an exception needs an owner", "an exception needs a reason"],
        ),
    ],
)
def test_an_exception_says_what_it_is_missing(
    changes: dict[str, Any], expected: list[str]
) -> None:
    assert exception_problems(entry(**changes)) == expected


def test_a_reason_of_the_longest_length_is_accepted() -> None:
    assert exception_problems(entry(reason="x" * MAX_REASON_LENGTH)) == []


# --- ages ------------------------------------------------------------------------


@pytest.mark.parametrize("extra", [-1, 0, 1])
def test_a_result_is_stale_only_past_its_maximum_age_and_keeps_its_status(
    extra: int,
) -> None:
    control = LIBRARY.control("PC-ACC-02")
    limit = control.max_age_days.automatic
    assert limit is not None
    spec = vector_evidence(control.id, "pass")
    source = spec["sources"]["entra-registration"]
    # The vectors are captured a day before the pack date: an extra of 0 is age M.
    source["captured_ago"] = {"days": limit - 1 + extra}
    result = evaluate_control(LIBRARY, control, build_evidence(spec))
    assert result.status == "pass"
    assert result.age_days == limit + extra
    assert result.max_age_days == limit
    assert result.stale is (extra > 0)


def test_the_age_is_never_negative_for_evidence_captured_after_the_pack_date() -> None:
    control = LIBRARY.control("PC-ACC-02")
    spec = vector_evidence(control.id, "pass")
    spec["as_of_ago"] = {"days": 30}
    result = evaluate_control(LIBRARY, control, build_evidence(spec))
    assert result.age_days == 0
    assert result.stale is False


# --- the engine against the file -------------------------------------------------


def test_evaluate_all_gives_one_result_per_control_in_file_order() -> None:
    results = evaluate_all(LIBRARY, Evidence(as_of=AS_OF))
    assert list(results) == [control.id for control in LIBRARY.controls]
    assert len(results) == 51
    for control in LIBRARY.controls:
        result = results[control.id]
        assert result.control_id == control.id
        assert result.status == "unknown"
        reason = "no_artefact" if control.manual_only else "licence_or_scope"
        assert result.reason == reason
        assert control_score(result) == 0


def test_the_engine_has_a_rule_for_every_measured_control_and_no_other() -> None:
    measured = {
        control.id
        for control in LIBRARY.controls
        if not control.manual_only and control.automatic_unavailable is None
    }
    assert set(RULES) == measured
    assert len(measured) == 36
    assert engine_problems(LIBRARY) == []


def replace_control(library: Library, control_id: str, **changes: Any) -> Library:
    controls = tuple(
        dataclasses.replace(item_, **changes) if item_.id == control_id else item_
        for item_ in library.controls
    )
    return dataclasses.replace(library, controls=controls)


def test_a_missing_or_extra_parameter_is_a_problem() -> None:
    control = LIBRARY.control("PC-DEV-01")
    missing = replace_control(LIBRARY, control.id, params={})
    assert "PC-DEV-01: parameter active_days is missing" in engine_problems(missing)
    extra = replace_control(LIBRARY, control.id, params={**control.params, "x": 1})
    assert "PC-DEV-01: parameter x is read by no rule" in engine_problems(extra)


def test_a_rule_that_does_not_match_the_measured_state_is_a_problem() -> None:
    unmeasured = replace_control(LIBRARY, "PC-ACC-06", automatic_unavailable=None)
    assert "PC-ACC-06: the engine has no rule" in engine_problems(unmeasured)
    dropped = replace_control(
        LIBRARY, "PC-DEV-01", automatic_unavailable="licence_or_scope"
    )
    assert "PC-DEV-01: has a rule but is not measured" in engine_problems(dropped)
    fewer = dataclasses.replace(
        LIBRARY,
        controls=tuple(c for c in LIBRARY.controls if c.id != "PC-DEV-01"),
    )
    assert "PC-DEV-01: the engine has a rule for no control" in engine_problems(fewer)


# --- the counts of verify-controls -----------------------------------------------


def test_the_library_has_the_counts_of_the_report() -> None:
    assert count_problems(LIBRARY) == []


def test_a_library_that_loses_a_control_a_gate_or_a_weight_is_refused() -> None:
    fewer = dataclasses.replace(LIBRARY, controls=LIBRARY.controls[:-1])
    assert "the library has 50 controls, not 51" in count_problems(fewer)
    ungated = replace_control(LIBRARY, "PC-ACC-01", gate=False)
    assert "the library has 2 gates, not 3" in count_problems(ungated)
    manual = replace_control(LIBRARY, "PC-ACC-08", manual_only=False)
    assert "the library has 7 manual-only controls, not 8" in count_problems(manual)
    domains = (dataclasses.replace(LIBRARY.domains[0], weight=1), *LIBRARY.domains[1:])
    light = dataclasses.replace(LIBRARY, domains=domains)
    assert any("domain weights" in problem for problem in count_problems(light))
    short = dataclasses.replace(LIBRARY, domains=LIBRARY.domains[:-1])
    assert "the library has 7 domains, not 8" in count_problems(short)


# --- no unverified framework identifier in any output ----------------------------


def all_rendered(
    library: Library, references: Any = REFERENCES
) -> list[tuple[Control, str]]:
    results = evaluate_all(library, Evidence(as_of=AS_OF))
    return [
        (control, render_control(control, results[control.id], references))
        for control in library.controls
    ]


def test_every_mapping_row_ships_unverified_so_nothing_external_is_rendered() -> None:
    rows = [row for control in LIBRARY.controls for row in control.mappings]
    assert rows
    assert not any(row.verified for row in rows)
    for control in LIBRARY.controls:
        assert visible_mappings(control) == ()
        assert reference_lines(control, REFERENCES) == []
        assert credit_lines(control, REFERENCES) == []


@pytest.mark.parametrize(
    ("control", "text"),
    all_rendered(LIBRARY),
    ids=lambda value: value.id if isinstance(value, Control) else "text",
)
def test_no_external_framework_identifier_or_name_reaches_a_rendered_control(
    control: Control, text: str
) -> None:
    for row in control.mappings:
        assert f"{FRAMEWORK_LABELS[row.framework]} {row.id}" not in text
        if len(row.id) > 2:  # NIS2 letters are words; their label is checked below
            assert row.id not in text.split(), (control.id, row.id)
        dataset = REFERENCES.get(row.framework)
        name = dataset.names.get(row.id) if dataset is not None else None
        if name is not None:
            assert name not in text
    for label in FRAMEWORK_LABELS.values():
        assert label not in text
    for reference in REFERENCES.values():
        assert reference.credit not in text
    assert text.startswith(f"{control.id} {control.title}")


def test_a_verified_row_is_rendered_with_its_name_and_the_nist_credit() -> None:
    control = LIBRARY.control("PC-ACC-01")
    csf = [row for row in control.mappings if row.framework == "csf"][0]
    verified = tuple(
        dataclasses.replace(row, verified=True) if row is csf else row
        for row in control.mappings
    )
    shown = dataclasses.replace(control, mappings=verified)
    lines = reference_lines(shown, REFERENCES)
    assert len(lines) == 1
    assert lines[0].startswith(f"NIST CSF 2.0 {csf.id} (")
    assert lines[0].endswith(f"({REFERENCES['csf'].names[csf.id]})")
    assert credit_lines(shown, REFERENCES) == [REFERENCES["csf"].credit]
    result = evaluate_all(LIBRARY, Evidence(as_of=AS_OF))[control.id]
    text = render_control(shown, result, REFERENCES)
    assert lines[0] in text
    assert REFERENCES["csf"].credit in text
    # The other rows of the same control stay hidden.
    other = [row for row in control.mappings if row is not csf][0]
    assert f"{FRAMEWORK_LABELS[other.framework]} {other.id}" not in text


def test_a_verified_row_of_a_framework_without_a_dataset_shows_only_its_id() -> None:
    control = LIBRARY.control("PC-ACC-01")
    cis = [row for row in control.mappings if row.framework == "cis"][0]
    shown = dataclasses.replace(
        control, mappings=(dataclasses.replace(cis, verified=True),)
    )
    assert reference_lines(shown, REFERENCES) == [f"CIS Controls {cis.id}"]
    assert credit_lines(shown, REFERENCES) == []


def test_a_row_is_rendered_only_after_it_is_marked_verified() -> None:
    row = MappingRow("csf", "PR.AA-03", verified=False, uncertain=False)
    control = dataclasses.replace(LIBRARY.control("PC-ACC-01"), mappings=(row,))
    assert reference_lines(control, REFERENCES) == []
    checked = dataclasses.replace(row, verified=True)
    flipped = dataclasses.replace(control, mappings=(checked,))
    assert reference_lines(flipped, REFERENCES) != []


def test_the_status_words_are_the_reports_four_labels_and_not_applicable() -> None:
    assert STATUS_LABELS == {
        "pass": "Protected",
        "partial": "Needs attention",
        "fail": "Not protected",
        "unknown": "Not checked",
        "na": "Not applicable",
    }
