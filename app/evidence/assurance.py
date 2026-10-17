"""Assurance labels: how much an item of evidence proves."""

from enum import StrEnum
from fractions import Fraction


class Assurance(StrEnum):
    """The three assurance levels, stored in evidence_item.assurance_level."""

    AUTOMATIC_EXPORT = "automatic-export"
    MANUAL_ARTEFACT = "manual-artefact"
    ATTESTATION = "attestation"

    @property
    def quality(self) -> Fraction:
        """The evidence quality factor q of the scoring model."""
        return QUALITY[self]

    @property
    def label(self) -> str:
        """The plain-language label shown next to the evidence."""
        return LABELS[self]


QUALITY: dict[Assurance, Fraction] = {
    Assurance.AUTOMATIC_EXPORT: Fraction(1),
    Assurance.MANUAL_ARTEFACT: Fraction(9, 10),
    Assurance.ATTESTATION: Fraction(3, 5),
}

LABELS: dict[Assurance, str] = {
    Assurance.AUTOMATIC_EXPORT: "Automatic export with capture time and hash",
    Assurance.MANUAL_ARTEFACT: "Manual artefact with hash, reviewer and date",
    Assurance.ATTESTATION: "Attestation without an artefact",
}
