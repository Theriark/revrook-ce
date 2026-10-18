"""Helpers for writing vectors (see tools/make_vectors.py).

The expected result of a share or a count is worked out here from the thresholds
of the control file, with exact fractions, and never from the engine.
"""

from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import Any

Vector = dict[str, Any]
RECENT = {"ago": {"days": 1}}
LOS = "licence_or_scope"
EMPTY = "empty_population"
UNRESOLVED = "unresolved_values"
LOOKUP = "lookup_failed"


def ago(**delta: int) -> dict[str, Any]:
    """A time that long before the capture time of the vectors."""
    return {"ago": delta}


def rep(
    count: int,
    row: Mapping[str, Any],
    id_column: str | None = None,
    prefix: str = "r",
    start: int = 0,
) -> dict[str, Any]:
    """`count` copies of a row, with their own identifiers in `id_column`."""
    spec: dict[str, Any] = {"repeat": count, "row": dict(row)}
    if id_column is not None:
        spec.update({"id_column": id_column, "prefix": prefix, "start": start})
    return spec


def src(
    kinds: Mapping[str, Sequence[Any]],
    summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One source: its rows by kind, and its summary fact when it has one."""
    found: dict[str, Any] = {"kinds": {k: list(rows) for k, rows in kinds.items()}}
    if summary is not None:
        found["summary"] = dict(summary)
    return found


def ev(
    sources: Mapping[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """The evidence of a vector: its sources by adapter, and anything else."""
    return {"sources": dict(sources or {}), **extra}


def one(adapter: str, kind: str, *rows: Any) -> dict[str, Any]:
    """Evidence with one source that has rows of one kind."""
    return ev({adapter: src({kind: list(rows)})})


def vec(
    name: str,
    evidence: Mapping[str, Any],
    status: str,
    reason: str | None = None,
    numerator: int | None = None,
    denominator: int | None = None,
) -> Vector:
    """A vector: the evidence and the result the control must give."""
    expect: dict[str, Any] = {"status": status, "reason": reason}
    if numerator is not None:
        expect["numerator"] = numerator
    if denominator is not None:
        expect["denominator"] = denominator
    return {"name": name, "evidence": dict(evidence), "expect": expect}


def at_least(rule: Mapping[str, Any], key: str) -> Fraction:
    return Fraction(rule[key]["at_least"])


def at_most(rule: Mapping[str, Any], key: str) -> int:
    return int(rule[key]["at_most"])


def share_status(rule: Mapping[str, Any], good: int, total: int) -> str:
    """pass, partial or fail for a share, from the thresholds of the rule."""
    share = Fraction(good, total)
    if share >= at_least(rule, "pass"):
        return "pass"
    if share >= at_least(rule, "partial"):
        return "partial"
    return "fail"


def count_status(rule: Mapping[str, Any], found: int) -> str:
    """pass, partial or fail for a count that should be small."""
    if found <= at_most(rule, "pass"):
        return "pass"
    if "partial" in rule and found <= at_most(rule, "partial"):
        return "partial"
    return "fail"


def of_hundred(threshold: Fraction) -> int:
    """A threshold as a number of 100: the vectors use populations of 100."""
    value = threshold * 100
    assert value.denominator == 1, f"{threshold} is not a whole percent"
    return int(value)
