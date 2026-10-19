"""The status labels of a report and how a control gets one.

A reader who is not technical sees one of four labels, always with an icon and the
words, never a colour alone: Protected, Needs attention, Not protected, Not checked.
A control a reviewer marked not applicable is listed as Not applicable (also icon and
words) and is left out of every count.

The rule that matters: a control is Protected only when its status is pass, its
evidence has a date that is not after the pack date, and the evidence is not out of
date. Anything that cannot show that is Not checked. A status can therefore never be
a claim without dated evidence.
"""

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

from app.scoring.model import ControlInput, ControlScore


@dataclass(frozen=True)
class StatusLabel:
    """A label for a reader: the words and the icon that goes with them."""

    key: str
    text: str
    icon: str


PROTECTED = StatusLabel("protected", "Protected", "check")
NEEDS_ATTENTION = StatusLabel("needs-attention", "Needs attention", "alert")
NOT_PROTECTED = StatusLabel("not-protected", "Not protected", "cross")
NOT_CHECKED = StatusLabel("not-checked", "Not checked", "question")
NOT_APPLICABLE = StatusLabel("not-applicable", "Not applicable", "dash")

LABELS = (PROTECTED, NEEDS_ATTENTION, NOT_PROTECTED, NOT_CHECKED, NOT_APPLICABLE)
COUNTED_LABELS = (PROTECTED, NEEDS_ATTENTION, NOT_PROTECTED, NOT_CHECKED)

# The evidence type, from the quality factor of the scoring model.
ASSURANCE_BY_QUALITY = {
    Fraction(1): "Automatic export",
    Fraction(9, 10): "Manual artefact",
    Fraction(3, 5): "Attestation",
}


def assurance_of(item: ControlInput) -> str:
    """How the evidence was made: an export, a dated artefact or an attestation."""
    return ASSURANCE_BY_QUALITY.get(item.quality, "Other evidence")


def has_dated_evidence(item: ControlInput, as_of: datetime) -> bool:
    """Whether the evidence has a date, and a date that is not after the pack date."""
    return item.evidence_at is not None and item.evidence_at <= as_of


def label_for(item: ControlInput, scored: ControlScore, as_of: datetime) -> StatusLabel:
    """The label of one control at the pack date."""
    if item.status == "na":
        return NOT_APPLICABLE
    if item.status == "unknown" or not has_dated_evidence(item, as_of):
        return NOT_CHECKED
    if scored.stale and scored.freshness == 0:
        # Older than twice the maximum age: the evidence no longer counts at all.
        return NOT_CHECKED
    if item.status == "fail":
        return NOT_PROTECTED
    if item.status == "partial" or scored.stale:
        return NEEDS_ATTENTION
    return PROTECTED
