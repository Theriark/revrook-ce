import re
from pathlib import Path

import pytest

from tools import licence_audit

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "docs" / "licences.md").read_text(encoding="utf-8")
# Rows above this heading are the dependencies whose LICENSE file was read.
READ_SECTION = DOC.split("## Planned dependencies")[0]


def direct_dependencies(path: Path) -> list[str]:
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text and not text.startswith(("#", "-")):
            names.append(re.split(r"[<>=!~;\[ ]", text, maxsplit=1)[0])
    return names


def table_rows() -> dict[str, list[str]]:
    rows = {}
    for line in READ_SECTION.splitlines():
        if line.startswith("|") and not line.startswith("| ---"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            rows[cells[0].lower()] = cells
    return rows


def test_there_are_runtime_dependencies_to_check() -> None:
    assert len(direct_dependencies(ROOT / "requirements.in")) >= 10


@pytest.mark.parametrize(
    "name", direct_dependencies(ROOT / "requirements.in") + ["htmx", "Pico CSS"]
)
def test_every_direct_dependency_has_a_complete_row(name: str) -> None:
    row = table_rows().get(name.lower())
    assert row is not None, f"{name} has no row in docs/licences.md"
    spdx, licence_file, date_read = row[1], row[2], row[3]
    assert spdx and "NOT READ" not in licence_file
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_read)
    # The recorded identifier must pass the same allow-list the audit enforces.
    assert licence_audit.is_allowed_expression(spdx)


def test_dnspython_is_recorded_as_permissive() -> None:
    assert table_rows()["dnspython"][1] == "ISC"


def test_httpx_is_not_a_runtime_dependency() -> None:
    # httpx requires certifi (MPL-2.0); see the open decision in docs/licences.md.
    assert "httpx" not in direct_dependencies(ROOT / "requirements.in")
    assert "httpx" in direct_dependencies(ROOT / "requirements-dev.in")


def test_driver_decision_is_recorded() -> None:
    assert "Decision: asyncpg" in DOC
