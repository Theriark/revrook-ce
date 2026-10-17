"""The contract between a source adapter and the evidence store.

An importer turns the bytes of one export into facts: counts and flags. A
personal identifier (user principal name, device id, mailbox id) is never put in
a fact value. The importer names it in `identifiers` instead, and the evidence
store replaces it with the client's pseudonym before anything is stored.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

SOURCE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")

FactValue = str | int | bool | None


class ImportRejectedError(Exception):
    """The file cannot be imported.

    The message is shown to the person who uploaded the file. It names a column,
    a row number or a limit, and never repeats content from the file.
    """


@dataclass(frozen=True)
class ParsedFact:
    """One normalised fact. `identifiers` maps a field name to a raw identifier."""

    key: str
    value: Mapping[str, FactValue]
    identifiers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ParseResult:
    """The facts of one file and, when the file says so, when it was captured."""

    facts: tuple[ParsedFact, ...]
    captured_at: datetime | None = None


class SourceImporter(Protocol):
    """A source adapter. `parse` is pure: bytes in, facts out, no I/O."""

    source_code: str
    version: str

    def parse(self, data: bytes, max_rows: int) -> ParseResult:
        """Parse one file; raise ImportRejectedError when it cannot be used."""
