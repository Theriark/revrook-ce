"""Scoring inputs for the phase 6 tests, read from tests/scoring_vectors/clients.json.

The file describes each client as a list of controls, each [status, quality, age in
days]. This module turns that into the `ControlInput` the scoring engine reads, with
the weight, domain, gate and maximum age M of each control taken from the control
file. The expected results in the file are written by hand (phase-plan-3), not by the
engine.
"""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any

from app.checks.library import Library
from app.scoring.model import ControlInput

VECTOR_DIR = Path(__file__).resolve().parent.parent / "tests" / "scoring_vectors"
AS_OF = datetime(2026, 10, 17, 8, 0, tzinfo=UTC)


def load_clients() -> dict[str, Any]:
    text = (VECTOR_DIR / "clients.json").read_text(encoding="utf-8")
    document: dict[str, Any] = json.loads(text)
    return document


def client_spec(
    library: Library, document: Mapping[str, Any], name: str
) -> dict[str, list[Any]]:
    """The [status, quality, age] of every control of a client."""
    client = document["clients"][name]
    spec: dict[str, list[Any]] = {}
    if "base" in client:
        spec = client_spec(library, document, client["base"])
    elif "default" in client:
        spec = {item.id: list(client["default"]) for item in library.controls}
    changes: Mapping[str, Sequence[Any]] = client.get("controls", {})
    spec.update({key: list(value) for key, value in changes.items()})
    return spec


def inputs_for(
    library: Library, spec: Mapping[str, Sequence[Any]], as_of: datetime = AS_OF
) -> tuple[ControlInput, ...]:
    """The scoring inputs of a spec, in the order of the control file."""
    found: list[ControlInput] = []
    for control in library.controls:
        status, quality_text, age_days = spec[control.id]
        quality = Fraction(quality_text)
        ages = control.max_age_days
        limit = ages.automatic
        if quality < 1 and ages.manual is not None:
            limit = ages.manual
        at = None if age_days is None else as_of - timedelta(days=age_days)
        found.append(
            ControlInput(
                control_id=control.id,
                domain=control.domain,
                weight=control.weight,
                gate=control.gate,
                status=status,
                quality=quality,
                evidence_at=at,
                max_age_days=limit,
            )
        )
    return tuple(found)
