"""The scenes of the interface (docs/design-system.md, Scenes) and the rail fold.

The rookery skyline of Home and the domain keep of a client overview are drawn by
one shared module from the data attributes of the cards and the bars already on the
page; these tests check what the browser is given (the module, its stylesheet, the
stage macro and the attributes), that the shell links them with the asset version,
that the Evidence Explorer sits in the Evidence group of the navigation, and that
the rail fold is a real form with a cookie behind it. The route tests need
PostgreSQL (DATABASE_URL) and are skipped without it.
"""

import re
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.evidence.service import EvidenceContext
from app.theme import DEFAULT_RAIL, RAIL_COOKIE, RAILS, normalise_rail
from app.ui.auth import templates
from app.ui.brand import ASSET_FILES, BRAND_FILES, STATIC_DIR
from helpers import get_csrf
from html_structure import structure_problems
from ui_helpers import seed_client, sign_in

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app/ui/templates"
SCRIPT = (STATIC_DIR / "js/scenes.js").read_text(encoding="utf-8")
CSS = (STATIC_DIR / "css/scenes.css").read_text(encoding="utf-8")
SHELL_CSS = (STATIC_DIR / "css/revrook-retest.css").read_text(encoding="utf-8")
SHELL_SCRIPT = (STATIC_DIR / "js/revrook.js").read_text(encoding="utf-8")
BASE = (TEMPLATES / "base.html").read_text(encoding="utf-8")
NAV = (TEMPLATES / "_nav.html").read_text(encoding="utf-8")
RAIL = (TEMPLATES / "_rail.html").read_text(encoding="utf-8")
STAGE = (TEMPLATES / "_scene.html").read_text(encoding="utf-8")
HOME = (TEMPLATES / "home.html").read_text(encoding="utf-8")
OVERVIEW = (TEMPLATES / "client_overview.html").read_text(encoding="utf-8")
EXPLORER = (TEMPLATES / "evidence_explorer.html").read_text(encoding="utf-8")
HEX_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b")
ROOK = re.compile(r'<li class="rv-rook[^"]*" data-client="(\d+)" data-name="([^"]*)"')
BLOCK = re.compile(r'<li class="rv-domain" data-code="([A-Z]+)" data-name="([^"]*)"')
# What every fallback of the scene module needs, and what it must never do.
REQUIRED_IN_SCRIPT = (
    '"/static/vendor/three/three.module.js"',
    'getContext("webgl2")',
    "prefers-reduced-motion: reduce",
    "webglcontextlost",
    "webglcontextrestored",
    "visibilitychange",
    "IntersectionObserver",
    "ResizeObserver",
    "pagehide",
    "renderer.dispose()",
    "forceContextLoss()",
    "geometry.dispose()",
    "material.dispose()",
    "root.revrookScene",
    'querySelectorAll("[data-scene]")',
    'setAttribute("role", "application")',
    # The address a node opens is a path of this site or nothing (THE-1053 review).
    "function pathOf(element)",
    r'/^\/(?![/\\])[\x21-\x7e]*$/.test(value)',
    "href: pathOf(element)",
    # A stage with nothing to draw, or a browser without WebGL 2, is put away.
    'setAttribute("data-scene-state", "unavailable")',
    "putAway(every.filter((root) => !hasNodes(root)))",
    # The home view fits the row to the stage; a chosen node leans the yard, never
    # turns it to face the node squarely.
    "function fitDistance()",
    "home.distance = fitDistance();",
    "turnTo(home.yaw + clamp(lean, -TURN_STEP, TURN_STEP));",
)
FORBIDDEN_IN_SCRIPT = (
    "eval(",
    "new Function",
    "innerHTML",
    "document.write",
    "http",
    "fetch(",
    "XMLHttpRequest",
)
# A placeholder for the CSRF field of a rendered template; not a real token.
PLACEHOLDER_TOKEN = "x" * 32


# --- the module, the stylesheet and the macro ------------------------------------


