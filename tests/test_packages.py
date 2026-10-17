import importlib
import tomllib
from pathlib import Path

import pytest

from app import __version__
from app.ext import EXTENSION_API_VERSION, PLUGIN_ENTRY_POINT_GROUP

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = [
    "app.checks",
    "app.scoring",
    "app.evidence",
    "app.importers",
    "app.ui",
    "app.ext",
    "app.worker",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name: str) -> None:
    assert importlib.import_module(name).__doc__


def test_version_matches_pyproject() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    assert project["version"] == __version__ == "0.0.0.dev0"
    assert project["requires-python"] == ">=3.12,<3.13"


def test_console_script_and_plugin_group_are_declared() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["scripts"]["revrook"] == "app.cli:main"
    assert PLUGIN_ENTRY_POINT_GROUP == "revrook.plugins"
    assert "revrook.plugins" in pyproject["project"]["entry-points"]


def test_extension_api_version_is_one() -> None:
    assert EXTENSION_API_VERSION == 1
