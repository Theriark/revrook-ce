"""The theme switch (docs/design-system.md, Themes): tokens, templates, route.

tests/test_brand_contrast.py checks every colour pair in both themes; this file
checks the recorded dark values, that the switch is on every page, that the page
carries the theme, and that /theme remembers it on the user row and in the
cookie. The route tests need PostgreSQL (DATABASE_URL) and are skipped without it.
"""

import re
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from test_brand_contrast import DARK_SELECTOR, RULES, SYSTEM_SELECTOR, VARIABLES

from app.models import AppUser
from app.theme import (
    COLOR_SCHEMES,
    DEFAULT_THEME,
    THEME_COOKIE,
    THEMES,
    normalise_theme,
    safe_next,
)
from app.ui.auth import templates
from app.ui.brand import BRAND_FILES
from helpers import create_admin, get_csrf
from ui_helpers import sign_in

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app/ui/templates"
CSS = (ROOT / "app/static/css/revrook.css").read_text(encoding="utf-8")
FOLLOW_UP = (ROOT / "app/static/css/revrook-retest.css").read_text(encoding="utf-8")
SCRIPT = (ROOT / "app/static/js/revrook.js").read_text(encoding="utf-8")
BASE = (TEMPLATES / "base.html").read_text(encoding="utf-8")
NAV = (TEMPLATES / "_nav.html").read_text(encoding="utf-8")
SWITCH = (TEMPLATES / "_theme.html").read_text(encoding="utf-8")
ICONS = (TEMPLATES / "_icons.html").read_text(encoding="utf-8")
# The dark values of the roles (docs/design-system.md, Tokens).
DARK = {
    "--rv-text": "#e6e7ec",
    "--rv-text-secondary": "#aab0bd",
    "--rv-surface": "#1e2028",
    "--rv-canvas": "#272a34",
    "--rv-line": "#3a3e4b",
    "--rv-line-strong": "#4d5261",
    "--rv-rail": "#15161c",
    "--rv-charcoal-deep": "#0e0f13",
    "--rv-charcoal-soft": "#2a2d38",
    "--rv-ink": "#5563dc",
    "--rv-link": "#8b97f2",
    "--rv-primary": "#8b97f2",
    "--rv-accent-deep": "#aeb7f6",
    "--rv-accent-tint": "#2b3050",
    "--rv-focus": "#ffffff",
    "--rv-veil": "rgba(0, 0, 0, 0.6)",
    "--rv-status-protected": "#4fbf7a",
    "--rv-status-needs-attention": "#e0a93c",
    "--rv-status-not-protected": "#ff8a80",
    "--rv-status-not-checked": "#aab0bd",
}
# The light roles that stand for a palette colour.
LIGHT_ROLES = {
    "--rv-text": "var(--rv-charcoal)",
    "--rv-surface": "var(--rv-white)",
    "--rv-line-strong": "var(--rv-stone)",
    "--rv-rail": "var(--rv-charcoal)",
    "--rv-ink": "var(--rv-charcoal)",
    "--rv-link": "var(--rv-accent)",
    "--rv-primary": "var(--rv-accent)",
    "--rv-focus": "var(--rv-charcoal)",
}
BUTTON = re.compile(
    r'<button type="submit" name="theme" value="(light|dark|system)" '
    r'aria-pressed="(true|false)" aria-label="(Light|Dark|System)"'
)


def block(selector: str, css: str = CSS) -> dict[str, str]:
    """The declarations of the rule with exactly this selector."""
    found = [decl for sel, decl in RULES if sel == selector]
    assert len(found) == 1, selector
    return found[0]


def render(
    name: str, brand_files: frozenset[str] = frozenset(BRAND_FILES), **context: object
) -> str:
    return templates.get_template(name).render(
        title="Sign in",
        errors=[],
        username="",
        csrf_token="x" * 32,
        brand_files=brand_files,
        **context,
    )


# --- the stylesheet ---------------------------------------------------------