def test_the_shell_links_the_scenes_with_the_asset_version() -> None:
    assert "css/scenes.css" in ASSET_FILES and "js/scenes.js" in ASSET_FILES
    sheet = 'href="/static/css/scenes.css?v={{ asset_version }}">'
    assert sheet in BASE and BASE.index("charts.css") < BASE.index("scenes.css")
    script = '<script type="module" src="/static/js/scenes.js?v={{ asset_version }}">'
    assert script + "</script>" in BASE
    assert BASE.index("charts.js") < BASE.index("scenes.js")


def test_the_scene_module_has_every_fallback_and_nothing_from_outside() -> None:
    for needed in REQUIRED_IN_SCRIPT:
        assert needed in SCRIPT, needed
    for forbidden in FORBIDDEN_IN_SCRIPT:
        assert forbidden not in SCRIPT, forbidden
    # The stages are revealed only once WebGL 2 is known to exist, and the library
    # is imported after that, never before; a page without a scene imports nothing.
    assert SCRIPT.index("supportsWebGL2()") < SCRIPT.index("await import(THREE_URL)")
    assert SCRIPT.index("root.hidden = false") < SCRIPT.index("await import(THREE_URL)")
    assert "if (!supportsWebGL2()) {\n    putAway(every);\n    return;\n  }" in SCRIPT
    # The hide button names the action it offers next and carries no pressed state.
    assert "aria-pressed" not in SCRIPT
    assert '"Hide the scene" : "Show the scene"' in SCRIPT
    # Only footprints: the detail line says what to do, not the hover hint.
    assert "entries.every((entry) => entry.footprint) ? WORDS.footprints" in SCRIPT
    assert "Import an export and its rook rises here." in SCRIPT
    # The yard never turns to face a node squarely, which lined the row up behind it.
    assert "turnTo(Math.atan2(" not in SCRIPT
    # Nothing turns by itself: the only motion answers a person, and is immediate
    # under the reduced-motion setting, also when it changes while the page is open.
    assert "AUTO_TURN" not in SCRIPT
    assert 'motionQuery.addEventListener("change"' in SCRIPT
    assert "built.applyMotion()" in SCRIPT
    # Both readers, both builders, and the page marks the chosen card or bar.
    for name in ("readRookery", "readKeep", "buildRook", "buildBlock"):
        assert f"function {name}(" in SCRIPT, name
    assert 'setAttribute("data-selected"' in SCRIPT
    assert "window.location.assign(node.entry.href)" in SCRIPT


def test_the_scene_stylesheet_draws_with_tokens_only() -> None:
    assert HEX_LITERAL.search(CSS) is None
    assert "url(" not in CSS and "@import" not in CSS
    assert "prefers-reduced-motion: reduce" in CSS
    assert "background-color: var(--rv-charcoal);" in CSS
    assert "aspect-ratio: 21 / 9;" in CSS and "aspect-ratio: 16 / 10;" in CSS
    assert "touch-action: pan-y pinch-zoom;" in CSS
    assert ".rv-scene[hidden] {\n  display: none;\n}" in CSS
    # Where script runs the stage takes its room before the module does, so the
    # page never moves under it; a stage put away stays out of the page.
    reserved = (
        "@media (scripting: enabled) {\n"
        '  .rv-scene[hidden]:not([data-scene-state="unavailable"]) {\n'
        "    display: block;\n"
        "  }\n"
        "}"
    )
    assert reserved in CSS
    # The chosen card or bar carries the mark of the rail, never a colour alone,
    # and the domain row does not move when it is chosen: the line is a
    # pseudo-element in the margin, no padding changes.
    assert '.rv-rook[data-selected="true"]' in CSS
    assert '.rv-domain[data-selected="true"]::before {' in CSS
    chosen = CSS.split('.rv-domain[data-selected="true"]::before {', 1)[1]
    chosen = chosen.split("}", 1)[0]
    assert "position: absolute;" in chosen and "padding" not in chosen
    assert "padding-left: 10px" not in CSS
    assert ".rv-scene.is-closed .rv-scene-toggle {" in CSS
    assert "aria-pressed" not in CSS
    # Every rule that colours text declares its background, as revrook.css does.
    body = re.sub(r"/\*.*?\*/", "", CSS, flags=re.DOTALL)
    for selector, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", body):
        if re.search(r"(^|\s)color:", declarations):
            assert "background-color:" in declarations, selector.strip()


