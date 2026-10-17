"""The fixture generator: deterministic, complete and well formed."""

import json
from pathlib import Path

from tools import make_fixtures
from tools.make_fixtures import SENSITIVE_VALUES

FILES = {
    "entra-registration.json",
    "secure-score.json",
    "intune-devices.csv",
    "conditional-access.json",
    "directory-roles.json",
}


def test_the_five_files_and_a_manifest_are_written(tmp_path: Path) -> None:
    manifest = make_fixtures.write_all(tmp_path)
    assert {path.name for path in tmp_path.iterdir()} == {*FILES, "manifest.json"}
    assert set(manifest["files"]) == FILES
    on_disk = json.loads((tmp_path / "manifest.json").read_text())
    assert on_disk == manifest
    assert on_disk["sensitive_values"] == list(SENSITIVE_VALUES)
    for fixture in make_fixtures.main_fixtures():
        assert (tmp_path / fixture.file_name).read_bytes() == fixture.data
        entry = on_disk["files"][fixture.file_name]
        assert entry["source_code"] == fixture.source_code
        assert entry["facts"] == fixture.facts
        assert entry["expected"] == fixture.expected


def test_the_same_seed_writes_the_same_bytes(tmp_path: Path) -> None:
    make_fixtures.write_all(tmp_path / "one")
    make_fixtures.write_all(tmp_path / "two")
    for name in (*FILES, "manifest.json"):
        assert (tmp_path / "one" / name).read_bytes() == (
            tmp_path / "two" / name
        ).read_bytes()


def test_the_command_line_takes_a_directory_and_a_seed(tmp_path: Path) -> None:
    target = tmp_path / "out"
    assert make_fixtures.main([str(target), "--seed", "7"]) == 0
    assert json.loads((target / "manifest.json").read_text())["seed"] == 7
    assert (target / "intune-devices.csv").is_file()


def test_every_synthetic_address_uses_the_reserved_domain() -> None:
    for fixture in make_fixtures.main_fixtures():
        words = fixture.data.decode().replace('"', " ").replace(",", " ").split()
        for word in words:
            if "@" in word and not word.startswith("@"):
                assert word.split("@")[1] == make_fixtures.DOMAIN
