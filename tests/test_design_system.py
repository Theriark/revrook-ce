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
)


def render(name: str, brand_files: frozenset[str] = frozenset(BRAND_FILES)) -> str:
    return templates.get_template(name).render(
        title="Sign in",
        errors=[],
        username="",
        csrf_token="***REDACTED***",
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
