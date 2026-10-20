"""The design system (docs/design-system.md): tokens, shell, auth pages, icons.

tests/test_brand_contrast.py checks every colour pair of the stylesheet. This file
checks what the revamp added on top of that: the derived tokens and the type scale,
the app shell every signed-in page shares, the sign-in and first-run layout, that no
control icon is a data: image any more (the content security policy blocks them), and
that the navigation names only routes the application answers.
"""

import re
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ui.auth import templates
from app.ui.brand import BRAND_FILES
from helpers import create_admin, login
from html_structure import structure_problems
from ui_helpers import app_answers, route_app

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "app/static/css/revrook.css").read_text(encoding="utf-8")
SCRIPT = (ROOT / "app/static/js/revrook.js").read_text(encoding="utf-8")
BASE = (ROOT / "app/ui/templates/base.html").read_text(encoding="utf-8")
NAV = (ROOT / "app/ui/templates/_nav.html").read_text(encoding="utf-8")
ICONS = (ROOT / "app/ui/templates/_icons.html").read_text(encoding="utf-8")
HREF = re.compile(r'href="([^"]+)"')
ICON_USE = re.compile(r'i\.icon\("([a-z-]+)"')
FONT_SIZE = re.compile(r"(?<![-\w])font-size:\s*([^;]+);")
NAV_LINK = re.compile(r'<a class="rv-nav-link" href="([^"]+)"( aria-current="page")?>')

# The tokens the revamp derived from the approved palette (docs/design-system.md).
DERIVED_TOKENS = {
    "--rv-canvas": "#f4f3ef",
    "--rv-line": "#e4e2db",
    "--rv-charcoal-deep": "#22242d",
    "--rv-charcoal-soft": "#3a3d4b",
    "--rv-stone-dim": "#a9a69e",
    "--rv-accent-deep": "#3a47b5",
    "--rv-accent-tint": "#eceefa",
}
# Every Pico icon variable; each one is a data: image in the vendored stylesheet.
PICO_ICONS = (
    "checkbox",
    "minus",
    "chevron",
    "date",
    "time",
    "search",
    "close",
    "loading",
    "valid",
    "invalid",
)
# The type scale (px); 1.75rem is the 28px text wordmark.
TYPE_SCALE = {"12px", "13px", "14px", "15px", "16px", "20px", "24px", "28px", "1.75rem"}
# (href, text) of the navigation, in order.
NAV_LINKS = (
    ("/", "Home"),
    ("/clients", "Clients"),
    ("/imports/profile-editor", "Profile editor"),
    ("/evidence/integrity", "Evidence integrity"),
    ("/settings", "Settings"),
    ("/system", "System"),
    ("/glossary", "Glossary"),
)
COMPONENTS = (
    ".rv-page-header",
    ".rv-button-quiet",
    ".rv-button-danger",
    ".rv-field",
    ".rv-help",
    ".rv-field-error",
    "main table thead th",
    ".rv-card",
    ".rv-stat-value",
    "span.rv-status-protected",
    "p.rv-status-protected",
    ".rv-alert",
    ".rv-errors",
    ".rv-empty",
    ".rv-dropzone",
    "details.rv-confirm",
    "dialog.rv-dialog",
    ".rv-skeleton",
    # The Home dashboard (area 2 of the revamp)
    ".rv-stat-note",
    ".rv-spark",
    ".rv-rookery",
    ".rv-ring-arc",
    ".rv-attention-row",
    ".rv-chart",
    ".rv-domains .rv-bar",
    ".rv-seg-protected",
    ".rv-timeline",
    ".rv-steps",
    # The clients list and the client overview (area 3 of the revamp)
    ".rv-client-header",
    ".rv-toolbar",
    ".rv-toolbar-search",
    ".rv-chip",
    ".rv-chip-off",
    ".rv-posture",
    ".rv-posture-ring",
    "main a.rv-sort",
    "main .rv-table-compact th",
    ".rv-pager",
    ".rv-ring-large",
    ".rv-posture-grade",
    ".rv-facts",
    ".rv-mix-bar",
    ".rv-mix-count",
    ".rv-domain-meta",
    # The checklist and the control detail (area 4 of the revamp)
    ".rv-checklist-toolbar",
    ".rv-flags",
    ".rv-coverage",
    ".rv-control-meta",
    ".rv-verdict",
    ".rv-rule",
    ".rv-exception",
    ".rv-empty-small",
    ".rv-suggestion",
    ".rv-notes-saving",
    ".rv-notes-status",
    # Evidence imports, the profile editor and the integrity check (area 5)
    ".rv-date",
    ".rv-refresh",
    ".rv-refresh-how",
    "fieldset.rv-step",
    ".rv-step-title",
    ".rv-step-lead",
    ".rv-editor-busy",
    ".rv-import-next",
    ".rv-chains",
    ".rv-hash",
    # Exceptions, reports, exports, settings, system, glossary, problem (area 6)
    ".rv-under-tabs",
    ".rv-topic",
    ".rv-sheet-band",
    ".rv-sheet",
    ".rv-sheet-title",
    ".rv-sheet-facts",
    ".rv-sheet-rule",
    ".rv-sheet-counts",
    ".rv-kind",
    ".rv-digest",
    ".rv-readonly",
    ".rv-quote",
    ".rv-users",
    ".rv-services",
    ".rv-danger-card",
    ".rv-delete-list",
    ".rv-glossary",
    ".rv-problem",
    ".rv-problem-code",
)
# A placeholder for the CSRF field of a rendered template; not a real token.
PLACEHOLDER_TOKEN = "x" * 32