def test_the_light_block_is_the_root_and_names_no_theme() -> None:
    assert "\n:root {\n" in CSS and "\n:root {\n" in FOLLOW_UP
    assert ':root:not([data-theme="dark"])' not in CSS
    assert ':root:not([data-theme="dark"])' not in FOLLOW_UP
    assert block(":root").get("color-scheme") == "light"
    for token, value in LIGHT_ROLES.items():
        assert VARIABLES[token] == value, token


@pytest.mark.parametrize(("token", "value"), sorted(DARK.items()))
def test_the_dark_values_are_the_recorded_ones(token: str, value: str) -> None:
    assert block(DARK_SELECTOR)[token] == value


def test_the_dark_block_also_deepens_the_shadows() -> None:
    dark = block(DARK_SELECTOR)
    assert set(dark) == set(DARK) | {"--rv-shadow-1", "--rv-shadow-2", "color-scheme"}
    assert dark["--rv-shadow-1"] != VARIABLES["--rv-shadow-1"]
    assert dark["--rv-shadow-2"] != VARIABLES["--rv-shadow-2"]


def test_the_system_theme_follows_the_system_without_script() -> None:
    media = CSS.split("@media (prefers-color-scheme: dark) {", 1)
    assert len(media) == 2 and '\n  :root[data-theme="system"] {' in media[1]
    assert block(SYSTEM_SELECTOR) == block(DARK_SELECTOR)
    # The brand needs no rule per theme: the mark is drawn on nothing, its tile
    # is the stylesheet's and the wordmark takes the colours of the roles.
    assert "rv-logo-on-dark" not in CSS
    assert block(".rv-mark")["background-color"] == "var(--rv-mark-tile)"
    assert VARIABLES["--rv-mark-tile"] == "#fffef5"
    assert "--rv-mark-tile" not in block(DARK_SELECTOR)


def test_the_veil_and_the_danger_face_are_roles() -> None:
    assert block("dialog.rv-dialog::backdrop") == {"background-color": "var(--rv-veil)"}
    assert "background-color: var(--rv-veil);" in FOLLOW_UP
    danger = block(".rv-button-danger, .rv-button-danger:not(:hover)")
    assert danger["background-color"] == "var(--rv-danger-fill)"
    assert danger["color"] == "var(--rv-white)"


def test_the_switch_has_its_own_rules_in_both_shells() -> None:
    pill = block(".rv-theme")
    assert pill["background-color"] == "var(--rv-rail)"
    pressed = block('.rv-theme button:hover, .rv-theme button[aria-pressed="true"]')
    assert pressed["color"] == "var(--rv-white)"
    signed_out = block(
        ".rv-signed-out .rv-theme button:hover, "
        '.rv-signed-out .rv-theme button[aria-pressed="true"]'
    )
    assert signed_out["background-color"] == "var(--rv-ink)"
    rail = re.search(
        r"@media \(min-width: 1024px\) \{\n  \.rv-app \.rv-theme \{([^}]*)\}", CSS
    )
    assert rail is not None and "flex-basis: 100%;" in rail.group(1)
    # In the 248px rail the three words fit and the icons go (icons beside the
    # words were 253px in 220px on Development); the bar keeps the icons only.
    assert "\n.rv-theme-text {\n  display: none;\n}\n" in CSS
    assert "  .rv-app .rv-theme-text {\n    display: inline;\n  }" in CSS
    rail_fix = re.search(
        r"@media \(min-width: 1024px\) \{\n  \.rv-app \.rv-theme \.rv-icon \{([^}]*)\}",
        FOLLOW_UP,
    )
    assert rail_fix is not None and "display: none;" in rail_fix.group(1)


# --- the templates and the script ---------------------------------------------


def test_the_switch_is_three_real_buttons_that_post_the_form() -> None:
    assert 'method="post" action="/theme" hx-post="/theme" hx-swap="none"' in SWITCH
    assert 'name="csrf_token"' in SWITCH and 'name="next"' in SWITCH
    html = render("login.html", theme="dark", theme_next="/login")
    buttons = BUTTON.findall(html)
    assert [b[0] for b in buttons] == ["light", "dark", "system"]
    assert [b[1] for b in buttons] == ["false", "true", "false"]
    assert '<input type="hidden" name="next" value="/login">' in html
    for glyph in ("sun", "moon", "monitor"):
        assert f'name == "{glyph}"' in ICONS, glyph


