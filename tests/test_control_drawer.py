"""The control drawer of phase 9 (THE-735, REV-196).

The approved plan lists a control drawer among the pages of phase 9; the build on
Development opened every control as a full page. The checklist, the home page and
the client overview now carry a closed native dialog (`_drawer.html`); a control
link marked `data-drawer` opens it with script and htmx, and is the page itself
without them. The server answers the drawer's htmx target with the control without
its shell (`_control_drawer.html`); the control page and the drawer share one body
(`_control_body.html`).

The page tests need PostgreSQL (DATABASE_URL) and are skipped without it.
"""

import re
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.checks.library import load_library
from app.evidence.service import EvidenceContext
from app.ui.clients import DRAWER_TARGET, DRAWER_TEMPLATE
from html_structure import structure_problems
from ui_helpers import seed_client, sign_in

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app/ui/templates"
CSS = (ROOT / "app/static/css/revrook-retest.css").read_text(encoding="utf-8")
SCRIPT = (ROOT / "app/static/js/revrook.js").read_text(encoding="utf-8")
DRAWER = (TEMPLATES / "_drawer.html").read_text(encoding="utf-8")
FRAGMENT = (TEMPLATES / DRAWER_TEMPLATE).read_text(encoding="utf-8")
CONTROL = (TEMPLATES / "control.html").read_text(encoding="utf-8")
HOSTS = ("checklist.html", "home.html", "client_overview.html")
LIBRARY = load_library()
ID = re.compile(r' id="([^"]+)"')
# A link to a control in a host template: the path of an attention item or the
# control of a checklist row.
CONTROL_LINK = re.compile(
    r'<a [^>]*href="/(?:\{\{ item\.path \}\}'
    r'|clients/\{\{ client_id \}\}/controls/[^"]+)"[^>]*>'
)
DRAWER_HEADERS = {"HX-Request": "true", "HX-Target": DRAWER_TARGET}
DIALOG_TAG = '<dialog class="rv-drawer" id="control-drawer" aria-label="Control">'
TITLE_TAG = '<h2 id="control-drawer-title" class="rv-control-title" tabindex="-1">'
INCLUDE_BODY = '{% include "_control_body.html" %}'
INCLUDE_DRAWER = '{% include "_drawer.html" %}'
BODY_DIV = f'<div id="{DRAWER_TARGET}" class="rv-drawer-body"></div>'
UNWANTED = ("eval(", "http", "fetch(", "XMLHttpRequest", "innerHTML")


def ids_of(html: str) -> list[str]:
    return ID.findall(html)


def rule(selector: str) -> str:
    found = re.findall(rf"\n{re.escape(selector)} \{{([^}}]*)\}}", CSS)
    assert found, selector
    return found[-1]


# --- the templates ---------------------------------------------------------------


def test_every_host_page_carries_the_closed_dialog_and_marks_its_links() -> None:
    for name in HOSTS:
        text = (TEMPLATES / name).read_text(encoding="utf-8")
        assert text.count(INCLUDE_DRAWER) == 1, name
        # Every link to a control opens the drawer; no other link does.
        links = CONTROL_LINK.findall(text)
        assert links, name
        assert all("data-drawer" in link for link in links), (name, links)
        assert text.count("data-drawer") == len(links), name


def test_the_dialog_is_native_closed_named_and_closes_without_script() -> None:
    assert DIALOG_TAG in DRAWER
    attributes = DRAWER.split("<dialog", 1)[1].split(">", 1)[0]
    assert " open" not in attributes
    assert '<form method="dialog" class="rv-drawer-close-form">' in DRAWER
    close = 'class="rv-button-quiet rv-button-small rv-drawer-close">Close</button>'
    assert close in DRAWER
    assert BODY_DIV in DRAWER
    assert '<div class="rv-drawer-loading" aria-hidden="true">' in DRAWER
    assert DRAWER.count("rv-skeleton") >= 4