def render(name: str, brand_files: frozenset[str] = frozenset(BRAND_FILES)) -> str:
    return templates.get_template(name).render(
        title="Sign in",
        errors=[],
        username="",
        csrf_token=PLACEHOLDER_TOKEN,
        brand_files=brand_files,
    )


# --- the stylesheet ---------------------------------------------------------


@pytest.mark.parametrize(("token", "value"), sorted(DERIVED_TOKENS.items()))
def test_the_derived_tokens_have_their_recorded_values(token: str, value: str) -> None:
    assert f"{token}: {value};" in CSS


@pytest.mark.parametrize("name", PICO_ICONS)
def test_every_pico_control_icon_is_switched_off(name: str) -> None:
    assert f"--pico-icon-{name}: none;" in CSS


def test_the_stylesheet_draws_no_image_at_all() -> None:
    assert "data:" not in CSS
    assert "url(" not in CSS
    assert "background-image: none" in CSS


def test_native_controls_replace_the_blocked_icons() -> None:
    select = re.search(r"select:not\(\[multiple\], \[size\]\) \{([^}]*)\}", CSS)
    assert select is not None and "appearance: auto" in select.group(1)
    checkbox = re.search(r'\[type="checkbox"\],\n\[type="radio"\] \{([^}]*)\}', CSS)
    assert checkbox is not None and "appearance: auto" in checkbox.group(1)
    assert "accent-color: var(--rv-accent)" in checkbox.group(1)
    picker = re.search(r"::-webkit-calendar-picker-indicator \{([^}]*)\}", CSS)
    assert picker is not None and "opacity: 1" in picker.group(1)


@pytest.mark.parametrize("selector", COMPONENTS)
def test_the_components_of_the_design_system_exist(selector: str) -> None:
    assert re.search(rf"(^|,\n){re.escape(selector)}[ ,]", CSS, re.MULTILINE), selector


def test_every_font_size_is_on_the_type_scale() -> None:
    sizes = set(FONT_SIZE.findall(re.sub(r"/\*.*?\*/", "", CSS, flags=re.DOTALL)))
    assert sizes - TYPE_SCALE == set(), sizes - TYPE_SCALE


def test_motion_is_short_and_respects_reduced_motion() -> None:
    assert "--rv-motion: 150ms ease-out;" in CSS
    assert "@media (prefers-reduced-motion: reduce)" in CSS


