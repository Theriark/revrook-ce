"""Merge gate check 7 as a test: every dataset under data/ and every model of the
scenes under app/static/models/ has a licence row.

LICENSES-CONTENT.md must name each of those files with its source, licence, the date
read and the SHA-256 of the file as committed. CI check 7 already fails a file under
data/ without a row; this test also fails a row whose hash is not the file's, and a
model file without a row.
"""

import hashlib
import re
from pathlib import Path

from app.ui.brand import CITY_FILES

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "LICENSES-CONTENT.md"
ALLOWED_LICENCES = {"MIT", "CC0-1.0"}
EXPECTED = {
    "data/controls.yaml",
    "data/nist/nist-csf-2.0-names.json",
    "data/nist/nist-sp800-171r3-names.json",
}
# The Kenney City Kit models of the scenes, their colormaps and each kit's licence.
MODELS = {f"app/static/{name}" for name in CITY_FILES} | {
    f"app/static/models/kenney/{kit}/License.txt"
    for kit in ("commercial", "roads", "suburban")
}


def table_rows() -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith(("| ---", "| Path")):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == 5, line
        assert cells[0] not in rows, f"{cells[0]} has two rows"
        rows[cells[0]] = cells
    return rows


def dataset_files() -> set[str]:
    return {
        path.relative_to(ROOT).as_posix()
        for folder in ("data", "app/static/models")
        for path in (ROOT / folder).rglob("*")
        if path.is_file() and path.name != ".gitkeep"
    }


def test_every_dataset_file_has_a_row_and_every_row_a_file() -> None:
    assert dataset_files() == set(table_rows())
    assert set(table_rows()) == EXPECTED | MODELS


def test_the_model_rows_credit_kenney_under_cc0_and_name_the_kit() -> None:
    rows = table_rows()
    for path in MODELS:
        assert rows[path][1].startswith("Kenney (www.kenney.nl), City Kit "), path
        assert rows[path][2] == "CC0-1.0", path
    for kit in ("commercial", "roads", "suburban"):
        licence = (ROOT / f"app/static/models/kenney/{kit}/License.txt").read_bytes()
        assert b"Created/distributed by Kenney (www.kenney.nl)" in licence, kit
        assert b"License: (Creative Commons Zero, CC0)" in licence, kit
        assert 13 not in licence, kit  # no carriage return: LF endings


def test_every_row_gives_the_hash_of_the_file_as_committed() -> None:
    for path, cells in table_rows().items():
        digest = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        assert cells[4] == digest, f"{path}: the hash in LICENSES-CONTENT.md is stale"


def test_every_row_is_complete_and_the_licence_is_permissive() -> None:
    for path, cells in table_rows().items():
        source, licence, date_read, digest = cells[1:]
        assert source, path
        assert licence in ALLOWED_LICENCES, path
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_read), path
        assert re.fullmatch(r"[0-9a-f]{64}", digest), path


def test_the_nist_rows_credit_nist_and_name_the_licence_source() -> None:
    rows = table_rows()
    for path in EXPECTED - {"data/controls.yaml"}:
        assert "NIST" in rows[path][1], path
        assert "usnistgov/oscal-content" in rows[path][1], path
        assert rows[path][2] == "CC0-1.0", path
