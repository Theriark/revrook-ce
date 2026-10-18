"""NIST reference names: credit, licence and the link to the mappings (phase 5).

data/nist holds the names of the NIST CSF 2.0 subcategories and NIST SP 800-171
Rev 3 requirements that data/controls.yaml maps to, taken from the NIST OSCAL
content repository (public domain, CC0 1.0). The tests check the credit and
licence that each dataset must carry, that every mapped identifier has a name,
and that no external identifier is shown while its row is unverified.
"""

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.checks.library import (
    CONTROLS_PATH,
    ControlLibraryError,
    build_library,
    load_library,
    parse_yaml,
    visible_mappings,
)
from app.checks.reference import (
    DATASETS,
    NIST_DIR,
    credit_lines,
    load_reference_names,
    reference_problems,
)

NIST = "National Institute of Standards and Technology"
COMMIT = re.compile(r"^[0-9a-f]{40}$")


def test_both_datasets_load_with_their_credit_licence_and_source() -> None:
    references = load_reference_names()
    assert set(references) == {"csf", "sp800-171"}
    assert len(references["csf"].names) == 32
    assert len(references["sp800-171"].names) == 26
    for reference in references.values():
        assert reference.licence == "CC0-1.0"
        assert NIST in reference.credit
        assert "public domain" in reference.credit
        assert "CC0 1.0" in reference.credit
        assert "does not imply endorsement" in reference.credit
        assert COMMIT.match(reference.source["commit"])
        assert reference.source["repository"].endswith("usnistgov/oscal-content")
        assert reference.source["licence_file_read"].endswith("read 2026-10-18")
    names = references["csf"].names
    assert names["PR.AA-03"] == "Users, services, and hardware are authenticated"
    assert references["sp800-171"].names["03.05.03"] == "Multi-Factor Authentication"
    assert len(credit_lines(references)) == 2


def test_every_mapped_nist_identifier_has_a_name_and_every_name_is_mapped() -> None:
    assert reference_problems(load_library(), load_reference_names()) == []


def test_a_mapping_without_a_name_and_a_name_without_a_mapping_are_reported() -> None:
    document = parse_yaml(CONTROLS_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    first = document["controls"][0]
    first["mappings"].append({"framework": "csf", "id": "PR.ZZ-99", "verified": False})
    for control in document["controls"]:
        control["mappings"] = [
            row for row in control["mappings"] if row["id"] != "GV.SC-01"
        ]
    problems = reference_problems(build_library(document), load_reference_names())
    assert problems == [
        "PC-ACC-01: csf PR.ZZ-99 has no name",
        "nist-csf-2.0: GV.SC-01 is mapped by none",
    ]


def test_no_nist_identifier_or_name_is_shown_while_its_row_is_unverified() -> None:
    library = load_library()
    references = load_reference_names()
    for control in library.controls:
        shown = visible_mappings(control)
        assert not [row for row in shown if row.framework in references], control.id
    assert all(
        not row.verified
        for control in library.controls
        for row in control.mappings
        if row.framework in references
    )


def copy_datasets(target: Path, change: Callable[[dict[str, Any]], None]) -> Path:
    """Copy both datasets to `target`, applying `change` to the CSF one."""
    target.mkdir()
    for key, (file_name, _) in DATASETS.items():
        document = json.loads((NIST_DIR / file_name).read_text(encoding="utf-8"))
        if key == "csf":
            change(document)
        (target / file_name).write_text(json.dumps(document), encoding="utf-8")
    return target


def drop_credit(document: dict[str, Any]) -> None:
    del document["credit"]


def credit_without_nist(document: dict[str, Any]) -> None:
    document["credit"] = "Names from a public repository."


def wrong_licence(document: dict[str, Any]) -> None:
    document["licence"] = "MIT"


def wrong_framework(document: dict[str, Any]) -> None:
    document["framework"] = "nist-csf-1.1"


def incomplete_source(document: dict[str, Any]) -> None:
    del document["source"]["commit"]


def repeated_identifier(document: dict[str, Any]) -> None:
    document["names"].append(dict(document["names"][0]))


def nameless_entry(document: dict[str, Any]) -> None:
    document["names"][0]["name"] = ""


def no_names(document: dict[str, Any]) -> None:
    document["names"] = []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (drop_credit, "the keys are not"),
        (credit_without_nist, "the credit does not name NIST"),
        (wrong_licence, "the licence is not CC0-1.0"),
        (wrong_framework, "the framework is not nist-csf-2.0"),
        (incomplete_source, "the source does not give"),
        (repeated_identifier, "PR.AA-01 is written twice"),
        (nameless_entry, "an entry has no id or no name"),
        (no_names, "there are no names"),
    ],
)
def test_a_dataset_without_its_credit_licence_or_source_is_refused(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], expected: str
) -> None:
    directory = copy_datasets(tmp_path / "nist", change)
    with pytest.raises(ControlLibraryError, match=expected):
        load_reference_names(directory)


def test_a_missing_or_unreadable_dataset_is_a_named_error(tmp_path: Path) -> None:
    with pytest.raises(ControlLibraryError, match="nist-csf-2.0-names.json cannot"):
        load_reference_names(tmp_path)
    directory = copy_datasets(tmp_path / "nist", no_names)
    (directory / "nist-sp800-171r3-names.json").write_text("[", encoding="utf-8")
    with pytest.raises(ControlLibraryError) as raised:
        load_reference_names(directory)
    assert "nist-sp800-171r3-names.json cannot be read" in str(raised.value)
    assert "nist-csf-2.0-names.json: there are no names" in str(raised.value)
