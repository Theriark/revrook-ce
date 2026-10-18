"""Snapshots: a stored score that can be made again byte for byte (phase 6).

A snapshot keeps everything the score was made from: the ruleset id and version, the
version of the importers, the pack date, the thresholds of the model, the domain
weights, the evidence items (id and SHA-256) and, for every control, its status,
quality, evidence time, maximum age, weight, domain and gate. It also keeps the
results that follow. Regenerating reads only the inputs and scores them again with
the engine, so a later change to a rule of the check engine cannot alter an old
pack, and the text written is the same bytes as the text stored.

The text is canonical JSON: keys sorted, no spaces, ASCII only, one line and a final
newline. There is no float in it: a fraction is written as `numerator/denominator`
and a time as an ISO text in UTC. The last key, `sha256`, is the digest of all the
others, so a pack that was edited is refused instead of read.

Trends compare only snapshots of the same ruleset and the same ruleset major version
(see `ruleset_major`); score and coverage are compared separately.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from typing import Any, cast

from app.checks.library import Library
from app.checks.model import ControlResult, Status
from app.scoring.display import format_fixed, percent
from app.scoring.engine import (
    control_inputs,
    domain_weights,
    require_aware,
    score_inputs,
)
from app.scoring.model import (
    DEFAULT_THRESHOLDS,
    ControlInput,
    DomainWeight,
    ScoreResult,
    Thresholds,
)

SCHEMA_VERSION = 1
STATUSES = frozenset({"pass", "partial", "fail", "unknown", "na"})
Json = dict[str, Any]


class SnapshotError(ValueError):
    """A snapshot is not readable, was edited, or is not what regeneration gives."""


@dataclass(frozen=True)
class EvidenceRef:
    """One evidence item a snapshot rests on: its id and the SHA-256 of its file."""

    evidence_id: str
    sha256: str


@dataclass(frozen=True)
class SnapshotInput:
    """Everything a score is made from."""

    ruleset_id: str
    ruleset_version: str
    importer_version: str
    as_of: datetime
    thresholds: Thresholds
    domains: tuple[DomainWeight, ...]
    controls: tuple[ControlInput, ...]
    evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True)
class Trend:
    """The change between two packs: the score and the coverage, kept apart."""

    score_change: Fraction
    coverage_change: Fraction


def snapshot_input(
    library: Library,
    results: Mapping[str, ControlResult],
    as_of: datetime,
    evidence: Sequence[EvidenceRef],
    importer_version: str,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> SnapshotInput:
    """The inputs of a snapshot from the results of the check engine."""
    return SnapshotInput(
        ruleset_id=library.ruleset_id,
        ruleset_version=library.version,
        importer_version=importer_version,
        as_of=require_aware(as_of, "as_of"),
        thresholds=thresholds,
        domains=domain_weights(library),
        controls=control_inputs(library, results),
        evidence=tuple(sorted(evidence, key=lambda ref: ref.evidence_id)),
    )


def score_snapshot(snapshot: SnapshotInput) -> ScoreResult:
    """The score of the inputs of a snapshot."""
    return score_inputs(
        snapshot.controls, snapshot.domains, snapshot.as_of, snapshot.thresholds
    )


# --- writing ----------------------------------------------------------------------


def _fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def _time_text(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def _canonical(document: Json) -> bytes:
    text = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return text.encode("ascii")


def _thresholds_document(thresholds: Thresholds) -> Json:
    return {
        "cap_fail": thresholds.cap_fail,
        "cap_partial": thresholds.cap_partial,
        "min_coverage": _fraction_text(thresholds.min_coverage),
        "na_flag_above": _fraction_text(thresholds.na_flag_above),
        "bands": [[name, lowest] for name, lowest in thresholds.bands],
        "lowest_band": thresholds.lowest_band,
        "insufficient_band": thresholds.insufficient_band,
    }


def _control_document(item: ControlInput) -> Json:
    return {
        "id": item.control_id,
        "domain": item.domain,
        "weight": item.weight,
        "gate": item.gate,
        "status": item.status,
        "quality": _fraction_text(item.quality),
        "evidence_at": _time_text(item.evidence_at),
        "max_age_days": item.max_age_days,
    }


def _inputs_document(snapshot: SnapshotInput) -> Json:
    return {
        "schema": SCHEMA_VERSION,
        "ruleset": {"id": snapshot.ruleset_id, "version": snapshot.ruleset_version},
        "importer_version": snapshot.importer_version,
        "as_of": _time_text(snapshot.as_of),
        "thresholds": _thresholds_document(snapshot.thresholds),
        "domains": [
            {"code": item.code, "weight": item.weight} for item in snapshot.domains
        ],
        "evidence": [
            {"id": ref.evidence_id, "sha256": ref.sha256} for ref in snapshot.evidence
        ],
        "controls": [_control_document(item) for item in snapshot.controls],
    }


def _results_document(result: ScoreResult) -> Json:
    cap = result.cap
    cap_document: Json | None = None
    if cap is not None:
        cap_document = {
            "control": cap.control_id,
            "limit": cap.limit,
            "reason": cap.reason,
        }
    best = result.best_case
    return {
        "controls": [
            {
                "id": item.control_id,
                "freshness": _fraction_text(item.freshness),
                "score": _fraction_text(item.score),
                "contribution": _fraction_text(item.contribution),
                "counted": item.counted,
                "covered": item.covered,
                "stale": item.stale,
            }
            for item in result.controls
        ],
        "domains": [
            {
                "code": item.code,
                "weight": item.weight,
                "earned": _fraction_text(item.earned),
                "possible": item.possible,
                "score": None if item.score is None else _fraction_text(item.score),
            }
            for item in result.domains
        ],
        "raw": _fraction_text(result.raw),
        "cap": cap_document,
        "capped": result.capped,
        "score": _fraction_text(result.score),
        "coverage": _fraction_text(result.coverage),
        "upper": _fraction_text(result.upper),
        "band": result.band,
        "insufficient": result.insufficient,
        "na_weight": result.na_weight,
        "na_flagged": result.na_flagged,
        "dropped_domains": list(result.dropped_domains),
        "display": {
            "raw": format_fixed(result.raw),
            "score": format_fixed(result.score),
            "best_case": None if best is None else format_fixed(best),
            "coverage_percent": percent(result.coverage),
        },
    }


def snapshot_document(snapshot: SnapshotInput) -> Json:
    """The snapshot as plain data: inputs, results and the digest of both."""
    body = _inputs_document(snapshot)
    body["results"] = _results_document(score_snapshot(snapshot))
    body["sha256"] = hashlib.sha256(_canonical(body)).hexdigest()
    return body


def render_snapshot(snapshot: SnapshotInput) -> bytes:
    """The canonical bytes of a snapshot."""
    return _canonical(snapshot_document(snapshot)) + b"\n"


# --- reading ----------------------------------------------------------------------


def _object(value: object) -> Json:
    if not isinstance(value, dict):
        raise TypeError("an object was expected")
    return cast(Json, value)


def _array(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError("a list was expected")
    return cast(list[Any], value)


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("a text was expected")
    return value


def _whole(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("a whole number was expected")
    return value


def _flag(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError("true or false was expected")
    return value


def _fraction(value: object) -> Fraction:
    text = _text(value)
    parsed = Fraction(text)
    if _fraction_text(parsed) != text:
        raise ValueError(f"{text} is not a fraction in lowest terms")
    return parsed


def _time(value: object) -> datetime:
    return require_aware(datetime.fromisoformat(_text(value)), "a stored time")


def _status(value: object) -> Status:
    text = _text(value)
    if text not in STATUSES:
        raise ValueError(f"{text} is not a status")
    return cast(Status, text)


def _thresholds(raw: object) -> Thresholds:
    item = _object(raw)
    return Thresholds(
        cap_fail=_whole(item["cap_fail"]),
        cap_partial=_whole(item["cap_partial"]),
        min_coverage=_fraction(item["min_coverage"]),
        na_flag_above=_fraction(item["na_flag_above"]),
        bands=tuple((_text(band[0]), _whole(band[1])) for band in item["bands"]),
        lowest_band=_text(item["lowest_band"]),
        insufficient_band=_text(item["insufficient_band"]),
    )


def _control(raw: object) -> ControlInput:
    item = _object(raw)
    at = item["evidence_at"]
    age = item["max_age_days"]
    return ControlInput(
        control_id=_text(item["id"]),
        domain=_text(item["domain"]),
        weight=_whole(item["weight"]),
        gate=_flag(item["gate"]),
        status=_status(item["status"]),
        quality=_fraction(item["quality"]),
        evidence_at=None if at is None else _time(at),
        max_age_days=None if age is None else _whole(age),
    )


def _inputs(document: Json) -> SnapshotInput:
    if document["schema"] != SCHEMA_VERSION:
        raise ValueError(f"schema {document['schema']} is not {SCHEMA_VERSION}")
    ruleset = _object(document["ruleset"])
    return SnapshotInput(
        ruleset_id=_text(ruleset["id"]),
        ruleset_version=_text(ruleset["version"]),
        importer_version=_text(document["importer_version"]),
        as_of=_time(document["as_of"]),
        thresholds=_thresholds(document["thresholds"]),
        domains=tuple(
            DomainWeight(_text(item["code"]), _whole(item["weight"]))
            for item in map(_object, _array(document["domains"]))
        ),
        controls=tuple(_control(item) for item in _array(document["controls"])),
        evidence=tuple(
            EvidenceRef(_text(item["id"]), _text(item["sha256"]))
            for item in map(_object, _array(document["evidence"]))
        ),
    )


def parse_snapshot(data: bytes) -> SnapshotInput:
    """The inputs of a stored snapshot.

    Raises SnapshotError when the text is not JSON, is not a snapshot of this
    schema, or its digest does not match: an edited pack is never read.
    """
    try:
        document = _object(json.loads(data.decode("utf-8")))
        stored = _text(document["sha256"])
        body = {key: value for key, value in document.items() if key != "sha256"}
        if hashlib.sha256(_canonical(body)).hexdigest() != stored:
            raise ValueError("the digest does not match the content")
        return _inputs(document)
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as error:
        raise SnapshotError(f"the snapshot cannot be read: {error}") from error


def regenerate(data: bytes) -> bytes:
    """The bytes of a stored snapshot, made again from its inputs alone."""
    return render_snapshot(parse_snapshot(data))


def verify_snapshot(data: bytes) -> None:
    """Raise SnapshotError unless regenerating gives exactly the stored bytes."""
    if regenerate(data) != data:
        raise SnapshotError("regenerating the snapshot does not give its bytes")


# --- trends -----------------------------------------------------------------------


def ruleset_major(version: str) -> str:
    """The part of a ruleset version that decides whether two packs compare.

    The first number is the major version. Version 0 has no stability promise, so
    for 0.x the minor number counts as well: 0.1 and 0.2 are different majors.
    """
    parts = version.split(".")
    if not all(part.isascii() and part.isdigit() for part in parts):
        raise ValueError(f"{version} is not a version of numbers separated by dots")
    if parts[0] == "0" and len(parts) > 1:
        return f"0.{parts[1]}"
    return parts[0]


def comparable(previous: SnapshotInput, current: SnapshotInput) -> bool:
    """Whether two packs were made by the same ruleset and the same major version."""
    if previous.ruleset_id != current.ruleset_id:
        return False
    before = ruleset_major(previous.ruleset_version)
    return before == ruleset_major(current.ruleset_version)


def trend(previous: SnapshotInput, current: SnapshotInput) -> Trend | None:
    """The change from one pack to the next; None across ruleset major versions."""
    if not comparable(previous, current):
        return None
    before = score_snapshot(previous)
    after = score_snapshot(current)
    return Trend(after.score - before.score, after.coverage - before.coverage)
