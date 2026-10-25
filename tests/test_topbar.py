"""The top bar of the page column (docs/design-system.md, The shell, THE-1188).

Every signed-in page opens its column with the breadcrumb of the page and the
search of the clients; a signed-out page has neither. The trail is a pure function
of the page's own context (app/ui/breadcrumbs.py), so the view model tests need no
database. The route tests need PostgreSQL (DATABASE_URL) and are skipped without it.
"""

import re
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.checks.library import load_library
from app.evidence.service import EvidenceContext
from app.ui.auth import templates
from app.ui.brand import BRAND_FILES, STATIC_DIR
from app.ui.breadcrumbs import PLACES, Crumb, breadcrumb_trail
from html_structure import structure_problems
from ui_helpers import NAME, seed_client, sign_in

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app/ui/templates"
TOPBAR = (TEMPLATES / "_topbar.html").read_text(encoding="utf-8")
NAV = (TEMPLATES / "_nav.html").read_text(encoding="utf-8")
BASE = (TEMPLATES / "base.html").read_text(encoding="utf-8")
FOLLOW_UP = (STATIC_DIR / "css/revrook-retest.css").read_text(encoding="utf-8")
SCRIPT = (STATIC_DIR / "js/revrook.js").read_text(encoding="utf-8")
LIBRARY = load_library()
# A placeholder for the CSRF field of a rendered template; not a real token.
PLACEHOLDER_TOKEN = "x" * 32
# A step of the trail that is a link: its address and its words. The chevron in
# front of every step but the first is an icon of the set.
CRUMB_LINK = re.compile(
    r'<li>(?:<svg[^>]*>(?:(?!</svg>).)*</svg>)?<a href="([^"]+)">([^<]+)</a></li>',
    re.S,
)
CURRENT = re.compile(r'<span aria-current="page">([^<]+)</span>')


def topbar_of(html: str) -> str:
    start = html.index('<div class="rv-topbar" id="topbar">')
    return html[start : html.index("</search>", start)]


# --- the trail -------------------------------------------------------------------


def test_the_home_page_is_home_alone_and_never_a_link() -> None:
    assert breadcrumb_trail(nav="home", title="Home") == [Crumb("Home")]


def test_each_place_of_the_rail_is_home_then_the_place() -> None:
    for nav, (text, _) in PLACES.items():
        if nav == "home":
            continue
        expected = [Crumb("Home", ""), Crumb(text)]
        assert breadcrumb_trail(nav=nav, title="Anything") == expected, nav


def test_every_place_of_the_trail_is_a_place_of_the_rail() -> None:
    for text, path in PLACES.values():
        assert f'href="/{path}"' in NAV, path
        assert f'<span class="rv-nav-text">{text}</span>' in NAV, text


def test_a_client_page_names_the_client_and_its_tab() -> None:
    overview = breadcrumb_trail(
        nav="clients", client_id=7, client_name="Acme Ltd", section="overview"
    )
    assert overview == [
        Crumb("Home", ""),
        Crumb("Clients", "clients"),
        Crumb("Acme Ltd"),
    ]
    checklist = breadcrumb_trail(
        nav="clients", client_id=7, client_name="Acme Ltd", section="checklist"
    )
    assert checklist == [
        Crumb("Home", ""),
        Crumb("Clients", "clients"),
        Crumb("Acme Ltd", "clients/7"),
        Crumb("Checklist"),
    ]
    control = breadcrumb_trail(
        nav="clients",
        client_id=7,
        client_name="Acme Ltd",
        section="checklist",
        leaf="PC-ACC-01",
    )
    tab = Crumb("Checklist", "clients/7/checklist")
    assert control[-2:] == [tab, Crumb("PC-ACC-01")]
    exports = breadcrumb_trail(
        nav="clients", client_id=7, client_name="Acme Ltd", section="exports"
    )
    assert exports[-1] == Crumb("Export history")


def test_the_clients_list_and_a_refusal_close_on_their_own_page() -> None:
    clients = [Crumb("Home", ""), Crumb("Clients")]
    assert breadcrumb_trail(nav="clients", title="Clients") == clients
    refusal = [Crumb("Home", ""), Crumb("Page not found")]
    assert breadcrumb_trail(nav="", title="Page not found") == refusal
    assert breadcrumb_trail() == [Crumb("Home")]


def test_only_the_last_step_is_without_a_link() -> None:
    trail = breadcrumb_trail(
        nav="clients", client_id=3, client_name="B", section="reports", leaf="Report"
    )
    linked = [crumb.path is not None for crumb in trail]
    assert linked == [True, True, True, True, False]


# --- the template ----------------------------------------------------------------


def render(name: str, **context: object) -> str:
    return templates.get_template(name).render(
        user=type("User", (), {"username": "admin"})(),
        csrf_token=PLACEHOLDER_TOKEN,
        brand_files=frozenset(BRAND_FILES),
        **context,
    )


