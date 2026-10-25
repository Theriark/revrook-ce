"""A report read on a phone (THE-1189): the preview of the quarterly review was 249px
wider than a 390px screen. The file itself now fits a narrow screen, a table wider
than the page scrolls inside itself, and print keeps the A4 layout. No database.
"""

import re
from pathlib import Path

import pytest

from app.checks.library import load_library
from app.reports.render import KINDS
from tools import make_report_golden

LIBRARY = load_library()
REPORTS = Path(__file__).resolve().parent.parent / "app/reports"
CSS = (REPORTS / "report.css").read_text(encoding="utf-8")
PRINT = (REPORTS / "print.css").read_text(encoding="utf-8")
NARROW = "@media screen and (max-width: 40em) {"


def narrow_rules() -> str:
    return CSS[CSS.index(NARROW) :]


def rule(selector: str) -> str:
    found = re.search(r"\n  " + re.escape(selector) + r" \{([^}]*)\}", narrow_rules())
    assert found is not None, selector
    return found.group(1)


def test_the_narrow_rules_are_last_so_they_win_on_a_small_screen() -> None:
    assert CSS.count(NARROW) == 1
    # Nothing follows the block: an earlier rule of the same selector cannot win.
    assert CSS.rstrip().endswith("  }\n}")


def test_the_page_fits_and_a_wide_table_scrolls_inside_itself() -> None:
    page = rule(".page")
    assert "min-height: 0;" in page and "padding: 1.25rem 1rem 1rem;" in page
    assert "padding: 0.5rem;" in rule("body")
    assert "grid-template-columns: minmax(0, 1fr);" in rule("dl.facts")
    assert "overflow-wrap: anywhere;" in rule("h1")
    table = rule("table")
    assert "display: block;" in table and "overflow-x: auto;" in table
    assert "max-width: 100%;" in table


def test_print_keeps_the_a4_layout() -> None:
    assert "@media" not in PRINT and "overflow-x" not in PRINT
    assert "size: A4;" in PRINT


@pytest.mark.parametrize("kind", KINDS)
def test_every_report_carries_the_narrow_rules_on_screen_only(kind: str) -> None:
    html = make_report_golden.golden_html(LIBRARY, kind, "A")
    text = html.decode("utf-8")
    screen, printed = text.split('<style media="print">', 1)
    assert NARROW in screen and "overflow-x: auto;" in screen
    assert NARROW not in printed
    # The comment that explains the rule stays in the source, not in the file.
    assert "THE-1189" not in text