def test_the_switch_is_in_the_rail_and_in_the_signed_out_header() -> None:
    assert NAV.count('{% include "_theme.html" %}') == 1
    assert NAV.index("_theme.html") < NAV.index('action="/logout"')
    assert BASE.count('{% include "_theme.html" %}') == 1
    assert '<div class="rv-header-tools">' in BASE


def test_the_page_carries_the_theme_and_the_colour_scheme() -> None:
    default = render("login.html")
    assert '<html lang="en" data-theme="system">' in default
    assert '<meta name="color-scheme" content="light dark">' in default
    dark = render("login.html", theme="dark", color_scheme="dark")
    assert '<html lang="en" data-theme="dark">' in dark
    assert '<meta name="color-scheme" content="dark">' in dark


def test_the_signed_out_header_carries_the_lockup_for_both_themes() -> None:
    html = render("login.html")
    mark = '<img class="rv-mark-img" src="/static/brand/logo-mark-512x512.png"'
    assert html.count(mark) == 2  # the panel and the header
    assert "logo-horizontal" not in html and "logo-stacked" not in html
    # On the surface the wordmark takes the text and link colours of the theme:
    # the rail colours are scoped to the app shell and to the sign-in panel.
    rev = block(".rv-wordmark .rv-wordmark-rev")
    assert rev == {"color": "var(--rv-text)", "background-color": "var(--rv-surface)"}
    rail = block(
        ".rv-app .rv-header .rv-wordmark .rv-wordmark-rev, "
        ".rv-auth-panel .rv-wordmark .rv-wordmark-rev"
    )
    assert rail["color"] == "var(--rv-stone)"
    without = render("login.html", brand_files=frozenset())
    assert "rv-mark" not in without and "rv-wordmark" in without


def test_the_script_applies_the_choice_at_once() -> None:
    assert 'document.documentElement.setAttribute("data-theme", theme);' in SCRIPT
    assert 'meta[name="color-scheme"]' in SCRIPT
    assert 'document.addEventListener("click", applyTheme);' in SCRIPT
    assert '{ light: "light", dark: "dark", system: "light dark" }' in SCRIPT


def test_the_script_restores_the_theme_when_the_post_is_refused() -> None:
    # A refused post (403, 422) or a failed one puts the theme back; the status
    # is read from the request, since the page's response handling marks 403
    # and 422 as answers and htmx then reports them as successful (THE-824).
    assert 'document.addEventListener("htmx:afterRequest", themePosted);' in SCRIPT
    assert 'document.addEventListener("htmx:sendError", themePosted);' in SCRIPT
    assert "var status = detail.xhr ? detail.xhr.status : 0;" in SCRIPT
    assert "status >= 200 && status < 300" in SCRIPT
    assert "setTheme(themeKept);" in SCRIPT
    assert 'form.classList.contains("rv-theme")' in SCRIPT
    handling = re.search(r'name="htmx-config" content=\'(.*?)\'', BASE)
    assert handling is not None
    assert '"code": "(403|404|409|413|422|500)", "swap": true, "error": false' in (
        handling.group(1)
    )


# --- the module ---------------------------------------------------------------------


def test_the_themes_and_their_colour_schemes() -> None:
    assert THEMES == ("light", "dark", "system") and DEFAULT_THEME == "system"
    assert set(COLOR_SCHEMES) == set(THEMES)
    assert COLOR_SCHEMES["system"] == "light dark"
    for value in ("", "DARK", "blue", None, 3, "dark "):
        assert normalise_theme(value) == DEFAULT_THEME, value
    assert normalise_theme("dark") == "dark"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/clients/3", "/clients/3"),
        ("/", "/"),
        ("/settings?saved=1", "/settings?saved=1"),
        ("//evil.example", "/"),
        ("https://evil.example/", "/"),
        ("clients", "/"),
        ("/a\\b", "/"),
        ("/a\nb", "/"),
        ("", "/"),
    ],
)
def test_the_way_back_stays_on_this_site(value: str, expected: str) -> None:
    assert safe_next(value) == expected


