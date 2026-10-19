"""The check engine: one result per control, from evidence, as pure functions.

`evaluate_control` decides, in this order:

1. A not-applicable decision (NA) with a reason and a named reviewer makes the
   control `na`. A GATE control needs a second reviewer, another person; without
   one the decision is refused, the control is evaluated as if it had not been
   made, and a note says so.
2. A manual-only control is judged from its artefact; without one it is unknown
   with the reason no_artefact.
3. An automatic control the CE importers cannot measure (`automatic_unavailable`)
   is unknown with that reason; otherwise its rule reads the facts. A field that is
   absent is never pass and never fail: unknown with the reason licence_or_scope.
4. When the automatic result is unknown and a person recorded a manual artefact or
   an attestation for the control, that judgement is used, at the quality of the
   manual evidence (0.9 for an artefact with its SHA-256, a named reviewer and a
   date; 0.6 for an attestation).
5. The open exceptions of the control are attached. They never change the status.

Nothing here reads a clock, a database or the network. Thresholds, windows and
maximum ages are read from the control file; the only numbers in the rules are
the structure of a rule itself (zero, one, a half).
"""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from fractions import Fraction

from app.checks import backup, devices, email, identity, monitoring, network
from app.checks.library import Control, Library
from app.checks.model import (
    NO_ARTEFACT,
    Assurance,
    ControlResult,
    Evidence,
    ManualAssurance,
    ManualItem,
    NaReview,
    Outcome,
    Status,
)
from app.checks.support import Context, unknown
from app.exceptions import notes_for

Rule = Callable[[Context], Outcome]

RULES: dict[str, Rule] = {
    "PC-ACC-01": identity.acc_01,
    "PC-ACC-02": identity.acc_02,
    "PC-ACC-03": identity.acc_03,
    "PC-ACC-04": identity.acc_04,
    "PC-ACC-05": identity.acc_05,
    "PC-DEV-01": devices.dev_01,
    "PC-DEV-02": devices.dev_02,
    "PC-DEV-03": devices.dev_03,
    "PC-DEV-04": devices.dev_04,
    "PC-DEV-05": devices.dev_05,
    "PC-DEV-07": devices.dev_07,
    "PC-END-01": devices.end_01,
    "PC-END-02": devices.end_02,
    "PC-END-04": devices.end_04,
    "PC-EML-01": email.eml_01,
    "PC-EML-02": email.eml_02,
    "PC-EML-03": email.eml_03,
    "PC-EML-04": email.eml_04,
    "PC-EML-05": email.eml_05,
    "PC-EML-06": email.eml_06,
    "PC-BCK-01": backup.bck_01,
    "PC-BCK-03": backup.bck_03,
    "PC-BCK-04": backup.bck_04,
    "PC-BCK-05": backup.bck_05,
    "PC-NET-01": network.net_01,
    "PC-NET-02": network.net_02,
    "PC-NET-03": network.net_03,
    "PC-NET-04": network.net_04,
    "PC-NET-05": network.net_05,
    "PC-LOG-01": monitoring.log_01,
    "PC-LOG-02": monitoring.log_02,
    "PC-LOG-03": monitoring.log_03,
    "PC-LOG-04": monitoring.log_04,
    "PC-LOG-06": monitoring.log_06,
    "PC-GOV-03": monitoring.gov_03,
    "PC-GOV-04": monitoring.gov_04,
}

