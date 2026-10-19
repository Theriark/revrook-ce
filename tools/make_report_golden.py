"""Writes the golden reports: tests/golden/reports/<kind>-client-<a|b|c>.html.

    python3 tools/make_report_golden.py

The golden files are what the renderers must produce, byte for byte, for the three
worked clients (tests/test_reports.py). Run this script only when a report is
meant to change (a template, the stylesheet, the disclaimer or a rule of the labels),
read the diff of the golden files like any other change, and commit them with it.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

from app.checks.library import Library, load_library
from app.reports.render import KINDS, render_report
from app.reports.view import build_view
from tools import report_clients

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "tests" / "golden" / "reports"


def golden_path(kind: str, name: str) -> Path:
    return GOLDEN_DIR / f"{kind}-client-{name.lower()}.html"


def golden_html(library: Library, kind: str, name: str) -> bytes:
    """The report of one worked client, made the way the tests make it."""
    view = build_view(
        report_clients.snapshot_bytes(library, name),
        library,
        report_clients.context_for(name),
        report_clients.previous_bytes(library, name),
    )
    return render_report(kind, view)


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    library = load_library()
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for kind in KINDS:
        for name in report_clients.NAMES:
            path = golden_path(kind, name)
            path.write_bytes(golden_html(library, kind, name))
            print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