def test_the_page_and_the_drawer_share_one_body_and_the_drawer_leads_on() -> None:
    assert INCLUDE_BODY in CONTROL and INCLUDE_BODY in FRAGMENT
    assert "<html" not in FRAGMENT and "extends" not in FRAGMENT
    assert TITLE_TAG in FRAGMENT
    page_link = 'href="/clients/{{ client_id }}/controls/{{ control.id }}"'
    assert f'{page_link} class="rv-drawer-page-link">Open as a page</a>' in FRAGMENT
    assert '<span class="rv-drawer-client">{{ client_name }}</span>' in FRAGMENT
    # The page keeps its way back; the drawer has none (Close is the way back).
    assert ">Back to the checklist</a>" in CONTROL
    assert "Back to the checklist" not in FRAGMENT


# --- the follow-up stylesheet and the script ---------------------------------------


def test_the_drawer_is_a_sheet_at_the_right_edge_that_fills_a_phone() -> None:
    sheet = rule("dialog.rv-drawer")
    assert "position: fixed;" in sheet and "inset: 0 0 0 auto;" in sheet
    assert "width: 38rem;" in sheet and "max-width: 100%;" in sheet
    assert "height: 100%;" in sheet and "padding: 0;" in sheet
    # Pico makes every dialog a centred flex box at least the whole window
    # (min-width and min-height 100%); seen on Development at 1440px, the sheet
    # filled the window. Both minimums are 0 and the open sheet is a block; the
    # closed state is left to Pico (display none), so no rule shows it.
    assert "min-width: 0;" in sheet and "min-height: 0;" in sheet
    assert "display:" not in sheet
    assert "box-shadow: var(--rv-shadow-2);" in sheet
    opened = rule("dialog.rv-drawer[open]")
    assert "display: block;" in opened
    assert "animation: rv-drawer-in var(--rv-motion);" in opened
    assert "@keyframes rv-drawer-in" in CSS
    veil = rule("dialog.rv-drawer::backdrop")
    assert "background-color: var(--rv-veil);" in veil
    phone = re.search(
        r"@media \(max-width: 767px\) \{\n  dialog\.rv-drawer \{([^}]*)\}", CSS
    )
    assert phone is not None and "width: 100%;" in phone.group(1)
    # One column inside the sheet, whatever the width; the notes do not stick.
    grid = rule(".rv-drawer .rv-control-grid")
    assert "grid-template-columns: minmax(0, 1fr);" in grid
    assert "position: static;" in rule(".rv-drawer .rv-notes-card")
    # The skeleton shows and the body hides while the control loads.
    busy = 'dialog.rv-drawer[aria-busy="true"]'
    assert "display: grid;" in rule(f"{busy} .rv-drawer-loading")
    assert "display: none;" in rule(f"{busy} .rv-drawer-body")
    assert "display: none;" in rule(".rv-drawer-loading")


def test_the_script_opens_loads_focuses_and_falls_back_to_the_page() -> None:
    assert 'var DRAWER_BODY = "control-drawer-body";' in SCRIPT
    assert 'document.getElementById("control-drawer")' in SCRIPT
    # A modified or middle click, no htmx: the link stays a link.
    assert "event.metaKey || event.ctrlKey || event.shiftKey || event.altKey" in SCRIPT
    assert "event.button !== 0" in SCRIPT
    assert "!link || !dialog || !window.htmx || !window.htmx.ajax" in SCRIPT
    assert 'typeof dialog.showModal !== "function"' in SCRIPT
    # Opened as a modal, loaded by htmx into the body, busy while it loads.
    assert "dialog.showModal();" in SCRIPT
    assert 'dialog.setAttribute("aria-busy", "true");' in SCRIPT
    assert 'window.htmx.ajax("GET", link.getAttribute("href"), {' in SCRIPT
    assert 'target: "#" + DRAWER_BODY' in SCRIPT
    # Named by the title, which takes focus; focus returns to the link on close.
    assert 'dialog.setAttribute("aria-labelledby", "control-drawer-title");' in SCRIPT
    assert "title.focus({ preventScroll: true });" in SCRIPT
    assert "drawerOpener.focus();" in SCRIPT
    assert 'dialog.addEventListener("close", drawerClosed);' in SCRIPT
    # Closed, the body is emptied: the next open starts from the skeleton, and a
    # swap never meets the ids of the previous control (seen on Development: the
    # second open logged four content security policy messages from htmx).
    assert "body.replaceChildren();" in SCRIPT
    # A failed request leaves for the page itself; a click on the veil closes.
    assert '"htmx:responseError", drawerFailed' in SCRIPT
    assert '"htmx:sendError", drawerFailed' in SCRIPT
    assert "window.location.assign(link.href);" in SCRIPT
    assert "event.target === dialog" in SCRIPT
    for forbidden in UNWANTED:
        assert forbidden not in SCRIPT, forbidden


