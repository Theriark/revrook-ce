"""A report read on a phone (THE-1189): the preview of the quarterly review was 249px
wider than a 390px screen. The file itself now fits a narrow screen, a table wider
than the page scrolls inside a named frame the keyboard reaches while its caption
stays whole, and print keeps the A4 layout. No database.
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
    frame = rule(".table-scroll")
    assert "overflow-x: auto;" in frame and "max-width: 100%;" in frame
    assert "container-type: inline-size;" in frame


def test_a_table_stays_a_table_and_its_caption_is_read_whole() -> None:
    # A table shown as a block loses its rows and cells in some screen readers, and
    # its caption scrolled away with the columns: the frame scrolls instead.
    assert not re.search(r"\n  table \{", narrow_rules())
    assert "display: block" not in narrow_rules()
    caption = rule(".table-scroll caption")
    assert "position: sticky;" in caption and "left: 0;" in caption
    assert "width: 100cqi;" in caption
    # The frame is reached by the keyboard, so it shows where the focus is.
    focus = re.search(r"\n\.table-scroll:focus-visible \{([^}]*)\}", CSS)
    assert focus is not None
    assert "outline: 2px solid var(--rv-accent);" in focus.group(1)


FRAME = re.compile(
    r'<div class="table-scroll" role="region" tabindex="0" '
    r'aria-labelledby="([a-z0-9-]+)">\n<table>\n<caption id="\1">[^<]+</caption>'
)


@pytest.mark.parametrize("kind", KINDS)
def test_every_table_sits_in_a_named_frame_the_keyboard_reaches(kind: str) -> None:
    html = make_report_golden.golden_html(LIBRARY, kind, "A").decode("utf-8")
    tables = html.count("<table>")
    frames = FRAME.findall(html)
    assert tables > 0 and len(frames) == tables
    ids = re.findall(r' id="([^"]+)"', html)
    assert len(ids) == len(set(ids))


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
