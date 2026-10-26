"""The markup the rules of the deployed findings rely on, drawn through the application.

The deployed checks of THE-1360 found a faint battlement, a void beyond 1448px, no
marker on a folded rule, a phone checklist of 15753px and an empty column beside the
gauge without a scene. Their rules are in app/static/css/revamp.css and
tests/test_revamp_routes.py reads them; CI has no browser, so these tests check that
the pages still render the elements those rules select, in the place the selectors
expect: a child combinator reads the parent of an element, so each one is checked
here by its parent. The pages need PostgreSQL (DATABASE_URL) and are skipped
without it.
"""

import re
from html.parser import HTMLParser

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.checks.library import load_library
from app.evidence.service import EvidenceContext
from html_structure import structure_problems
from ui_helpers import make_report, seed_client, sign_in

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta"}
VOID |= {"source", "track", "wbr"}
CELLS = (
    '<th scope="row">',
    '<td data-label="Status">',
    '<td data-label="Coverage" class="rv-coverage">',
    '<td data-label="Evidence dated" class="rv-coverage">',
    '<td data-label="Owner">',
    '<td data-label="Why it needs a look">',
)
HIDDEN_STAGE = re.compile(r'<div class="rv-scene" id="rookery-scene"[^>]* hidden>')


class Parents(HTMLParser):
    """The attributes of every element and of the element it stands in."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[dict[str, str]] = []
        self.found: list[tuple[dict[str, str], dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        here = {name: value or "" for name, value in attrs} | {"<tag>": tag}
        self.found.append((here, self.stack[-1] if self.stack else {}))
        if tag not in VOID:
            self.stack.append(here)

    def handle_endtag(self, tag: str) -> None:
        # An end tag closes its element and any left open inside it; a stray one
        # closes nothing
        tags = [item["<tag>"] for item in self.stack]
        if tag in tags:
            del self.stack[len(tags) - 1 - tags[::-1].index(tag) :]


def parents(html: str, name: str, value: str) -> list[str]:
    """The class of the parent of every element whose `name` is `value`.

    For "class" an element matches when `value` is one of its classes.
    """
    parser = Parents()
    parser.feed(html)
    found: list[str] = []
    for here, parent in parser.found:
        given = here.get(name, "")
        if given == value or (name == "class" and value in given.split()):
            found.append(parent.get("class", ""))
    return found


async def test_the_pages_render_what_the_finding_rules_select(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    await make_report(ui_browser, csrf, client_id)
    home = (await ui_browser.get("/")).text
    assert structure_problems(home) == []
    # Beyond 1448px: .rv-app .rv-content, .rv-app .rv-topbar-inner and .rv-app
    # .rv-footer stand in the middle; .rv-content > .rv-page-header is the band
    assert parents(home, "class", "rv-main") == ["rv-app"]
    assert parents(home, "class", "rv-content") == ["rv-main"]
    assert parents(home, "class", "rv-footer") == ["rv-main"]
    assert parents(home, "class", "rv-topbar-inner") == ["rv-topbar"]
    assert parents(home, "class", "rv-page-header") == ["rv-content"]
    # Without a scene: .rv-keep-panel:has(> .rv-scene[data-scene-state=...]) and,
    # without script, the stage stays hidden in the panel
    assert parents(home, "id", "rookery-scene") == ["rv-keep rv-keep-panel"]
    assert HIDDEN_STAGE.search(home) is not None
    # The tabs of a client reach both edges: .rv-content > .rv-tabs-strip
    checklist = (await ui_browser.get(f"/clients/{client_id}/checklist")).text
    assert structure_problems(checklist) == []
    assert parents(checklist, "class", "rv-tabs-strip") == ["rv-content"]
    # The phone checklist: main .rv-checklist tbody tr[data-control], the status
    # without its label, the dates kept whole, the reasons last
    assert parents(checklist, "id", "checklist") == ["rv-content"]
    rows = checklist.split("<tr data-control=")[1:]
    assert len(rows) == len(load_library().controls)
    for row in rows:
        cells = [row.index(cell) for cell in CELLS]
        assert cells == sorted(cells) and cells[-1] < row.index("</tr>")
    # The folded rule: .rv-rule-more[open] > summary::before is its marker
    control = load_library().controls[0].id
    page = (await ui_browser.get(f"/clients/{client_id}/controls/{control}")).text
    assert structure_problems(page) == []
    rule = '<details class="rv-rule-more">\n<summary>The rule as the library writes it'
    assert rule in page
