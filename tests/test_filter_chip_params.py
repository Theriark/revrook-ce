"""Hostile values in the query of the clients list (THE-1224, on THE-1061's chips).

A search with quotes, angle brackets and ampersands is shown as text: in the chips,
their data-filter-text, the search box and the empty state. It adds no element, no
event handler and no script, and every link of a chip still points at /clients with
exactly the values the list was asked for: an ampersand in the search never becomes
another parameter. A `show` or `band` that is not one of the known values is refused
(422) without its text in the refusal.

The template tests render clients.html and need no database; one of them renders it
again with autoescaping off to prove the check below fails when the escaping goes.
The page tests need PostgreSQL (DATABASE_URL) and are skipped without it.
"""

from dataclasses import replace
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.evidence.service import EvidenceContext
from app.ui.auth import templates
from app.ui.brand import BRAND_FILES
from app.ui.charts import band_counts
from app.ui.clientlist import (
    BAND_CHOICES,
    FILTER_KEYS,
    FILTERS,
    NO_EVIDENCE,
    ClientCard,
    ListQuery,
    paginate,
    read_query,
)
from app.ui.common import FormError
from html_structure import structure_problems
from ui_helpers import seed_client, sign_in

# A placeholder for the CSRF field of a rendered template; not a real token.
PLACEHOLDER_TOKEN = "x" * 32
SCRIPT = "<script>alert(1)</script>"
IMAGE = "<img src=x onerror=alert(2)>"
# Quotes of both kinds, a tag, an attribute break-out, ampersands written as more
# parameters and a fragment, all in one search.
HOSTILE = f"\"'>{SCRIPT} {IMAGE} Alder & Co&band=strong&show=all#top"
BOGUS = (
    SCRIPT,
    '"><svg onload=alert(3)>',
    "needs-work&band=strong",
    "needs-work'",
    "Strong",
    "none&q=x",
)
LIST_KEYS = {"q", "show", "sort", "order", "density", "page", "band"}


class Parsed(HTMLParser):
    """The tags of a page with their attributes as a browser reads them (the
    parser unescapes attribute values), and the text inside each <script>."""

    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.scripts: list[str] = []
        self._script: list[str] | None = None
        self.feed(html)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, {name: value or "" for name, value in attrs}))
        if tag == "script":
            self._script = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, {name: value or "" for name, value in attrs}))

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script is not None:
            self.scripts.append("".join(self._script))
            self._script = None

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script.append(data)

    def all(self, tag: str, attribute: str = "") -> list[dict[str, str]]:
        return [
            attrs
            for name, attrs in self.tags
            if name == tag and (not attribute or attribute in attrs)
        ]


def injected(html: str) -> list[str]:
    """What the page would run that the templates do not write: an event handler,
    a script without a src (the policy allows none), a javascript: address, or a
    tag of the hostile search."""
    page = Parsed(html)
    found = [f"inline script {text!r}" for text in page.scripts if text.strip()]
    for tag, attrs in page.tags:
        if tag == "script" and "src" not in attrs:
            found.append("script without src")
        for name, value in attrs.items():
            if name.startswith("on"):
                found.append(f"<{tag} {name}>")
            if value.strip().lower().startswith(("javascript:", "data:text/html")):
                found.append(f"<{tag} {name}={value!r}>")
        if tag == "img" and attrs.get("src") == "x":
            found.append("<img src=x>")
    return found


def link_query(href: str) -> dict[str, str]:
    """The parameters of a link to the list; it must be /clients with each known
    parameter at most once and no fragment."""
    parts = urlsplit(href)
    assert (parts.scheme, parts.netloc, parts.path) == ("", "", "/clients"), href
    assert parts.fragment == "" and "#" not in href, href
    values = parse_qs(parts.query, keep_blank_values=True)
    assert set(values) <= LIST_KEYS, href
    assert all(len(items) == 1 for items in values.values()), href
    return {key: items[0] for key, items in values.items()}


def render(query: ListQuery, *, autoescape: bool = True) -> str:
    env = templates.env if autoescape else templates.env.overlay(autoescape=False)
    card = ClientCard(1, "Alder & Co", 0, None, None, None)
    return env.get_template("clients.html").render(
        title="Clients",
        user=type("User", (), {"username": "admin"})(),
        csrf_token=PLACEHOLDER_TOKEN,
        brand_files=frozenset(BRAND_FILES),
        nav="clients",
        rows=[card],
        page=paginate([card], 1),
        query=query,
        filters=[(key, label, 1) for key, label in FILTERS],
        bands=band_counts([card]),
        total=1,
        no_evidence=NO_EVIDENCE,
        errors=[],
        name="",
    )


def hostile_query() -> ListQuery:
    """The hostile search through the parser of the route, with a filter, a band
    and a sort beside it."""
    return read_query(HOSTILE, "needs-work", "score", "asc", "comfortable", "1", "none")


# --- the search, rendered -------------------------------------------------------------


def test_the_hostile_search_reaches_the_list_as_it_was_typed() -> None:
    query = hostile_query()
    # The route only folds the spaces; nothing is stripped or escaped before the
    # template, so the template is what keeps it text.
    assert query.q == " ".join(HOSTILE.split())
    assert SCRIPT in query.q and IMAGE in query.q and "&band=strong" in query.q
    assert [chip.key for chip in query.active_filters] == ["q", "show", "band"]


