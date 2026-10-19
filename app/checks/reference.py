"""NIST reference names for the framework mappings of the control library.

The names of NIST CSF 2.0 subcategories and NIST SP 800-171 Rev 3 requirements
come from the NIST OSCAL content repository, which is in the public domain and
dedicated worldwide under CC0 1.0. The two datasets under data/nist carry their
credit, source file, commit and licence; a row for each is in LICENSES-CONTENT.md.
Each is a names extract: it holds only the identifiers that the control file maps,
so checking the mapped identifiers against it (`verify-mappings`) is a consistency
check, not a comparison with the full NIST catalog.

A name is looked up by the identifier of a mapping row. It is shown only for a row
a person has verified (see app.checks.library.visible_mappings): until then no
external identifier, and so no name, reaches a rendered output.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.checks.library import ROOT, ControlLibraryError, Library

NIST_DIR = ROOT / "data" / "nist"
# The framework key of a mapping row -> its dataset file and dataset framework.
DATASETS = {
    "csf": ("nist-csf-2.0-names.json", "nist-csf-2.0"),
    "sp800-171": ("nist-sp800-171r3-names.json", "nist-sp800-171r3"),
}
SOURCE_KEYS = (
    "repository",
    "file",
    "commit",
    "catalog_title",
    "catalog_version",
    "catalog_last_modified",
    "catalog_published",
    "oscal_version",
    "licence_file_read",
)
LICENCE = "CC0-1.0"
CREDIT_MARK = "National Institute of Standards and Technology"
SET_KEYS = {"credit", "licence", "framework", "source", "scope", "names"}


@dataclass(frozen=True)
class ReferenceSet:
    """One dataset: the credit to show, where it came from, and id -> name."""

    framework: str
    credit: str
    licence: str
    source: Mapping[str, str]
    names: Mapping[str, str]


def _check_set(raw: Mapping[str, Any], file_name: str, framework: str) -> list[str]:
    problems: list[str] = []
    if set(raw) != SET_KEYS:
        problems.append(f"{file_name}: the keys are not {sorted(SET_KEYS)}")
        return problems
    if raw["framework"] != framework:
        problems.append(f"{file_name}: the framework is not {framework}")
    if raw["licence"] != LICENCE:
        problems.append(f"{file_name}: the licence is not {LICENCE}")
    if CREDIT_MARK not in str(raw["credit"]):
        problems.append(f"{file_name}: the credit does not name NIST")
    source = raw["source"]
    if not isinstance(source, dict) or set(source) != set(SOURCE_KEYS):
        problems.append(f"{file_name}: the source does not give {SOURCE_KEYS}")
    names = raw["names"]
    if not isinstance(names, list) or not names:
        problems.append(f"{file_name}: there are no names")
        return problems
    seen: set[str] = set()
    for item in names:
        identifier = item.get("id") if isinstance(item, dict) else None
        text = item.get("name") if isinstance(item, dict) else None
        if not isinstance(identifier, str) or not isinstance(text, str) or not text:
            problems.append(f"{file_name}: an entry has no id or no name")
        elif identifier in seen:
            problems.append(f"{file_name}: {identifier} is written twice")
        else:
            seen.add(identifier)
    return problems


def load_reference_names(directory: Path = NIST_DIR) -> dict[str, ReferenceSet]:
    """Load both datasets, keyed by the framework key of the mapping rows.

    Raises ControlLibraryError when a file is missing, is not JSON, lacks its
    credit, source or licence, or repeats an identifier.
    """
    loaded: dict[str, ReferenceSet] = {}
    problems: list[str] = []
    for key, (file_name, framework) in DATASETS.items():
        try:
            raw = json.loads((directory / file_name).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            problems.append(f"{file_name} cannot be read: {error}")
            continue
        if not isinstance(raw, dict):
            problems.append(f"{file_name} is not an object")
            continue
        found = _check_set(raw, file_name, framework)
        problems.extend(found)
        if not found:
            loaded[key] = ReferenceSet(
                framework=framework,
                credit=raw["credit"],
                licence=raw["licence"],
                source=dict(raw["source"]),
                names={item["id"]: item["name"] for item in raw["names"]},
            )
    if problems:
        raise ControlLibraryError(problems)
    return loaded


def reference_problems(
    library: Library, references: Mapping[str, ReferenceSet]
) -> list[str]:
    """Mapping rows whose identifier has no name, and names no row refers to."""
    problems: list[str] = []
    used: dict[str, set[str]] = {key: set() for key in references}
    for control in library.controls:
        for row in control.mappings:
            reference = references.get(row.framework)
            if reference is None:
                continue
            used[row.framework].add(row.id)
            if row.id not in reference.names:
                problems.append(f"{control.id}: {row.framework} {row.id} has no name")
    for key, reference in references.items():
        for identifier in sorted(set(reference.names) - used[key]):
            problems.append(f"{reference.framework}: {identifier} is mapped by none")
    return problems


def credit_lines(references: Mapping[str, ReferenceSet]) -> list[str]:
    """The credit text of every dataset in use, for a page or a report footer."""
    return [references[key].credit for key in sorted(references)]
