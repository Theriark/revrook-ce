"""Which source a file comes from, read from its header or its first JSON record.

The import page takes several files at once and names no source: each file is
matched to the importer whose required columns (a CSV) or fields (a JSON file from
Microsoft Graph) it has. A saved column mapping of the client counts as a way of
reading the file too, so a vendor export mapped once in the profile editor is
recognised from then on. When more than one importer fits, the one that finds the
most of its columns wins; a tie is not guessed, and the person is told to use the
profile editor. Nothing is stored here and the file is only looked at.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass

from app.importers.base import ImportRejectedError
from app.importers.framework import decode_text, missing_columns, resolve_columns
from app.importers.generic import CsvAdapter
from app.importers.microsoft import MicrosoftAdapter, Sniffed, sniff

Adapter = MicrosoftAdapter | CsvAdapter


@dataclass(frozen=True)
class Candidate:
    """One way of reading a file: an importer, with a saved profile or without."""

    adapter: Adapter
    profile_id: int | None = None


@dataclass(frozen=True)
class Detected:
    """What a file was matched to; `candidate` is None when nothing fits alone."""

    candidate: Candidate | None
    problem: str | None = None


# The Graph address in `@odata.context` of each Microsoft source.
ODATA_SOURCES = (
    ("conditionalAccess/policies", "conditional-access"),
    ("directoryRoles", "directory-roles"),
    ("userRegistrationDetails", "entra-registration"),
    ("managedDevices", "intune-devices"),
    ("secureScores", "secure-score"),
)
NOT_READABLE = "The file is not readable text, CSV or JSON."
NOT_RECOGNISED = (
    "The columns of this file match no source. If it is a vendor export with other "
    "column names, map it once in the profile editor; it is recognised after that."
)
AMBIGUOUS = (
    "This file fits more than one source ({names}). Import it from the profile "
    "editor, where you choose the source."
)


def _score(adapter: Adapter, sniffed: Sniffed) -> int | None:
    """How many columns or fields of the importer the file has; None if it misses
    a required one (or the importer does not read this kind of file)."""
    if sniffed.header is not None:
        if not adapter.columns:
            return None
        try:
            found = resolve_columns(sniffed.header, adapter.columns, adapter.mapping)
        except ImportRejectedError:
            return None
        if missing_columns(adapter.columns, found):
            return None
        for group in getattr(adapter, "any_of", ()):
            if not any(key in found for key in group):
                return None
        return len(found)
    if isinstance(adapter, MicrosoftAdapter) and adapter.matches(sniffed):
        return len(adapter.json_fields)
    return None


def _odata_source(data: bytes) -> str | None:
    """The source of a Graph answer with no record (an empty list: a tenant without
    Conditional Access policies, say), read from its `@odata.context`."""
    try:
        root = json.loads(decode_text(data))
    except (ImportRejectedError, ValueError):
        return None
    context = root.get("@odata.context") if isinstance(root, dict) else None
    if not isinstance(context, str):
        return None
    for marker, code in ODATA_SOURCES:
        if marker in context:
            return code
    return None


def detect(data: bytes, candidates: Sequence[Candidate]) -> Detected:
    """The one candidate that reads this file best, or why there is none."""
    sniffed = sniff(data)
    if sniffed is None:
        return Detected(None, NOT_READABLE)
    if sniffed.header is None and sniffed.record is None:
        code = _odata_source(data)
        for candidate in candidates:
            if candidate.adapter.source_code == code and candidate.profile_id is None:
                return Detected(candidate)
        return Detected(None, NOT_RECOGNISED)
    scored = [
        (score, candidate)
        for candidate in candidates
        if (score := _score(candidate.adapter, sniffed)) is not None
    ]
    if not scored:
        return Detected(None, NOT_RECOGNISED)
    best = max(score for score, _ in scored)
    top = [candidate for score, candidate in scored if score == best]
    codes = {candidate.adapter.source_code for candidate in top}
    if len(codes) > 1:
        names = ", ".join(sorted(candidate.adapter.label for candidate in top))
        return Detected(None, AMBIGUOUS.format(names=names))
    # One source; a saved profile of the client wins over plain name matching.
    top.sort(key=lambda candidate: candidate.profile_id is None)
    return Detected(top[0])
