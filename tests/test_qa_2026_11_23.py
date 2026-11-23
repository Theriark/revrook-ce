"""The three findings of the Stage QA of 2026-11-23 (rc.17, build d31fd03b7667).

REV-382: the theme button of the top bar shrank from 40px to its icon under the
pointer, so a click on its right half did nothing. The square was set only through
`.rv-icon-button:not(:hover)`; under the pointer `button[type="submit"] { width:
auto }` won. After the top bar changed the theme, the Account page kept its old
choice until a reload.

REV-383: at phone width the names over the companies ring of the Evidence Explorer
ran into one another and three were missing. A domain now goes by its first word on
a phone-sized stage, the domains are placed before the client chips, no name may
touch a domain's name, and a domain's name steps a line up or down before it gives
way.

REV-384: the sources table of a client's evidence page was 37 to 45px wider than its
card at 768 and 1024px, with the last column cut off. It now stands in a scroll
region like the other wide tables, and fits at those widths.

CI has no browser: the stylesheets and scripts are read as text here, the page is
read through the application (PostgreSQL), and the live checks are in the pull
request.
"""

import re

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.evidence.service import EvidenceContext
from app.ui.brand import STATIC_DIR
from html_structure import structure_problems
from ui_helpers import seed_client, sign_in

REVAMP = (STATIC_DIR / "css/revamp.css").read_text(encoding="utf-8")
SHELL = (STATIC_DIR / "js/revrook.js").read_text(encoding="utf-8")
EXPLORER = (STATIC_DIR / "js/evidence-explorer.js").read_text(encoding="utf-8")
EXPLORER_CSS = (STATIC_DIR / "css/evidence-explorer.css").read_text(encoding="utf-8")


def rule(css: str, selector: str) -> str:
    """The declarations of the first rule whose selector list is `selector`."""
    found = re.search(r"(?:^|\n)" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert found is not None, selector
    return found.group(1)


def body_of(name: str) -> str:
    start = EXPLORER.index(f"function {name}(")
    line = EXPLORER.rfind("\n", 0, start) + 1
    indent = EXPLORER[line:start]
    return EXPLORER[start : EXPLORER.index(f"\n{indent}}}\n", start)]


# --- REV-382 ------------------------------------------------------------------------


def test_an_icon_button_is_a_square_of_40px_under_the_pointer_too() -> None:
    square = rule(
        REVAMP,
        ".rv-icon-button,\n.rv-icon-button:not(:hover),\n.rv-icon-button:hover",
    )
    assert "width: 40px;" in square and "height: 40px;" in square
    # The rule for the pointer alone draws the frame and sets no size, so the square
    # above stays the only width an icon button has.
    hover = REVAMP.split("}\n\n.rv-icon-button:hover {", 1)[1].split("}", 1)[0]
    assert "width" not in hover and "border-color" in hover


def test_the_account_page_follows_the_theme_the_top_bar_sets() -> None:
    start = SHELL.index("function setTheme(theme) {")
    body = SHELL[start : SHELL.index("\n  }\n", start)]
    assert "'.rv-account-theme input[name=\"theme\"][value=\"' + theme + '\"]'" in body
    assert "choice.checked = true;" in body


# --- REV-383 ------------------------------------------------------------------------


def test_on_a_phone_a_domain_of_the_ring_goes_by_its_first_word() -> None:
    compact = body_of("compactLabels")
    assert 'overlay.classList.toggle("is-compact", on);' in compact
    assert 'item.full.split(" ")[0] : item.full' in compact
    assert "measured = false;" in compact
    resize = body_of("resize")
    assert "compactLabels(width < COMPACT_STAGE);" in resize
    # Set before the view is fitted, so the fit measures the names it will show.
    assert resize.index("compactLabels(") < resize.index("fitDistance(")
    assert "const COMPACT_STAGE = 480;" in EXPLORER
    assert ".rv-explorer-labels.is-compact .rv-explorer-label-extra {" in EXPLORER_CSS


def test_no_name_touches_a_domain_and_a_domain_steps_before_it_gives_way() -> None:
    place = body_of("placeLabels")
    # The domains first, so the eight names of the map always find their place.
    assert "b.domain - a.domain" in place
    assert "if (item.domain || other.domain) {" in place
    assert "return across > -LABEL_AIR && down > -LABEL_AIR;" in place
    assert "const steps = item.domain ? LABEL_STEPS : LABEL_STEPS.slice(0, 1);" in place
    assert "const LABEL_STEPS = [0, -1, 1, -2, 2];" in EXPLORER
    # A stepped name is still kept inside the stage.
    assert "Math.max(4, height - item.height - 4)" in place


# --- REV-384 ------------------------------------------------------------------------


def test_the_sources_table_fits_its_card_between_768_and_1099px() -> None:
    narrow = REVAMP.split("@media (min-width: 768px) and (max-width: 1099px) {")
    assert len(narrow) > 1
    block = narrow[-1].split("\n}\n", 1)[0]
    assert ".rv-sources :is(th, td) {" in block and "padding-inline: 8px;" in block
    assert ".rv-sources .rv-age-cell .rv-age-bar {" in block
    assert "min-width: 64px;" in block


async def test_the_sources_table_stands_in_a_scroll_region(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    html = (await ui_browser.get(f"/clients/{client_id}/evidence")).text
    assert structure_problems(html) == []
    region = (
        '<div class="rv-table-scroll rv-sources-scroll" role="region" '
        'aria-label="Sources table" tabindex="0">\n'
        '<table id="sources" class="rv-table-cards rv-sources">'
    )
    assert region in html
    after = html.split(region, 1)[1]
    assert after.index("</table>") < after.index("</div>")


# --- The account menu under the page (found in the Dev check of REV-367) -----------


def test_the_top_bar_with_its_account_menu_lies_above_the_page() -> None:
    # The bar is a stacking context (its view-transition-name), so its own z-index,
    # not the menu's, decides whether the page draws over the open menu.
    assert ".rv-topbar {\n  view-transition-name: rv-topbar;\n}" in REVAMP
    lifted = rule(REVAMP, ".rv-app .rv-topbar")
    assert "position: relative;" in lifted and "z-index: 15;" in lifted
    # Above every layer of the page (the sticky rail is 10, the bulk bar 5), under
    # the skip link (20) and a chart's tip (30).
    sheets = "".join(
        (STATIC_DIR / f"css/{name}.css").read_text(encoding="utf-8")
        for name in ("revrook", "bulk-actions", "charts", "scenes", "revrook-retest")
    )
    levels = sorted({int(z) for z in re.findall(r"z-index:\s*(\d+);", sheets)})
    assert levels == [1, 5, 10, 20, 30]
