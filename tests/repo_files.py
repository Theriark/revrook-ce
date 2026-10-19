"""The text files of the repository, for the tests that guard what they hold."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_SUFFIXES = {
    ".py",
    ".html",
    ".md",
    ".sh",
    ".yml",
    ".yaml",
    ".css",
    ".json",
    ".toml",
    ".txt",
    ".in",
    ".mako",
    ".cfg",
    ".ini",
}
SOURCE_NAMES = {".env.example", ".dockerignore", ".gitignore", "Dockerfile"}
SKIPPED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "__pycache__",
    "build",
    "node_modules",
    "vendor",
}


def source_files() -> list[Path]:
    """Every text file of the repository, without caches and vendored files."""
    found: list[Path] = []
    for folder, names, files in os.walk(ROOT):
        names[:] = [name for name in names if name not in SKIPPED_DIRECTORIES]
        found.extend(
            Path(folder) / name
            for name in files
            if Path(name).suffix in SOURCE_SUFFIXES or name in SOURCE_NAMES
        )
    return sorted(found)
