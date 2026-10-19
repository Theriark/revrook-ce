"""Mapping verification (phase 11): which external identifiers nobody has checked.

Every mapping row of data/controls.yaml ships `verified: false`, and a report prints
an external identifier only for a row that a person marked verified
(`app.checks.library.visible_mappings`). This module makes that state visible and
keeps a marked row honest:

* it lists the rows that are still unverified, framework by framework;
* for the two NIST frameworks it checks every identifier against the pinned names
  extract (data/nist: the 32 CSF subcategories and the 26 SP 800-171 requirements
  that the control file maps to, with their names, transcribed from the OSCAL
  catalogs at the recorded commit) and reports the commit and catalog version of the
  extract. This is a consistency check between the control file and the extract, not
  a comparison with the full catalog; whether the extract matches the catalog is not
  re-checked here;
* it requires every row marked verified to have a line in the register of
  docs/mapping-verification.md (the source and its version, the date it was read and
  the person who read it), and every line of the register to match a verified row.

It reads files only: no database, no network, no clock. `revrook verify-mappings`
runs it. A row is marked verified by a person who read the source, never by this
module.
"""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import NamedTuple

from app.checks.library import ROOT, Library
from app.checks.reference import DATASETS, ReferenceSet

REGISTER_PATH = ROOT / "docs" / "mapping-verification.md"
REGISTER_START = "<!-- register:start -->"
REGISTER_END = "<!-- register:end -->"
REGISTER_COLUMNS = (
    "Control",
    "Framework",
    "Identifier",
    "Source and version",
    "Date read",
    "Confirmed by",
)
MARKERS_MISSING = "docs/mapping-verification.md lacks its register markers"
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FRAMEWORK_NAMES = {
    "csf": "NIST CSF 2.0",
    "sp800-171": "NIST SP 800-171 Rev 3",
    "cis": "CIS Controls",
    "iso27001": "ISO/IEC 27001",
    "cyber-essentials": "Cyber Essentials",
    "nis2": "NIS2 Directive",
}


class RowKey(NamedTuple):
    """One mapping row of one control."""

    control: str
    framework: str
    identifier: str

    def label(self) -> str:
        return f"{self.control} {self.framework} {self.identifier}"


@dataclass(frozen=True)
class Entry:
    """A mapping row of the library with its state."""

    key: RowKey
    verified: bool
    uncertain: bool


@dataclass(frozen=True)
class RegisterRow:
    """One line of the register of verified rows."""

    key: RowKey
    source: str
    date_read: str
    confirmed_by: str


@dataclass(frozen=True)
class Resolution:
    """How many identifiers of one NIST framework the pinned extract knows."""

    framework: str
    rows: int
    resolved: int
    unresolved: tuple[str, ...]


def entries(library: Library) -> tuple[Entry, ...]:
    """Every mapping row of every control, in file order."""
    found: list[Entry] = []
    for control in library.controls:
        for row in control.mappings:
            key = RowKey(control.id, row.framework, row.id)
            found.append(Entry(key, row.verified, row.uncertain))
    return tuple(found)


def unverified(library: Library) -> tuple[Entry, ...]:
    """The rows no person has marked verified."""
    return tuple(entry for entry in entries(library) if not entry.verified)


def unpinned_frameworks(library: Library) -> list[str]:
    """Frameworks with rows but no pinned names extract in the repository."""
    used = {entry.key.framework for entry in entries(library)}
    return sorted(used - set(DATASETS))


def summary_lines(library: Library) -> list[str]:
    """One line per framework: its rows, how many are verified and how many not."""
    totals: Counter[str] = Counter()
    checked: Counter[str] = Counter()
    for entry in entries(library):
        totals[entry.key.framework] += 1
        if entry.verified:
            checked[entry.key.framework] += 1
    lines: list[str] = []
    for framework in sorted(totals):
        name = FRAMEWORK_NAMES.get(framework, framework)
        total = totals[framework]
        done = checked[framework]
        line = f"{name}: {total} rows, {done} verified, {total - done} unverified"
        lines.append(line)
    return lines