def test_the_narrow_bar_and_the_rail_make_room_for_the_sign_out_button() -> None:
    # Seen on Development at 390px: the edition badge overlapped the sign-out
    # button; at 1440px the button beside the name cut the user name short.
    narrow = re.search(
        r"@media \(max-width: 599px\) \{\n  \.rv-app \.rv-edition \{([^}]*)\}", CSS
    )
    assert narrow is not None and "display: none" in narrow.group(1)
    rail = re.search(r"@media \(min-width: 1024px\) \{(.*?)\n\}\n", CSS, re.DOTALL)
    assert rail is not None
    block = rail.group(1)
    assert re.search(r"\.rv-user \{[^}]*flex-wrap: wrap;", block)
    assert re.search(r"\.rv-user \.rv-inline-form \{[^}]*flex-basis: 100%;", block)
    assert re.search(r"\.rv-user \.rv-button-quiet \{[^}]*width: 100%;", block)


def test_a_submit_button_is_as_wide_as_its_words() -> None:
    # Pico widens every submit button to its form (button[type="submit"]
    # { width: 100% }, specificity 0,1,1), which the :is() button rule of the
    # design system cannot override. Seen on Development: the Search button
    # across the toolbar beside a 54px search box, "Show this period" and "Add
    # client" across their cards. Only the block button of the sign-in pages and
    # the sign-out button of the rail take the whole line.
    rule = re.search(
        r'\nbutton\[type="submit"\],\ninput\[type="submit"\] \{([^}]*)\}', CSS
    )
    assert rule is not None and "width: auto;" in rule.group(1)
    block = re.search(r"\n\.rv-button-block,\nbutton\.rv-button-block \{([^}]*)\}", CSS)
    assert block is not None and "width: 100%;" in block.group(1)
    # The block rule comes later, so at equal specificity it wins
    assert CSS.index('\nbutton[type="submit"],') < CSS.index("\n.rv-button-block,")


def test_the_toolbar_keeps_every_text_on_its_canvas() -> None:
    # The toolbar is a canvas band: a label or a note inside it that kept the white
    # background of the page would show as a white box on the band.
    toolbar = CSS.split("/* Toolbar:", 1)[1].split("/* Chips:", 1)[0]
    for selector in (".rv-toolbar label", ".rv-toolbar-note"):
        rule = re.search(rf"{re.escape(selector)} \{{([^}}]*)\}}", toolbar)
        assert rule is not None, selector
        assert "background-color: var(--rv-canvas);" in rule.group(1), selector
        assert "var(--rv-text-secondary)" not in rule.group(1), selector


def test_the_chips_and_the_status_pills_keep_their_shape() -> None:
    # Seen on Development: Pico marks every list item with a square (ul li
    # { list-style: square }), which showed beside each filter chip; and a pill
    # in the narrow cell of the evidence freshness table broke "Not imported"
    # one letter a line, so the pill stays on one line and that table shares
    # its row evenly with the domains from 1280px.
    chips = re.search(r"\n\.rv-chips li \{([^}]*)\}", CSS)
    assert chips is not None and "list-style: none;" in chips.group(1)
    pill = re.search(r"\nspan\.rv-status-not-applicable \{([^}]*)\}", CSS)
    assert pill is not None and "white-space: nowrap;" in pill.group(1)
    even = re.search(
        r"@media \(min-width: 1280px\) \{\n  \.rv-two-even \{([^}]*)\}", CSS
    )
    assert even is not None and "repeat(2, minmax(0, 1fr))" in even.group(1)


def test_the_clients_table_becomes_cards_on_a_phone_without_a_scroll_box() -> None:
    # A sticky heading needs the page itself to scroll, so the table has no scroll
    # box; below 768px every row is a card and each cell names its column.
    phone = re.search(r"@media \(max-width: 767px\) \{(.*?)\n\}\n", CSS, re.DOTALL)
    assert phone is not None
    block = phone.group(1)
    assert "main table.rv-clients" in block and "display: block;" in block
    assert re.search(r"\.rv-clients thead \{[^}]*clip: rect\(0 0 0 0\);", block)
    before = re.search(r"td\[data-label\]::before \{([^}]*)\}", block)
    assert before is not None
    assert "content: attr(data-label);" in before.group(1)
    assert "background-color: var(--rv-white);" in before.group(1)
    # The caption shrank to one word a line at 390px while it was still a
    # table caption inside the block the table had become
    assert re.search(r"\.rv-clients caption \{[^}]*display: block;", block)
    assert re.search(
        r'\.rv-add-form button\[type="submit"\] \{[^}]*width: 100%;', block
    )