def test_a_hostile_search_is_text_and_runs_nothing() -> None:
    query = hostile_query()
    html = render(query)
    assert structure_problems(html) == []
    assert injected(html) == []
    assert SCRIPT not in html and IMAGE not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;img src=x onerror=alert(2)&gt;" in html
    page = Parsed(html)
    # The search box, the chip's words and the empty state's words hold the search
    # exactly, as text.
    (box,) = [attrs for attrs in page.all("input") if attrs.get("id") == "q"]
    assert box["value"] == query.q
    chip = page.all("a", "data-filter-chip")[0]
    assert chip["data-filter-text"] == f'Name contains "{query.q}"'
    # The page draws exactly the elements it draws for a harmless search.
    harmless = Parsed(render(replace(query, q="Alder")))
    assert [tag for tag, _ in page.tags] == [tag for tag, _ in harmless.tags]


def test_every_chip_link_keeps_the_hostile_search_as_one_value() -> None:
    query = hostile_query()
    page = Parsed(render(query))
    chips = [link_query(a["href"]) for a in page.all("a", "data-filter-chip")]
    rest = {"sort": "score"}
    assert chips == [
        {"show": "needs-work", "band": "none", **rest},
        {"q": query.q, "band": "none", **rest},
        {"q": query.q, "show": "needs-work", **rest},
    ]
    (clear,) = page.all("a", "data-filter-clear")
    assert link_query(clear["href"]) == rest
    # Every other link to the list (filters, density, bands, sort headings) also
    # carries the search as one value and never a band or show it did not choose.
    for attrs in page.all("a"):
        href = attrs.get("href", "")
        if href.startswith("/clients?"):
            values = link_query(href)
            assert values.get("q", query.q) == query.q, href
            assert values.get("band", "none") in BAND_CHOICES, href
            assert values.get("show", "all") in FILTER_KEYS, href
    # The hidden fields of the toolbar are the known values only.
    hidden = {
        attrs["name"]: attrs["value"]
        for attrs in page.all("input")
        if attrs.get("type") == "hidden" and attrs.get("name") in LIST_KEYS
    }
    assert hidden == {"show": "needs-work", "band": "none", "sort": "score"}


def test_the_checks_fail_when_the_template_stops_escaping() -> None:
    """The same page without autoescaping: the checks above must catch it."""
    query = hostile_query()
    html = render(query, autoescape=False)
    assert SCRIPT in html and IMAGE in html
    found = injected(html)
    assert "<img onerror>" in found and "script without src" in found
    chips = Parsed(html).all("a", "data-filter-chip")
    texts = [a.get("data-filter-text", "") for a in chips]
    assert f'Name contains "{query.q}"' not in texts


# --- unknown show and band values -----------------------------------------------------


@pytest.mark.parametrize("value", BOGUS)
@pytest.mark.parametrize("field", ["show", "band"])
def test_an_unknown_show_or_band_is_refused_without_its_text(
    field: str, value: str
) -> None:
    values = {"show": "all", "band": ""} | {field: value}
    with pytest.raises(FormError) as refused:
        show, band = values["show"], values["band"]
        read_query("", show, "name", "asc", "comfortable", "1", band)
    assert refused.value.status_code == 422
    message = str(refused.value)
    assert value not in message and "<" not in message and '"' not in message


# --- the page (PostgreSQL) ------------------------------------------------------------


async def test_the_list_page_shows_a_hostile_search_as_text(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    await seed_client(db_engine, ui_ctx)
    params = {"q": HOSTILE, "show": "no-report", "band": "none", "sort": "score"}
    response = await ui_browser.get("/clients", params=params)
    html = response.text
    assert response.status_code == 200 and structure_problems(html) == []
    assert injected(html) == []
    assert SCRIPT not in html and IMAGE not in html
    policy = response.headers["content-security-policy"]
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy
    q = " ".join(HOSTILE.split())
    page = Parsed(html)
    chips = [link_query(a["href"]) for a in page.all("a", "data-filter-chip")]
    assert chips == [
        {"show": "no-report", "band": "none", "sort": "score"},
        {"q": q, "band": "none", "sort": "score"},
        {"q": q, "show": "no-report", "sort": "score"},
    ]
    texts = [a["data-filter-text"] for a in page.all("a", "data-filter-chip")]
    assert texts == [f'Name contains "{q}"', "No report yet", "Band: No report yet"]


@pytest.mark.parametrize("field", ["show", "band"])
async def test_the_list_page_refuses_an_unknown_show_or_band(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, field: str
) -> None:
    await sign_in(ui_browser, db_engine)
    for value in BOGUS:
        response = await ui_browser.get("/clients", params={field: value})
        html = response.text
        assert response.status_code == 422, value
        # The refusal does not repeat the value. The page's own address is still
        # in the theme form's hidden `next` field, as an escaped attribute.
        main = html[html.index("<main") : html.index("</main>")]
        assert value not in main, value
        assert injected(html) == [], value
        assert "data-filter-chip" not in html, value
