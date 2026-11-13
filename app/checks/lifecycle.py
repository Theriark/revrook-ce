"""The shipped vendor end-of-support dates (data/lifecycle.yaml) read by PC-DEV-03."""

import datetime as dt
from functools import cache
from pathlib import Path

import yaml

from app.checks.model import LifecycleEntry

LIFECYCLE_PATH = Path(__file__).resolve().parents[2] / "data" / "lifecycle.yaml"
FAMILIES = frozenset({"windows", "macos", "linux", "ios", "android"})
FORM_FACTORS = frozenset({"server", "workstation"})


def parse_lifecycle(text: str) -> tuple[LifecycleEntry, ...]:
    """The entries of the table; ValueError names the first entry that is wrong."""
    document = yaml.safe_load(text) or {}
    entries: list[LifecycleEntry] = []
    for number, raw in enumerate(document.get("entries") or [], start=1):
        os_name, prefix = raw.get("os"), raw.get("version_prefix")
        end, form = raw.get("end_of_support"), raw.get("form_factor")
        if os_name not in FAMILIES or not isinstance(prefix, str) or not prefix:
            raise ValueError(f"lifecycle entry {number}: os or version_prefix is wrong")
        if not isinstance(end, dt.date) or form not in (None, *FORM_FACTORS):
            raise ValueError(f"lifecycle entry {number}: end_of_support or form_factor")
        entries.append(LifecycleEntry(os_name, prefix, end, form))
    keys = [(e.os, e.version_prefix, e.form_factor) for e in entries]
    if len(keys) != len(set(keys)):
        raise ValueError("lifecycle: an os, version_prefix and form_factor is repeated")
    return tuple(entries)


@cache
def load_lifecycle(path: Path = LIFECYCLE_PATH) -> tuple[LifecycleEntry, ...]:
    return parse_lifecycle(path.read_text(encoding="utf-8"))