def test_the_checklist_becomes_cards_on_a_phone_and_marks_a_changed_row() -> None:
    # The checklist has six columns and no scroll box (its head is sticky), so
    # below 768px every row is a card and a cell with nothing to flag is dropped.
    # A row whose status changed carries the violet mark beside its words.
    phone = CSS.split("/* On a phone every row of the checklist", 1)[1]
    phone = phone.split("\n}\n", 1)[0]
    assert "main table.rv-checklist" in phone and "display: block;" in phone
    assert re.search(r"\.rv-checklist thead \{[^}]*clip: rect\(0 0 0 0\);", phone)
    before = re.search(r"td\[data-label\]::before \{([^}]*)\}", phone)
    assert before is not None and "content: attr(data-label);" in before.group(1)
    assert re.search(r"\.rv-checklist caption \{[^}]*display: block;", phone)
    assert re.search(r"main \.rv-checklist td:empty \{[^}]*display: none;", phone)
    changed = re.search(
        r'\n\.rv-checklist tr\[data-changed="true"\] > th \{([^}]*)\}', CSS
    )
    assert changed is not None and "var(--rv-accent)" in changed.group(1)


def test_the_verdict_band_and_the_suggestion_keep_every_text_on_the_canvas() -> None:
    # Both are canvas bands: a fact or a suggestion that kept the white background
    # of the page would show as a white box on them (the toolbar rule, again).
    for selector in (
        ".rv-verdict-facts dt",
        ".rv-verdict-facts dd",
        ".rv-suggestion-label",
        ".rv-suggestion-text",
    ):
        rule = re.search(rf"\n{re.escape(selector)} \{{([^}}]*)\}}", CSS)
        assert rule is not None, selector
        assert "background-color: var(--rv-canvas);" in rule.group(1), selector
        assert "var(--rv-text-secondary)" not in rule.group(1), selector
    band = re.search(r"\n\.rv-verdict \{([^}]*)\}", CSS)
    assert band is not None and "background-color: var(--rv-canvas);" in band.group(1)
    large = re.search(
        r"\n\.rv-verdict span\.rv-status-protected,([^{]*)\{([^}]*)\}", CSS
    )
    assert large is not None and "font-size: 16px;" in large.group(2)
    assert large.group(1).count("span.rv-status-") == 4


def test_the_notes_form_shows_that_it_is_saving_while_htmx_posts() -> None:
    # htmx adds htmx-request to the form while a request is in flight; the
    # stylesheet shows the spinner and the word then, and nothing otherwise.
    hidden = re.search(r"\n\.rv-notes-saving \{([^}]*)\}", CSS)
    assert hidden is not None and "display: none;" in hidden.group(1)
    shown = re.search(r"\n#note-form\.htmx-request \.rv-notes-saving \{([^}]*)\}", CSS)
    assert shown is not None and "display: inline-flex;" in shown.group(1)
    control = (ROOT / "app/ui/templates/control.html").read_text(encoding="utf-8")
    assert '<span class="rv-notes-saving" aria-hidden="true">' in control
    assert '<span class="rv-busy"></span>' in control