# --- the pages -------------------------------------------------------------------


async def test_the_host_pages_render_the_dialog_and_stay_well_formed(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    for path in ("/", f"/clients/{client_id}", f"/clients/{client_id}/checklist"):
        page = await ui_browser.get(path)
        html = page.text
        assert page.status_code == 200, path
        assert structure_problems(html) == [], path
        assert html.count(DIALOG_TAG) == 1, path
        assert "data-drawer" in html, path
        assert ids_of(html).count(DRAWER_TARGET) == 1, path


async def test_the_drawer_gets_the_control_without_its_shell_and_the_page_keeps_it(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    control_id = LIBRARY.controls[0].id
    path = f"/clients/{client_id}/controls/{control_id}"

    drawer = await ui_browser.get(path, headers=DRAWER_HEADERS)
    html = drawer.text
    assert drawer.status_code == 200
    assert drawer.headers["cache-control"] == "no-store, no-transform"
    assert "<html" not in html and "<main" not in html and "<h1" not in html
    assert TITLE_TAG in html
    assert f'href="{path}" class="rv-drawer-page-link">Open as a page</a>' in html
    assert '<section class="rv-verdict" id="control-status"' in html
    assert f'<form id="note-form" method="post" action="{path}/note"' in html
    assert 'id="note-status" class="rv-notes-status" aria-live="polite"' in html
    assert "Back to the checklist" not in html
    found = ids_of(html)
    assert len(found) == len(set(found)), "an id is used twice in the drawer"

    # Only the drawer target gets the fragment: any other htmx request, and a
    # request without htmx, gets the page.
    other = {"HX-Request": "true", "HX-Target": "note-status"}
    for headers in ({}, {"HX-Request": "true"}, other):
        page = await ui_browser.get(path, headers=headers)
        assert page.status_code == 200 and "<html" in page.text, headers
        assert ">Back to the checklist</a>" in page.text, headers
        assert "control-drawer-title" not in page.text, headers
        assert structure_problems(page.text) == [], headers

    # The ids of the drawer never collide with the ids of a page that hosts it.
    for host in ("/", f"/clients/{client_id}", f"/clients/{client_id}/checklist"):
        page = await ui_browser.get(host)
        assert set(found) & set(ids_of(page.text)) == set(), host


async def test_a_control_the_drawer_cannot_show_is_a_short_refusal(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    missing = await ui_browser.get(
        f"/clients/{client_id}/controls/PC-ZZZ-99", headers=DRAWER_HEADERS
    )
    assert missing.status_code == 404
    assert '<div class="rv-errors" role="alert">' in missing.text
    assert "There is no such control." in missing.text
    assert "<html" not in missing.text
    gone = await ui_browser.get(
        f"/clients/{client_id + 1000}/controls/{LIBRARY.controls[0].id}",
        headers=DRAWER_HEADERS,
    )
    assert gone.status_code == 404 and "<html" not in gone.text


async def test_the_drawer_autosaves_a_note_the_page_then_shows(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    control_id = LIBRARY.controls[0].id
    path = f"/clients/{client_id}/controls/{control_id}"
    note = {"did": "Written in the drawer", "recommend": "", "need": "", "by_when": ""}
    saved = await ui_browser.post(
        f"{path}/note",
        data=note,
        headers={"HX-Request": "true", "X-CSRF-Token": csrf},
    )
    assert saved.status_code == 200 and "Saved at" in saved.text
    drawer = await ui_browser.get(path, headers=DRAWER_HEADERS)
    assert "Written in the drawer" in drawer.text
    page = await ui_browser.get(path)
    assert "Written in the drawer" in page.text