def test_the_stage_macro_is_hidden_until_the_browser_can_draw() -> None:
    assert "{% macro stage(id, kind, for_id, label, hint, lead) -%}" in STAGE
    assert 'data-scene="{{ kind }}" data-scene-for="{{ for_id }}"' in STAGE
    assert 'data-scene-hint="{{ hint }}" hidden>' in STAGE
    assert '<div class="rv-scene-state" role="status">' in STAGE
    assert 'class="rv-scene-detail" id="{{ id }}-detail" aria-live="polite"' in STAGE
    assert "<style" not in STAGE and " style=" not in STAGE
    # The hide button is a plain button whose words say what it offers next.
    assert 'class="rv-button-quiet rv-button-small rv-scene-toggle" hidden>' in STAGE
    assert "aria-pressed" not in STAGE
    for button in ("rv-scene-turn-left", "rv-scene-turn-right", "rv-scene-reset"):
        assert f'class="rv-button-quiet rv-button-small {button}"' in STAGE, button


def test_home_and_the_overview_feed_their_scenes_from_the_page() -> None:
    assert '{{ sc.stage("rookery-scene", "rookery", "rookery-list",' in HOME
    assert '<ul class="rv-rookery" id="rookery-list">' in HOME
    for attribute in (
        'data-client="{{ client.client_id }}"',
        'data-score="{{ client.score_share }}"',
        'data-band="{{ client.band }}"',
        "data-insufficient=",
        'data-evidence="{{ client.evidence }}"',
        'data-needs-work="{{ client.needs_work }}"',
        'data-href="/clients/{{ client.client_id }}"',
    ):
        assert attribute in HOME, attribute
    assert HOME.index("rookery-scene") < HOME.index('id="rookery-list"')
    assert '{{ sc.stage("keep-scene", "keep", "domains-list",' in OVERVIEW
    assert '<ul class="rv-domains" id="domains-list">' in OVERVIEW
    for attribute in (
        'data-code="{{ bar.code }}"',
        'data-weight="{{ bar.weight }}"',
        'data-score="{{ bar.score_text }}"',
        'data-count-{{ label.key }}="{{ count }}"',
        'data-href="/clients/{{ client_id }}/checklist?domain={{ bar.code }}"',
    ):
        assert attribute in OVERVIEW, attribute
    # Home keeps the rings and the overview its bars: the scene adds, never replaces.
    assert '<svg class="rv-ring"' in HOME and '<svg class="rv-bar"' in OVERVIEW


# --- the navigation and the explorer -----------------------------------------------


def test_the_explorer_is_an_evidence_page_and_no_longer_an_experiment() -> None:
    groups = re.findall(r'<p class="rv-nav-group-label">([^<]+)</p>', NAV)
    assert groups == ["Work", "Evidence", "Administration"]
    evidence = NAV.split("Evidence</p>", 1)[1].split("Administration</p>", 1)[0]
    assert "Evidence integrity" in evidence and "Evidence Explorer" in evidence
    assert evidence.index("Evidence integrity") < evidence.index("Evidence Explorer")
    assert "Development-only" not in EXPLORER and "preview on this" not in EXPLORER
    assert "What this view is" in EXPLORER


# --- the rail fold -----------------------------------------------------------------


def test_the_rail_states_and_their_default() -> None:
    assert RAILS == ("expanded", "compact") and DEFAULT_RAIL == "expanded"
    assert RAIL_COOKIE == "rv_rail"
    for value in ("compact", "expanded"):
        assert normalise_rail(value) == value
    for value in (None, "", "wide", 3, "COMPACT"):
        assert normalise_rail(value) == "expanded", value