def test_the_evidence_tables_become_cards_on_a_phone() -> None:
    # The sources, the items and the chains carry rv-table-cards: below 768px
    # every row is a card, each cell names its column, a number aligns left in
    # its card and an empty cell is dropped, as the clients list does.
    phone = CSS.split("/* Any table that carries rv-table-cards", 1)[1]
    phone = phone.split("\n}\n", 1)[0]
    assert "main table.rv-table-cards" in phone and "display: block;" in phone
    assert re.search(r"\.rv-table-cards thead \{[^}]*clip: rect\(0 0 0 0\);", phone)
    before = re.search(r"td\[data-label\]::before \{([^}]*)\}", phone)
    assert before is not None and "content: attr(data-label);" in before.group(1)
    assert "background-color: var(--rv-white);" in before.group(1)
    assert re.search(r"\.rv-table-cards caption \{[^}]*display: block;", phone)
    assert re.search(r"main \.rv-table-cards td:empty \{[^}]*display: none;", phone)
    cells = re.search(r"main \.rv-table-cards tbody td \{([^}]*)\}", phone)
    assert cells is not None and "text-align: left;" in cells.group(1)
    broken = re.search(r'\n\.rv-chains tr\[data-ok="false"\] > th \{([^}]*)\}', CSS)
    assert broken is not None
    assert "var(--rv-status-not-protected)" in broken.group(1)
    for name in ("evidence_imports.html", "evidence_integrity.html"):
        page = (ROOT / "app/ui/templates" / name).read_text(encoding="utf-8")
        assert 'class="rv-table-cards' in page, name
        assert 'data-label="' in page, name


def test_the_editor_steps_are_cards_with_a_busy_indicator_beside_each_button() -> None:
    # The legend of a step floats across its card so it reads as the title; the
    # indicator of a button is shown only while htmx posts (hx-indicator names
    # it, htmx adds htmx-request to it); the hint of the import area is plain.
    legend = re.search(r"\n\.rv-step > legend \{([^}]*)\}", CSS)
    assert legend is not None
    assert "float: left;" in legend.group(1) and "width: 100%;" in legend.group(1)
    assert re.search(r"\n\.rv-step > legend \+ \* \{[^}]*clear: both;", CSS)
    hidden = re.search(r"\n\.rv-editor-busy \{([^}]*)\}", CSS)
    assert hidden is not None and "display: none;" in hidden.group(1)
    shown = re.search(r"\n\.rv-editor-busy\.htmx-request \{([^}]*)\}", CSS)
    assert shown is not None and "display: inline-flex;" in shown.group(1)
    # The import area declares the hint in two places: its own section sets
    # the size, the editor's section (later in the file) makes it plain.
    hints = re.findall(r"\n\.rv-dropzone-hint \{([^}]*)\}", CSS)
    assert len(hints) == 2 and "font-weight: 400;" in hints[-1]
    templates = ROOT / "app/ui/templates"
    editor = (templates / "profile_editor.html").read_text(encoding="utf-8")
    assert 'hx-indicator="#rv-editor-busy"' in editor
    assert '<label class="rv-dropzone">' in editor
    assert '<output class="rv-dropzone-file" aria-live="polite"></output>' in editor
    first = '<legend><span class="rv-step-number">1</span>Client, source and file'
    assert first in editor
    result = (templates / "_profile_editor_result.html").read_text(encoding="utf-8")
    for step in ("2", "4", "5"):
        assert f'<legend><span class="rv-step-number">{step}</span>' in result, step
    assert '<h2 id="step-3-title" class="rv-step-title">' in result
    for name in ("preview", "save", "import"):
        assert f'hx-indicator="#rv-busy-{name}"' in result, name
        assert f'id="rv-busy-{name}" class="rv-editor-busy"' in result, name