# The `params` each rule reads from data/controls.yaml (and no others).
REQUIRED_PARAMS: dict[str, tuple[str, ...]] = {
    "PC-ACC-03": ("max_exclusions",),
    "PC-ACC-05": ("partial_min", "pass_min", "pass_max", "partial_max"),
    "PC-DEV-01": ("active_days",),
    "PC-DEV-02": ("active_days", "patch_days"),
    "PC-DEV-03": ("active_days", "partial_share"),
    "PC-DEV-04": ("active_days",),
    "PC-DEV-05": ("active_days",),
    "PC-DEV-07": ("active_days", "max_local_admins"),
    "PC-END-01": ("active_days",),
    "PC-END-02": ("active_days", "signature_days"),
    "PC-END-04": ("active_days",),
    "PC-EML-01": ("partial_share",),
    "PC-EML-02": ("partial_share",),
    "PC-EML-05": ("partial_mailboxes",),
    "PC-BCK-01": ("active_days", "schedule_factor"),
    "PC-BCK-03": ("restore_days",),
    "PC-BCK-04": ("share",),
    "PC-BCK-05": ("min_retention_days",),
    "PC-NET-01": ("pass_days", "partial_days"),
    "PC-NET-02": ("risk_ports",),
    "PC-NET-04": ("obsolete_modes",),
    "PC-NET-05": ("active_days",),
    "PC-LOG-02": ("pass_days", "partial_days"),
    "PC-LOG-03": ("ack_days",),
    "PC-LOG-04": ("required_alerts",),
    "PC-LOG-06": ("active_days",),
    "PC-GOV-03": ("training_days",),
    "PC-GOV-04": ("grace_days",),
}

# r of the scoring model (rnd-report-3 section 3.5): a partial is a fixed half.
STATUS_VALUE: Mapping[Status, Fraction] = {
    "pass": Fraction(1),
    "partial": Fraction(1, 2),
    "fail": Fraction(0),
    "unknown": Fraction(0),
    "na": Fraction(0),
}
DAY = timedelta(days=1)


def has_rule(control: Control) -> bool:
    """Whether the engine measures this control from facts."""
    return not control.manual_only and control.automatic_unavailable is None


def engine_problems(library: Library) -> list[str]:
    """Where the control file and the rules of the engine do not fit together.

    A control that should be measured has a rule, a control that is manual-only or
    unavailable has none, and the file gives each rule exactly the parameters it
    reads. `revrook verify-controls` exits non-zero on any problem.
    """
    problems: list[str] = []
    known = {control.id for control in library.controls}
    for control_id in sorted(set(RULES) - known):
        problems.append(f"{control_id}: the engine has a rule for no control")
    for control in library.controls:
        if has_rule(control) and control.id not in RULES:
            problems.append(f"{control.id}: the engine has no rule")
        if not has_rule(control) and control.id in RULES:
            problems.append(f"{control.id}: has a rule but is not measured")
        needed = set(REQUIRED_PARAMS.get(control.id, ()))
        for name in sorted(needed - set(control.params)):
            problems.append(f"{control.id}: parameter {name} is missing")
        for name in sorted(set(control.params) - needed):
            problems.append(f"{control.id}: parameter {name} is read by no rule")
    return problems


def na_problem(control: Control, review: NaReview) -> str | None:
    """Why a not-applicable decision is refused; None when it stands."""
    return na_review_problem(control.gate, review)


def na_review_problem(gate: bool, review: NaReview) -> str | None:
    """`na_problem` for a control known only by whether it is a gate (a report)."""
    if not review.reason.strip():
        return "the reason is empty"
    if not review.reviewer.strip():
        return "no reviewer is named"
    if gate:
        second = (review.second_reviewer or "").strip()
        if not second:
            return "a gate control needs a second reviewer"
        if second.casefold() == review.reviewer.strip().casefold():
            return "the second reviewer must be another person"
    return None


def manual_assurance(item: ManualItem) -> ManualAssurance:
    """An artefact counts as one only with its SHA-256 and a named reviewer."""
    if item.assurance == "manual-artefact" and item.sha256 and item.reviewer.strip():
        return "manual-artefact"
    return "attestation"


def manual_quality(library: Library, item: ManualItem) -> Decimal:
    if manual_assurance(item) == "manual-artefact":
        return library.manual_alternative_quality
    return library.attestation_quality


