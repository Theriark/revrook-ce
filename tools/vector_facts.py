"""Builds the evidence of a check-engine vector from its JSON description.

The vectors in tests/vectors/*.json are written by tools/make_vectors.py. A vector
describes its evidence as data so the file can be read without code:

    {"as_of": {...}, "sources": {adapter: {"kinds": {kind: [row, ...]},
     "summary": {...}, "captured_ago": {"days": 0}}}, "manual": {...},
     "reviews": {...}, "lifecycle": [...], "licence_log_retention_days": 180}

A row is an object of columns. A time is `{"ago": {"days": 3}}`: that long before
the capture time of the vectors (`CAPTURED`). A row can be written as
`{"repeat": 98, "id_column": "device", "prefix": "d", "start": 0, "row": {...}}`
to give 98 rows whose identifier column is d0 to d97 (the same prefix in two
sources names the same devices).
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.checks.model import (
    Evidence,
    LifecycleEntry,
    ManualItem,
    NaReview,
    Row,
    SourceFacts,
)
from app.exceptions import ExceptionEntry

# The capture time of every source of a vector, and the pack date a day later.
CAPTURED = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
AS_OF = datetime(2026, 10, 17, 8, 0, tzinfo=UTC)


def resolve(value: Any) -> Any:
    """Replace every {"ago": {...}} by the ISO time that long before CAPTURED."""
    if isinstance(value, dict):
        if set(value) == {"ago"}:
            return (CAPTURED - timedelta(**value["ago"])).isoformat()
        return {key: resolve(item) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item) for item in value]
    return value


def expand_rows(items: Sequence[Mapping[str, Any]]) -> tuple[Row, ...]:
    """The rows of a kind: plain rows, and repeated rows with their own ids."""
    rows: list[Row] = []
    for item in items:
        if "repeat" not in item:
            rows.append(resolve(item))
            continue
        column = item.get("id_column")
        prefix = item.get("prefix", "r")
        start = item.get("start", 0)
        for index in range(item["repeat"]):
            row = dict(resolve(item["row"]))
            if column is not None:
                row[column] = f"{prefix}{start + index}"
            rows.append(row)
    return tuple(rows)


def build_source(spec: Mapping[str, Any]) -> SourceFacts:
    captured = CAPTURED - timedelta(**spec.get("captured_ago", {}))
    kinds = {kind: expand_rows(items) for kind, items in spec.get("kinds", {}).items()}
    return SourceFacts(captured, kinds, resolve(spec.get("summary", {})))


def build_evidence(spec: Mapping[str, Any]) -> Evidence:
    as_of = AS_OF - timedelta(**spec.get("as_of_ago", {}))
    manual = {
        control_id: ManualItem(
            assurance=item["assurance"],
            outcome=item.get("outcome"),
            reviewer=item.get("reviewer", "A. Reviewer"),
            reviewed_on=date.fromisoformat(item["reviewed_on"]),
            sha256=item.get("sha256"),
            value=item.get("value"),
            components=item.get("components", {}),
        )
        for control_id, item in spec.get("manual", {}).items()
    }
    reviews = {
        control_id: NaReview(
            reason=item["reason"],
            reviewer=item["reviewer"],
            second_reviewer=item.get("second_reviewer"),
        )
        for control_id, item in spec.get("reviews", {}).items()
    }
    lifecycle = [
        LifecycleEntry(
            os=item["os"],
            version_prefix=item["version_prefix"],
            end_of_support=date.fromisoformat(item["end_of_support"]),
        )
        for item in spec.get("lifecycle", [])
    ]
    exceptions = [
        ExceptionEntry(
            control_id=item["control_id"],
            owner=item["owner"],
            reason=item["reason"],
            compensating_control=item.get("compensating_control"),
            review_date=date.fromisoformat(item["review_date"]),
        )
        for item in spec.get("exceptions", [])
    ]
    return Evidence(
        as_of=as_of,
        sources={
            adapter: build_source(source)
            for adapter, source in spec.get("sources", {}).items()
        },
        manual=manual,
        reviews=reviews,
        exceptions=exceptions,
        lifecycle=lifecycle,
        licence_log_retention_days=spec.get("licence_log_retention_days"),
    )