def test_the_report_sheet_is_white_paper_on_the_canvas_band() -> None:
    # The signature of the report page: a letter-sized white sheet on the canvas
    # band, drawn with the cover facts of the exported file. The band is canvas,
    # the sheet and every text on it declare white, the title is the 28px of the
    # type scale and the violet rule is the only colour on the page.
    band = re.search(r"\n\.rv-sheet-band \{([^}]*)\}", CSS)
    assert band is not None and "background-color: var(--rv-canvas);" in band.group(1)
    sheet = re.search(r"\n\.rv-sheet \{([^}]*)\}", CSS)
    assert sheet is not None and "background-color: var(--rv-white);" in sheet.group(1)
    assert "box-shadow: var(--rv-shadow-2);" in sheet.group(1)
    title = re.search(r"\n\.rv-sheet-title \{([^}]*)\}", CSS)
    assert title is not None and "font-size: 28px;" in title.group(1)
    rule = re.search(r"\n\.rv-sheet-rule \{([^}]*)\}", CSS)
    assert rule is not None and "background-color: var(--rv-accent);" in rule.group(1)
    report = (ROOT / "app/ui/templates/report.html").read_text(encoding="utf-8")
    sheet_tag = '<article class="rv-sheet" id="sheet" aria-labelledby="sheet-title">'
    assert sheet_tag in report
    for part in ("rv-sheet-head", "rv-sheet-facts", "rv-sheet-rule", "rv-sheet-counts"):
        assert f'class="{part}"' in report, part
    # The ids the tests of phase 9 read stay where they were
    for marker in ('id="summary"', 'id="problems"', 'id="kinds"', 'id="export-status"'):
        assert marker in report, marker
    assert "Ready to export" in report and "to fix first" in report


def test_the_builder_shows_that_it_is_saving_and_the_pages_become_cards() -> None:
    # The details form of the report builder shows the spinner while htmx posts,
    # as the notes card does; the registers of area 6 carry rv-table-cards so a
    # row is a card on a phone, with each cell naming its column.
    shown = re.search(
        r"\n#details-form\.htmx-request \.rv-notes-saving \{([^}]*)\}", CSS
    )
    assert shown is not None and "display: inline-flex;" in shown.group(1)
    builder = (ROOT / "app/ui/templates/reports.html").read_text(encoding="utf-8")
    assert '<span class="rv-notes-saving" aria-hidden="true">' in builder
    for step in ("1", "2", "3"):
        assert f'<span class="rv-step-number">{step}</span>' in builder, step
    topic = re.search(r"@media \(min-width: 768px\) \{\n  \.rv-topic \{([^}]*)\}", CSS)
    assert topic is not None and "minmax(12rem, 1fr)" in topic.group(1)
    for name in ("exceptions.html", "exports.html", "reports.html", "system.html"):
        page = (ROOT / "app/ui/templates" / name).read_text(encoding="utf-8")
        assert 'class="rv-table-cards' in page, name
        assert 'data-label="' in page, name
        assert 'class="rv-empty"' in page, name
    digest = re.search(r"\n\.rv-digest \{([^}]*)\}", CSS)
    assert digest is not None and "overflow-wrap: anywhere;" in digest.group(1)


def test_the_administration_pages_use_header_cards_and_confirmation() -> None:
    # Settings and System open with the page header; the fixed facts of the
    # installation are cards two to a row from 1024px; a client is deleted behind
    # the inline confirmation with the danger button; the glossary is one card
    # with the term beside its meaning from 768px; the problem page is one card
    # with the status code as a figure in violet-blue and two ways back.
    templates = ROOT / "app/ui/templates"
    for name in ("settings.html", "system.html", "glossary.html"):
        page = (templates / name).read_text(encoding="utf-8")
        assert '<div class="rv-page-header">' in page, name
        assert 'class="rv-page-purpose"' in page, name
    settings = (templates / "settings.html").read_text(encoding="utf-8")
    assert '<div class="rv-readonly">' in settings
    assert 'id="users" class="rv-users"' in settings
    columns = re.search(
        r"@media \(min-width: 1024px\) \{\n  \.rv-readonly \{([^}]*)\}", CSS
    )
    assert columns is not None and "repeat(2, minmax(0, 1fr))" in columns.group(1)
    system = (templates / "system.html").read_text(encoding="utf-8")
    assert '<div id="worker-status" class="rv-verdict-status">' in system
    assert '<details class="rv-confirm">' in system
    assert 'class="rv-button-danger"' in system
    assert 'id="clients" class="rv-delete-list"' in system
    glossary = re.search(
        r"@media \(min-width: 768px\) \{\n  \.rv-glossary > div \{([^}]*)\}", CSS
    )
    assert glossary is not None and "15rem minmax(0, 1fr)" in glossary.group(1)
    problem = (templates / "problem.html").read_text(encoding="utf-8")
    assert '<section class="rv-problem" role="alert"' in problem
    assert '<p class="rv-problem-code">' in problem and "{{ status }}" in problem
    assert problem.count('role="button"') == 2
    code = re.search(r"\n\.rv-problem-code \{([^}]*)\}", CSS)
    assert code is not None and "color: var(--rv-accent);" in code.group(1)
    assert "font-size: 28px;" in code.group(1)