def test_a_signed_in_page_opens_its_column_with_the_top_bar() -> None:
    html = render("glossary.html", title="Glossary", nav="glossary")
    assert structure_problems(html) == []
    bar = topbar_of(html)
    assert html.index('<div class="rv-main">') < html.index(bar) < html.index("<main")
    assert '<nav class="rv-breadcrumb" aria-label="Breadcrumb">' in bar
    assert CRUMB_LINK.findall(bar) == [("/", "Home")]
    assert CURRENT.findall(bar) == ["Glossary"]
    # One banner landmark: the rail is the header, the top bar is not.
    assert "<header" not in bar
    # The search: a plain GET form to the clients list in a labelled search
    # landmark (the element, since Pico draws a [role=search] as a joined pill).
    assert '<search class="rv-topbar-search" aria-label="Clients">' in bar
    assert '<form class="rv-topbar-form" method="get" action="/clients">' in bar
    assert 'role="search"' not in bar
    label = '<label for="topbar-q" class="rv-sr-only">Search clients by name</label>'
    assert label in bar
    assert 'id="topbar-q" name="q" type="search"' in bar
    assert 'aria-keyshortcuts="/" aria-describedby="topbar-q-key"' in bar
    assert '<button type="submit" class="rv-button-quiet rv-button-small">' in bar


def test_the_top_bar_draws_a_client_trail_from_the_page_context() -> None:
    html = render(
        "glossary.html",
        title="Checklist - Acme Ltd",
        nav="clients",
        client_id=4,
        client_name="Acme <Ltd>",
        section="checklist",
    )
    bar = topbar_of(html)
    assert CRUMB_LINK.findall(bar) == [
        ("/", "Home"),
        ("/clients", "Clients"),
        ("/clients/4", "Acme &lt;Ltd&gt;"),
    ]
    assert CURRENT.findall(bar) == ["Checklist"]


def test_a_signed_out_page_has_no_top_bar() -> None:
    html = templates.get_template("login.html").render(
        title="Sign in",
        csrf_token=PLACEHOLDER_TOKEN,
        brand_files=frozenset(BRAND_FILES),
        errors=[],
        username="",
    )
    assert 'id="topbar"' not in html and 'id="topbar-q"' not in html
    assert BASE.count('{% include "_topbar.html" %}') == 1


def test_the_top_bar_uses_tokens_scrolls_with_the_page_and_wraps() -> None:
    section = FOLLOW_UP.split("/* ---------- The top bar (_topbar.html", 1)[1]
    # Only the rules of the bar: the next section of the stylesheet starts with
    # the same rule of dashes.
    section = section.split("/* ---------- ", 1)[0]
    assert "border-bottom: 1px solid var(--rv-line);" in section
    assert "background-color: var(--rv-surface);" in section
    # Not sticky: a bar over the page would cover the focus of a field under it.
    assert "position: sticky" not in section and "position: fixed" not in section
    # A long client name wraps; nothing in the trail is cut with an ellipsis.
    assert "flex-wrap: wrap;" in section and "overflow-wrap: anywhere;" in section
    assert "text-overflow" not in section
    assert "@media (min-width: 768px)" in section
    assert "@media (min-width: 1024px)" in section


def test_the_slash_key_focuses_the_search_outside_fields_and_dialogs() -> None:
    assert 'document.addEventListener("keydown", focusSearch);' in SCRIPT
    handler = SCRIPT.split("function focusSearch(event) {", 1)[1]
    handler = handler.split("\n  }\n\n", 1)[0]
    assert 'event.key !== "/"' in handler
    assert "event.ctrlKey || event.metaKey || event.altKey" in handler
    assert "isContentEditable" in handler and "INPUT|TEXTAREA|SELECT" in handler
    assert 'document.querySelector("dialog[open]")' in handler
    assert 'document.getElementById("topbar-q")' in handler
    assert "event.preventDefault();" in handler


# --- the routes ------------------------------------------------------------------


async def test_the_client_pages_carry_their_trail(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    checklist = await ui_browser.get(f"/clients/{client_id}/checklist")
    assert checklist.status_code == 200 and structure_problems(checklist.text) == []
    bar = topbar_of(checklist.text)
    assert CRUMB_LINK.findall(bar) == [
        ("/", "Home"),
        ("/clients", "Clients"),
        (f"/clients/{client_id}", NAME),
    ]
    assert CURRENT.findall(bar) == ["Checklist"]

    control_id = LIBRARY.controls[0].id
    control = await ui_browser.get(f"/clients/{client_id}/controls/{control_id}")
    bar = topbar_of(control.text)
    tab = (f"/clients/{client_id}/checklist", "Checklist")
    assert tab in CRUMB_LINK.findall(bar)
    assert CURRENT.findall(bar) == [control_id]

    home = await ui_browser.get("/")
    assert CURRENT.findall(topbar_of(home.text)) == ["Home"]
    assert CRUMB_LINK.findall(topbar_of(home.text)) == []

    # The search of the top bar is the search of the clients list.
    found = await ui_browser.get("/clients", params={"q": NAME[:9]})
    assert found.status_code == 200 and NAME in found.text