def test_the_rail_fold_is_a_real_form_in_the_rail() -> None:
    assert 'method="post" action="/rail" hx-post="/rail" hx-swap="none"' in RAIL
    assert 'name="csrf_token"' in RAIL and 'name="next"' in RAIL
    assert 'class="rv-rail-toggle" name="rail"' in RAIL
    assert 'aria-controls="rail"' in RAIL and 'i.icon("chevron-right", "sm")' in RAIL
    assert NAV.count('{% include "_rail.html" %}') == 1
    assert NAV.index("_rail.html") < NAV.index('<div class="rv-nav-strip">')
    assert '<header class="rv-header" id="rail">' in BASE
    assert '<body class="rv-app" data-rail="{{ rail|default(' in BASE
    html = templates.get_template("glossary.html").render(
        title="Glossary",
        user=type("User", (), {"username": "admin"})(),
        csrf_token=PLACEHOLDER_TOKEN,
        brand_files=frozenset(BRAND_FILES),
        nav="glossary",
        rail="compact",
        theme_next="/glossary",
    )
    assert structure_problems(html) == []
    assert '<body class="rv-app" data-rail="compact">' in html
    assert 'name="rail" value="expanded" aria-expanded="false"' in html
    assert 'aria-label="Open the rail"' in html
    assert '<input type="hidden" name="next" value="/glossary">' in html
    # Folded, each icon carries its words as a tooltip; open, the words are beside
    # the icon and no link carries a title.
    for word in (
        "Home",
        "Clients",
        "Profile editor",
        "Evidence integrity",
        "Evidence Explorer",
        "Settings",
        "System",
        "Glossary",
    ):
        assert f' title="{word}">' in html, word
    assert 'aria-current="page" title="Glossary">' in html
    assert '<button type="submit" class="rv-button-quiet" title="Sign out">' in html
    open_rail = templates.get_template("glossary.html").render(
        title="Glossary",
        user=type("User", (), {"username": "admin"})(),
        csrf_token=PLACEHOLDER_TOKEN,
        brand_files=frozenset(BRAND_FILES),
        nav="glossary",
    )
    assert '<body class="rv-app" data-rail="expanded">' in open_rail
    assert 'name="rail" value="compact" aria-expanded="true"' in open_rail
    assert 'class="rv-nav-link" href="/glossary" aria-current="page">' in open_rail
    assert ' title="Home">' not in open_rail and ' title="Sign out">' not in open_rail


def test_the_rail_folds_to_its_icons_from_the_sidebar_width_only() -> None:
    assert "\n.rv-rail-form {\n  display: none;\n  margin: 0;\n}\n" in SHELL_CSS
    fold = SHELL_CSS.split("/* ---------- The rail fold (_rail.html) ----------", 1)[1]
    assert fold.startswith(" */") and "@media (min-width: 1024px) {" in fold
    assert 'body.rv-app[data-rail="compact"]' in fold
    assert "grid-template-columns: 72px minmax(0, 1fr);" in fold
    # The words of the links and the user stay in the page for assistive
    # technology: hidden the way the sr-only heading is, never display none.
    start = fold.index('body[data-rail="compact"] .rv-nav-text,')
    hidden = re.search(r"\{([^}]*)\}", fold[start:])
    assert hidden is not None and "clip: rect(0 0 0 0);" in hidden.group(1)
    assert "display: none" not in hidden.group(1)
    # Folded, the theme switch shows its icons again, stacked.
    assert 'body[data-rail="compact"] .rv-theme .rv-icon {\n    display: block;' in fold


def test_the_shell_script_folds_the_rail_at_once_and_restores_it_when_refused() -> None:
    assert 'document.body.setAttribute("data-rail", rail);' in SHELL_SCRIPT
    assert 'document.addEventListener("click", applyRail);' in SHELL_SCRIPT
    assert 'document.addEventListener("htmx:afterRequest", railPosted);' in SHELL_SCRIPT
    assert 'document.addEventListener("htmx:sendError", railPosted);' in SHELL_SCRIPT
    assert '{ expanded: "Fold the rail", compact: "Open the rail" }' in SHELL_SCRIPT
    # Folded with script, the links and the sign-out button get their tooltips at
    # once, and lose them when the rail opens again.
    assert "function setRailTitles(rail)" in SHELL_SCRIPT
    assert "setRailTitles(rail);" in SHELL_SCRIPT
    assert 'named[k].setAttribute("title", text.textContent.trim());' in SHELL_SCRIPT
    assert 'named[k].removeAttribute("title");' in SHELL_SCRIPT


# --- the routes (PostgreSQL) --------------------------------------------------------


