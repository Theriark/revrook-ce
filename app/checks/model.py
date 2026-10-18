"""The inputs and results of the check engine (phase 5, part 2).

The engine is a set of pure functions: it reads `Evidence` (facts that are already
stored, the manual evidence and reviews a person recorded, and an injected clock
value) and returns one `ControlResult` per control. It does no input or output,
reads no database and no clock of its own, so the same evidence always gives the
same results.

A fact is the stored value of one importer record (`fact.fact_key`, `fact.value`):
the column keys of the adapter, with identifiers already replaced by the client's
pseudonym. `SourceFacts.from_facts` groups the facts of one evidence item by record
kind (the part of the key after the prefix, `inventory.device` is kind `device`);
the `<prefix>.summary` fact is kept apart.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self

from app.exceptions import ExceptionEntry, ExceptionNote

Value = str | int | bool | None
Row = Mapping[str, Value]

Status = Literal["pass", "partial", "fail", "unknown", "na"]
Assurance = Literal["automatic-export", "manual-artefact", "attestation"]
ManualAssurance = Literal["manual-artefact", "attestation"]
ManualOutcome = Literal["pass", "partial", "fail"]

# Why a control is unknown (or why the rest of the result is what it is).
ABSENT = "licence_or_scope"
EMPTY_POPULATION = "empty_population"
UNRESOLVED = "unresolved_values"
NO_ARTEFACT = "no_artefact"
LOOKUP_FAILED = "lookup_failed"
NO_PERMANENT_ASSIGNMENT = "no_permanent_assignment"
REASONS = frozenset(
    {
        ABSENT,
        EMPTY_POPULATION,
        UNRESOLVED,
        NO_ARTEFACT,
        LOOKUP_FAILED,
        NO_PERMANENT_ASSIGNMENT,
    }
)

SUMMARY_KIND = "summary"


@dataclass(frozen=True)
class SourceFacts:
    """The facts of the newest evidence item of one source (one adapter).

    `captured_at` is the capture time of the evidence item: the time in the file,
    or the upload time when the file has none. Every age is measured from it.
    """

    captured_at: datetime
    kinds: Mapping[str, tuple[Row, ...]] = field(default_factory=dict)
    summary: Row = field(default_factory=dict)

    @classmethod
    def from_facts(
        cls, captured_at: datetime, facts: Iterable[tuple[str, Row]]
    ) -> Self:
        """Group (fact_key, value) pairs by record kind; keep the summary apart."""
        grouped: dict[str, list[Row]] = {}
        summary: Row = {}
        for key, value in facts:
            kind = key.partition(".")[2] or key
            if kind == SUMMARY_KIND:
                summary = value
            else:
                grouped.setdefault(kind, []).append(value)
        return cls(
            captured_at=captured_at,
            kinds={kind: tuple(rows) for kind, rows in grouped.items()},
            summary=summary,
        )

    def rows(self, kind: str) -> tuple[Row, ...]:
        return self.kinds.get(kind, ())


@dataclass(frozen=True)
class ManualItem:
    """A dated manual artefact or an attestation a person recorded for a control.

    `outcome` is the reviewer's judgement. For a control whose artefact has named
    parts (PC-GOV-05: a plan and an exercise record) `components` says which parts
    exist and the outcome follows from them. `value` is a number the artefact
    states (PC-LOG-02: the days a declared archive keeps logs).

    A manual artefact is worth the manual quality only with its SHA-256, a named
    reviewer and a date; without them it counts as an attestation.
    """

    assurance: ManualAssurance
    outcome: ManualOutcome | None
    reviewer: str
    reviewed_on: date
    sha256: str | None = None
    value: int | None = None
    components: Mapping[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class NaReview:
    """A reviewer's decision that a control does not apply, with the reason.

    A GATE control needs a second reviewer, a different person.
    """

    reason: str
    reviewer: str
    second_reviewer: str | None = None


@dataclass(frozen=True)
class LifecycleEntry:
    """A vendor end-of-support date: an operating system family and a version prefix.

    `os` is the family word of the importers (windows, macos, ...); a device matches
    when its version starts with `version_prefix` (empty matches every version). The
    longest matching prefix wins. The table itself is shipped data that part 2 does
    not contain; the engine reads it from here.
    """

    os: str
    version_prefix: str
    end_of_support: date


@dataclass(frozen=True)
class Evidence:
    """Everything the engine reads for one client at one date.

    `sources` is keyed by adapter code (`device-inventory`, `entra-registration`,
    ...). A source that was never imported is simply missing. `as_of` is the pack
    date (injected: the engine never reads a clock).
    """

    as_of: datetime
    sources: Mapping[str, SourceFacts] = field(default_factory=dict)
    manual: Mapping[str, ManualItem] = field(default_factory=dict)
    reviews: Mapping[str, NaReview] = field(default_factory=dict)
    exceptions: Sequence[ExceptionEntry] = ()
    lifecycle: Sequence[LifecycleEntry] = ()
    licence_log_retention_days: int | None = None


@dataclass(frozen=True)
class Outcome:
    """What a rule decided, before manual evidence, NA and exceptions are applied.

    `manual` says the rule used a number a person declared (PC-LOG-02), so the
    result has the quality of that manual evidence and not of an export.
    """

    status: Status
    reason: str | None
    detail: str
    numerator: int | None = None
    denominator: int | None = None
    evidence_at: datetime | None = None
    manual: bool = False


@dataclass(frozen=True)
class ControlResult:
    """The result of one control.

    `quality` is the evidence quality factor (1 an automatic export, the manual
    quality for an artefact, the attestation quality; 0 when there is no
    evidence). `age_days` is measured from `evidence_at` to the pack date;
    `stale` says the age is past the control's maximum age (the underlying status
    is kept: scoring decays it).
    """

    control_id: str
    status: Status
    reason: str | None
    detail: str
    numerator: int | None
    denominator: int | None
    quality: Decimal
    assurance: Assurance | None
    evidence_at: datetime | None
    age_days: int | None
    max_age_days: int | None
    stale: bool
    exceptions: tuple[ExceptionNote, ...] = ()
    notes: tuple[str, ...] = ()