def unverified_lines(library: Library) -> list[str]:
    """One line per unverified row; [U] marks an identifier recalled with doubt."""
    lines: list[str] = []
    for entry in unverified(library):
        key = entry.key
        mark = " [U]" if entry.uncertain else ""
        lines.append(f"{key.control}  {key.framework}  {key.identifier}{mark}")
    return lines


def resolve_nist_rows(
    library: Library, references: Mapping[str, ReferenceSet]
) -> list[Resolution]:
    """For each NIST framework: how many mapped identifiers the pinned extract knows.

    This is a consistency check between the control file and the pinned names
    extract, which holds only the identifiers that the control file maps. It is not
    a comparison with the full NIST catalog, and it does not re-check that the
    extract matches the catalog. Whether a control belongs under an identifier is a
    judgement that only a person who read the source makes.
    """
    found: list[Resolution] = []
    for key in DATASETS:
        reference = references.get(key)
        if reference is None:
            continue
        rows = 0
        missing: list[str] = []
        for entry in entries(library):
            if entry.key.framework != key:
                continue
            rows += 1
            if entry.key.identifier not in reference.names:
                missing.append(entry.key.label())
        found.append(Resolution(key, rows, rows - len(missing), tuple(missing)))
    return found


def _is_rule(cells: list[str]) -> bool:
    """The `---` line under the header of a Markdown table."""
    return all(cell and set(cell) <= set("-:") for cell in cells)


def _valid_date(text: str) -> bool:
    if not DATE_PATTERN.match(text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def parse_register(text: str) -> tuple[list[RegisterRow], list[str]]:
    """The lines of the register in `text`, and what is wrong with them.

    The register is the Markdown table between the two marker comments. A line needs
    its six cells, a source, a real date (YYYY-MM-DD) and the name of the reader.
    """
    start = text.find(REGISTER_START)
    end = text.find(REGISTER_END)
    if start < 0 or end < start:
        return [], [MARKERS_MISSING]
    begin = start + len(REGISTER_START)
    rows: list[RegisterRow] = []
    problems: list[str] = []
    for line in text[begin:end].splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if tuple(cells) == REGISTER_COLUMNS or _is_rule(cells):
            continue
        if len(cells) != len(REGISTER_COLUMNS):
            problems.append("a register line does not have six cells")
            continue
        control, framework, identifier, source, date_read, confirmed_by = cells
        key = RowKey(control, framework, identifier)
        if not source or not confirmed_by or not _valid_date(date_read):
            message = f"{key.label()}: the register needs a source, a date, a name"
            problems.append(message)
        rows.append(RegisterRow(key, source, date_read, confirmed_by))
    return rows, problems


def register_problems(library: Library, rows: Sequence[RegisterRow]) -> list[str]:
    """Where the register and the verified rows of the control file disagree."""
    problems: list[str] = []
    registered = Counter(row.key for row in rows)
    for key, count in sorted(registered.items()):
        if count > 1:
            message = f"{key.label()} is in the register {count} times"
            problems.append(message)
    verified = {entry.key for entry in entries(library) if entry.verified}
    for key in sorted(verified - set(registered)):
        message = f"{key.label()} is marked verified but is not in the register"
        problems.append(message)
    for key in sorted(set(registered) - verified):
        message = f"{key.label()} is in the register but is not marked verified"
        problems.append(message)
    return problems


def source_problems(references: Mapping[str, ReferenceSet], text: str) -> list[str]:
    """The pinned sources the document must name: their commit and catalog version."""
    problems: list[str] = []
    for key in sorted(references):
        reference = references[key]
        for name in ("commit", "catalog_version"):
            value = reference.source[name]
            if value not in text:
                message = f"{key}: the {name} {value} is not recorded"
                problems.append(message)
    return problems