# --- the shell --------------------------------------------------------------


def test_the_navigation_names_every_page_once_and_only_real_routes() -> None:
    found = re.findall(
        r'href="([^"]+)"[^>]*>.*?<span class="rv-nav-text">([^<]+)</span>', NAV
    )
    assert found == list(NAV_LINKS)
    app = route_app()
    for href in HREF.findall(NAV):
        assert app_answers(app, href, "GET"), href


def test_every_icon_the_templates_use_is_drawn_without_a_namespace() -> None:
    assert "xmlns" not in ICONS and "http" not in ICONS
    assert 'aria-hidden="true"' in ICONS and 'focusable="false"' in ICONS
    used = set(ICON_USE.findall(NAV)) | set(ICON_USE.findall(BASE))
    assert used >= {"home", "clients", "mapping", "chain", "signout", "check"}
    for name in used:
        assert f'name == "{name}"' in ICONS, name


def test_the_shell_script_is_linked_and_plain() -> None:
    script = '<script src="/static/js/revrook.js?v={{ asset_version }}" defer></script>'
    assert script in BASE
    for forbidden in ("eval(", "http", "fetch(", "XMLHttpRequest", "innerHTML"):
        assert forbidden not in SCRIPT, forbidden
    assert '"use strict"' in SCRIPT


async def test_the_shell_script_is_served_with_the_security_headers(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/static/js/revrook.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "default-src 'self'" in response.headers["content-security-policy"]


async def test_signed_in_pages_share_the_rail_and_mark_the_current_page(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await create_admin(db_engine)
    assert (await login(client)).status_code == 303
    for path, current in (("/", "/"), ("/glossary", "/glossary")):
        page = await client.get(path)
        assert page.status_code == 200, path
        html = page.text
        assert structure_problems(html) == [], path
        assert '<body class="rv-app">' in html
        assert '<nav class="rv-nav" aria-label="Main">' in html
        assert 'src="/static/brand/logo-horizontal-dark-1200x400.png"' in html
        assert 'class="rv-edition">Community Edition' in html
        links = NAV_LINK.findall(html)
        assert [href for href, _ in links] == [href for href, _ in NAV_LINKS]
        assert [href for href, flag in links if flag] == [current]
        assert html.count('aria-current="page"') == 1
        # The rail draws one icon per link and one on the sign-out button; the page
        # below it may draw its own (the Home empty state does).
        rail = html.split("</header>", 1)[0]
        assert rail.count('<svg class="rv-icon"') == len(NAV_LINKS) + 1
        assert '<span class="rv-user-name">admin</span>' in html
        assert 'action="/logout"' in html and ">Sign out</span>" in html
        assert 'class="rv-footer"' in html
        assert 'class="rv-auth-panel"' not in html


def test_the_sign_in_and_first_run_pages_show_the_rook_panel() -> None:
    for name in ("login.html", "setup.html"):
        html = render(name)
        assert structure_problems(html) == [], name
        assert '<body class="rv-signed-out">' in html
        assert '<aside class="rv-auth-panel" aria-label="About revrook">' in html
        assert 'src="/static/brand/logo-stacked-dark-1000x1000.png"' in html
        assert html.count('<svg class="rv-icon"') == 3
        assert 'class="rv-logo"' in html and 'height="36"' in html
        assert 'class="rv-auth-lead"' in html
        assert 'class="rv-button-block"' in html
        assert 'class="rv-nav"' not in html and "logo-horizontal-dark" not in html
        bare = render(name, frozenset())
        assert structure_problems(bare) == [], name
        assert "/static/brand/" not in bare
    setup = render("setup.html")
    assert 'aria-describedby="password-help"' in setup
    assert 'id="password-help">At least 12 characters.' in setup