def manual_status(item: ManualItem) -> Status | None:
    """What the reviewer judged. With named parts all must exist for a pass, and
    a plan without the rest is a partial (PC-GOV-05); None when nothing was judged.
    """
    if item.components:
        if all(item.components.values()):
            return "pass"
        return "partial" if item.components.get("plan") else "fail"
    return item.outcome


def reviewed_at(item: ManualItem) -> datetime:
    return datetime.combine(item.reviewed_on, time.min, tzinfo=UTC)


def control_score(result: ControlResult) -> Fraction:
    """r x q of the scoring model: the part of a control's weight it earns, before
    freshness. Unknown, fail and NA earn nothing; a partial earns half.
    """
    return STATUS_VALUE[result.status] * Fraction(result.quality)


def contribution(control: Control, result: ControlResult) -> Fraction:
    """weight x r x q: at most the weight, and at most 0.9 of it for a control
    that only a manual artefact can show.
    """
    return control.weight * control_score(result)


def _automatic(control: Control, evidence: Evidence) -> Outcome:
    if control.manual_only:
        return unknown(NO_ARTEFACT, "No artefact has been recorded for this control.")
    if control.automatic_unavailable is not None:
        return unknown(
            control.automatic_unavailable,
            "The CE importers cannot measure this automatically.",
        )
    return RULES[control.id](Context(control, evidence))


def _result(
    control: Control,
    evidence: Evidence,
    outcome: Outcome,
    assurance: Assurance | None,
    quality: Decimal,
    notes: list[str],
) -> ControlResult:
    at = outcome.evidence_at
    manual = assurance in ("manual-artefact", "attestation")
    limit = control.max_age_days.manual if manual else control.max_age_days.automatic
    age: int | None = None
    stale = False
    if at is not None:
        elapsed = max(evidence.as_of - at, timedelta(0))
        age = elapsed // DAY
        stale = limit is not None and elapsed > limit * DAY
    return ControlResult(
        control_id=control.id,
        status=outcome.status,
        reason=outcome.reason,
        detail=outcome.detail,
        numerator=outcome.numerator,
        denominator=outcome.denominator,
        quality=quality,
        assurance=assurance,
        evidence_at=at,
        age_days=age,
        max_age_days=limit,
        stale=stale,
        exceptions=notes_for(evidence.exceptions, control.id, evidence.as_of),
        notes=tuple(notes),
    )


def evaluate_control(
    library: Library, control: Control, evidence: Evidence
) -> ControlResult:
    """The result of one control against the evidence (see the module text)."""
    notes: list[str] = []
    review = evidence.reviews.get(control.id)
    if review is not None:
        problem = na_problem(control, review)
        if problem is None:
            detail = f"Not applicable: {review.reason.strip()}"
            na = Outcome("na", None, detail)
            return _result(control, evidence, na, None, Decimal(0), notes)
        notes.append(f"A not-applicable decision was refused: {problem}.")
    item = evidence.manual.get(control.id)
    outcome = _automatic(control, evidence)
    if outcome.status != "unknown":
        if outcome.manual and item is not None:
            quality = manual_quality(library, item)
            return _result(
                control, evidence, outcome, manual_assurance(item), quality, notes
            )
        measured: Assurance = "automatic-export"
        return _result(control, evidence, outcome, measured, Decimal(1), notes)
    if item is not None and (control.manual_only or control.manual_alternative):
        judged = manual_status(item)
        if judged is not None:
            assurance = manual_assurance(item)
            detail = f"Judged from a {assurance} dated {item.reviewed_on.isoformat()}."
            manual = Outcome(judged, None, detail, evidence_at=reviewed_at(item))
            quality = manual_quality(library, item)
            return _result(control, evidence, manual, assurance, quality, notes)
        notes.append("A manual artefact exists but no outcome was judged.")
    return _result(control, evidence, outcome, None, Decimal(0), notes)


def evaluate_all(library: Library, evidence: Evidence) -> dict[str, ControlResult]:
    """The result of every control, in the order of the control file."""
    return {
        control.id: evaluate_control(library, control, evidence)
        for control in library.controls
    }