# --- the route (PostgreSQL) -----------------------------------------------------


async def theme_in_database(engine: AsyncEngine) -> str:
    async with async_sessionmaker(engine)() as session:
        return (await session.execute(select(AppUser.theme))).scalar_one()


async def test_a_signed_in_user_keeps_the_choice_on_the_user_row(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token = await sign_in(ui_browser, db_engine)
    assert await theme_in_database(db_engine) == "system"
    home = await ui_browser.get("/")
    assert 'data-theme="system"' in home.text
    assert '<input type="hidden" name="next" value="/">' in home.text

    answer = await ui_browser.post(
        "/theme", data={"theme": "dark", "next": "/settings", "csrf_token": token}
    )
    assert answer.status_code == 303
    assert answer.headers["location"] == "/settings"
    assert answer.cookies[THEME_COOKIE] == "dark"
    assert "HttpOnly" in answer.headers["set-cookie"]
    assert await theme_in_database(db_engine) == "dark"
    page = await ui_browser.get("/settings")
    assert 'data-theme="dark"' in page.text
    assert '<meta name="color-scheme" content="dark">' in page.text
    assert 'value="dark" aria-pressed="true"' in page.text

    # htmx gets 204 and nothing to swap; the choice is still written.
    quiet = await ui_browser.post(
        "/theme",
        data={"theme": "light", "next": "/", "csrf_token": token},
        headers={"HX-Request": "true"},
    )
    assert quiet.status_code == 204 and quiet.content == b""
    assert await theme_in_database(db_engine) == "light"

    # The way back stays on this site and a forged value changes nothing.
    away = await ui_browser.post(
        "/theme", data={"theme": "dark", "next": "//x.example", "csrf_token": token}
    )
    assert away.headers["location"] == "/"
    forged = await ui_browser.post(
        "/theme", data={"theme": "blue", "next": "/", "csrf_token": token}
    )
    assert forged.status_code == 422
    assert await theme_in_database(db_engine) == "dark"

    # Without the CSRF token the post is refused and nothing changes (THE-824).
    bare = await ui_browser.post("/theme", data={"theme": "light", "next": "/"})
    assert bare.status_code == 403
    assert THEME_COOKIE not in bare.cookies
    assert await theme_in_database(db_engine) == "dark"

    # The way back keeps the query of the page (a filtered list, a search), and
    # a page drawn in answer to a POST sends the switch back to the home page.
    listed = await ui_browser.get("/clients?q=synthetic&show=all")
    assert (
        '<input type="hidden" name="next" value="/clients?q=synthetic&amp;show=all">'
    ) in listed.text
    answer = await ui_browser.post(
        "/clients", data={"name": "", "csrf_token": token}, follow_redirects=False
    )
    assert answer.status_code in (200, 422)
    assert '<input type="hidden" name="next" value="/">' in answer.text

    # Signed out, the sign-in page keeps the theme from the cookie.
    await ui_browser.post("/logout", data={"csrf_token": token})
    login = await ui_browser.get("/login")
    assert 'data-theme="dark"' in login.text


async def test_signed_out_the_choice_is_kept_in_the_cookie_only(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await create_admin(db_engine)
    token = await get_csrf(ui_browser, "/login")
    answer = await ui_browser.post(
        "/theme", data={"theme": "light", "next": "/login", "csrf_token": token}
    )
    assert answer.status_code == 303
    assert answer.headers["location"] == "/login"
    assert answer.cookies[THEME_COOKIE] == "light"
    assert await theme_in_database(db_engine) == "system"
    login = await ui_browser.get("/login")
    assert 'data-theme="light"' in login.text
    assert '<meta name="color-scheme" content="light">' in login.text
    assert 'value="light" aria-pressed="true"' in login.text
    # A forged cookie is the default, never an error.
    ui_browser.cookies.set(THEME_COOKIE, "blue")
    assert 'data-theme="system"' in (await ui_browser.get("/login")).text