async def test_the_pages_carry_their_scenes_and_the_rail_state(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    token = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    home = await ui_browser.get("/")
    html = home.text
    assert home.status_code == 200 and structure_problems(html) == []
    assert '<body class="rv-app" data-rail="expanded">' in html
    assert 'data-scene="rookery" data-scene-for="rookery-list"' in html
    rooks = ROOK.findall(html)
    assert [int(found) for found, _ in rooks] == [client_id]
    assert 'data-insufficient="' in html and 'data-needs-work="' in html
    # The attributes say what the ring says: the same share and the same band.
    rook = re.search(
        r'<li class="rv-rook[^>]*data-score="(\d+)"[^>]*data-band="([^"]+)"', html
    )
    assert rook is not None
    ring = re.search(
        r'<title id="ring-\d+-title">[^<]*?(score [\d.]+, ([^<]+)|insufficient)',
        html,
    )
    assert ring is not None
    if ring.group(2):
        assert rook.group(2) == ring.group(2)

    overview = await ui_browser.get(f"/clients/{client_id}")
    page = overview.text
    assert overview.status_code == 200 and structure_problems(page) == []
    assert 'data-scene="keep" data-scene-for="domains-list"' in page
    blocks = BLOCK.findall(page)
    assert len(blocks) == page.count('class="rv-domain"') > 0
    for code, _ in blocks:
        assert f'data-href="/clients/{client_id}/checklist?domain={code}"' in page
    assert 'data-count-protected="' in page and 'data-count-not-checked="' in page

    # The fold is remembered in the cookie and drawn on the next page.
    answer = await ui_browser.post(
        "/rail", data={"rail": "compact", "next": "/glossary", "csrf_token": token}
    )
    assert answer.status_code == 303 and answer.headers["location"] == "/glossary"
    assert answer.cookies[RAIL_COOKIE] == "compact"
    assert "HttpOnly" in answer.headers["set-cookie"]
    folded = await ui_browser.get("/glossary")
    assert '<body class="rv-app" data-rail="compact">' in folded.text
    assert 'aria-label="Open the rail"' in folded.text
    quiet = await ui_browser.post(
        "/rail",
        data={"rail": "expanded", "next": "/", "csrf_token": token},
        headers={"HX-Request": "true"},
    )
    assert quiet.status_code == 204 and quiet.cookies[RAIL_COOKIE] == "expanded"
    forged = await ui_browser.post(
        "/rail", data={"rail": "wide", "next": "/", "csrf_token": token}
    )
    assert forged.status_code == 422
    bare = await ui_browser.post("/rail", data={"rail": "compact", "next": "/"})
    assert bare.status_code == 403 and RAIL_COOKIE not in bare.cookies
    back = await ui_browser.get("/")
    assert '<body class="rv-app" data-rail="expanded">' in back.text


async def test_signed_out_the_rail_post_sets_the_cookie_and_goes_to_sign_in(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await sign_in(ui_browser, db_engine)
    token = await get_csrf(ui_browser, "/")
    await ui_browser.post("/logout", data={"csrf_token": token})
    token = await get_csrf(ui_browser, "/login")
    answer = await ui_browser.post(
        "/rail", data={"rail": "compact", "next": "/", "csrf_token": token}
    )
    assert answer.status_code == 303 and answer.headers["location"] == "/login"
    assert answer.cookies[RAIL_COOKIE] == "compact"
    # A forged cookie is read as the open rail.
    ui_browser.cookies.set(RAIL_COOKIE, "wide")
    login = await ui_browser.get("/login")
    assert login.status_code == 200 and "data-rail" not in login.text


@pytest.mark.parametrize(
    ("path", "media_type"),
    [
        ("/static/js/scenes.js", "javascript"),
        ("/static/css/scenes.css", "text/css"),
    ],
)
async def test_the_scene_files_are_served_under_the_strict_policy(
    client: httpx.AsyncClient, path: str, media_type: str
) -> None:
    response = await client.get(path)
    assert response.status_code == 200
    assert media_type in response.headers["content-type"]
    policy = response.headers["content-security-policy"]
    assert "default-src 'self'" in policy
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy
