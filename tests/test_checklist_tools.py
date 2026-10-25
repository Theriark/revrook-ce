"""The tools of the checklist (docs/design-system.md, Checklist; THE-1188).

A search over the name, the id, the domain and the owner of a control, a status
menu and an order, sent as one GET form beside the chips of the filter band. The
view model tests use the worked clients of the report tests and need no database.
The route tests need PostgreSQL (DATABASE_URL) and are skipped without it.
"""

import html as htmlib
import re
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.checks.library import load_library
from app.evidence.service import EvidenceContext
from app.reports.status import LABELS, NOT_APPLICABLE, NOT_PROTECTED
from app.reports.topics import TOPICS
from app.reports.view import ReportView, build_view
from app.ui.auth import templates
from app.ui.brand import BRAND_FILES, STATIC_DIR
from app.ui.viewmodels import (
    CHECKLIST_SORT_KEYS,
    CHECKLIST_SORTS,
    STATUS_RANK,
    ChecklistQuery,
    ChecklistRow,
    checklist_rows,
    read_search,
    search_rows,
    sort_rows,
)
from html_structure import structure_problems
from tools import report_clients
from ui_helpers import ROW, seed_client, sign_in

LIBRARY = load_library()
ROOT = Path(__file__).resolve().parent.parent
CHECKLIST = (ROOT / "app/ui/templates/checklist.html").read_text(encoding="utf-8")
FOLLOW_UP = (STATIC_DIR / "css/revrook-retest.css").read_text(encoding="utf-8")
# A placeholder for the CSRF field of a rendered template; not a real token.
PLACEHOLDER_TOKEN = "x" * 32
TITLE_LINK = re.compile(
    r'<a class="rv-control-link" href="[^"]+" data-drawer>([^<]+)</a>'
)
ROW_STATUS = re.compile(
    r'<tr data-control="[^"]+"[^>]*>.*?<span class="rv-status-([a-z-]+)">', re.S
)


def view_of(name: str) -> ReportView:
    return build_view(
        report_clients.snapshot_bytes(LIBRARY, name),
        LIBRARY,
        report_clients.context_for(name),
        report_clients.previous_bytes(LIBRARY, name),
    )


def rows_of(name: str, owners: dict[str, str] | None = None) -> list[ChecklistRow]:
    return checklist_rows(view_of(name), {}, None, owners or {}, set())


def ids(rows: list[ChecklistRow]) -> list[str]:
    return [item.row.control_id for item in rows]


def holds(item: ChecklistRow, words: str) -> bool:
    texts = (item.row.title, item.row.control_id, item.row.domain_name, item.owner)
    return any(words.casefold() in text.casefold() for text in texts)


# --- the query -------------------------------------------------------------------


def test_the_query_leaves_its_defaults_out_of_the_address() -> None:
    assert ChecklistQuery().params() == ""
    query = ChecklistQuery("flagged", "ID", "not-protected", "mfa", "status")
    everything = "?show=flagged&domain=ID&status=not-protected&q=mfa&sort=status"
    assert query.params() == everything
    every_control = "?domain=ID&status=not-protected&q=mfa&sort=status"
    assert query.params(show="all") == every_control
    assert query.params(domain="", status="") == "?show=flagged&q=mfa&sort=status"
    reset = query.params(q="", status="", sort="library")
    assert reset == "?show=flagged&domain=ID"
    assert ChecklistQuery(q="a b&c").params() == "?q=a+b%26c"


def test_the_query_knows_when_it_was_refined() -> None:
    assert not ChecklistQuery().refined
    assert not ChecklistQuery(show="flagged", domain="ID").refined
    assert ChecklistQuery(q="mfa").refined
    assert ChecklistQuery(status="protected").refined
    assert ChecklistQuery(sort="title").refined
    assert ChecklistQuery(sort="evidence").sort_words == "Evidence, oldest first"
    assert CHECKLIST_SORT_KEYS == ("library", "status", "evidence", "title")


def test_the_words_of_a_search_are_folded_and_capped() -> None:
    assert read_search("  multi   factor ") == "multi factor"
    assert read_search("x" * 300) == "x" * 200
    assert read_search("") == ""


# --- search and order --------------------------------------------------------------


def test_a_search_finds_the_name_the_id_the_domain_and_the_owner() -> None:
    topic = TOPICS[0]
    rows = rows_of("A", {topic.key: "Sam Example"})
    assert search_rows(rows, "") == rows
    first = rows[0]
    by_id = search_rows(rows, first.row.control_id.lower())
    assert ids(by_id) == [first.row.control_id]
    word = first.row.title.split()[0].upper()
    found = search_rows(rows, word)
    assert first in found and all(holds(item, word) for item in found)
    domain = search_rows(rows, first.row.domain_name)
    in_domain = [item for item in rows if item.row.domain_name == first.row.domain_name]
    assert all(item in domain for item in in_domain)
    owned = search_rows(rows, "sam example")
    assert set(ids(owned)) == set(topic.control_ids)
    assert search_rows(rows, "no control has these words") == []


def test_the_library_order_is_the_order_of_the_report() -> None:
    rows = rows_of("B")
    assert sort_rows(rows, "library") == rows
    assert ids(rows) == [row.control_id for row in view_of("B").rows]


def test_the_status_order_puts_the_worst_first_then_gates_then_weight() -> None:
    rows = rows_of("B")
    ordered = sort_rows(rows, "status")
    assert sorted(ids(ordered)) == sorted(ids(rows))
    keys = [
        (STATUS_RANK[item.row.label.key], not item.row.gate, -item.row.weight)
        for item in ordered
    ]
    assert keys == sorted(keys)
    worst = min(STATUS_RANK[item.row.label.key] for item in rows)
    assert STATUS_RANK[ordered[0].row.label.key] == worst
    assert STATUS_RANK[NOT_PROTECTED.key] == 0
    labels = [item.row.label for item in ordered]
    if NOT_APPLICABLE in labels:
        assert set(labels[labels.index(NOT_APPLICABLE) :]) == {NOT_APPLICABLE}
    # Ties keep the library order.
    library = {control_id: index for index, control_id in enumerate(ids(rows))}
    for before, after in zip(ordered, ordered[1:], strict=False):
        same = (
            before.row.label == after.row.label
            and before.row.gate == after.row.gate
            and before.row.weight == after.row.weight
        )
        if same:
            assert library[before.row.control_id] < library[after.row.control_id]


def test_the_evidence_order_puts_the_undated_first_then_the_oldest() -> None:
    ordered = sort_rows(rows_of("C"), "evidence")
    dates = [item.row.evidence_at for item in ordered]
    undated = [day for day in dates if day is None]
    assert dates[: len(undated)] == undated
    dated = [day for day in dates if day is not None]
    assert dated == sorted(dated)


def test_the_name_order_is_by_name_in_any_case() -> None:
    ordered = sort_rows(rows_of("A"), "title")
    titles = [item.row.title.casefold() for item in ordered]
    assert titles == sorted(titles)


# --- the template ----------------------------------------------------------------


def render(query: ChecklistQuery, rows: list[ChecklistRow], narrowed: str = "") -> str:
    return templates.get_template("checklist.html").render(
        title="Checklist - Acme Ltd",
        user=type("User", (), {"username": "admin"})(),
        csrf_token=PLACEHOLDER_TOKEN,
        brand_files=frozenset(BRAND_FILES),
        nav="clients",
        client_id=5,
        client_name="Acme Ltd",
        section="checklist",
        rows=rows,
        total=len(LIBRARY.controls),
        flagged_total=3,
        show=query.show,
        domain=query.domain,
        status=query.status,
        query=query,
        statuses=LABELS,
        sorts=CHECKLIST_SORTS,
        narrowed=narrowed,
        has_earlier=True,
    )


def test_the_tools_are_one_labelled_get_form_with_the_chips() -> None:
    page = render(ChecklistQuery(), rows_of("A"))
    assert structure_problems(page) == []
    # A labelled search landmark: the element, as Pico draws a [role=search] as
    # one joined pill.
    form = (
        '<search aria-label="Checklist">\n'
        '<form class="rv-toolbar rv-checklist-toolbar" id="checklist-tools" '
        'method="get" action="/clients/5/checklist">'
    )
    assert form in page and 'role="search"' not in page
    tools = page[page.index(form) : page.index("</form>", page.index(form))]
    assert '<label for="checklist-q" class="rv-sr-only">' in tools
    assert 'id="checklist-q" name="q" type="search" value=""' in tools
    assert '<label for="checklist-status">Status</label>' in tools
    assert '<option value="" selected>Any status</option>' in tools
    for label in LABELS:
        assert f'<option value="{label.key}">{label.text}</option>' in tools
    assert '<label for="checklist-sort">Order</label>' in tools
    assert '<option value="library" selected>Library order</option>' in tools
    assert '<button type="submit">Show controls</button>' in tools
    # Nothing refined: nothing to reset, and no hidden choice is carried.
    assert ">Reset</a>" not in tools and 'type="hidden"' not in tools
    assert 'id="show-all" class="rv-chip" href="/clients/5/checklist"' in tools
    assert "controls shown. Order: library order." in tools
    headings = page.count('<th scope="row"><a class="rv-control-link"')
    assert headings == len(LIBRARY.controls)
    assert "aria-sort" not in page


def test_a_refined_list_keeps_every_choice_and_offers_a_reset() -> None:
    query = ChecklistQuery("flagged", "ID", "not-protected", "mfa", "title")
    page = render(query, [], narrowed="Identity, not protected")
    assert structure_problems(page) == []
    assert '<input type="hidden" name="show" value="flagged">' in page
    assert '<input type="hidden" name="domain" value="ID">' in page
    assert 'value="mfa"' in page
    assert '<option value="not-protected" selected>Not protected</option>' in page
    assert '<option value="title" selected>Name, A to Z</option>' in page
    reset = 'href="/clients/5/checklist?show=flagged&amp;domain=ID">Reset</a>'
    assert reset in page
    kept = "?domain=ID&amp;status=not-protected&amp;q=mfa&amp;sort=title"
    assert f'id="show-all" class="rv-chip" href="/clients/5/checklist{kept}"' in page
    chip = 'href="/clients/5/checklist?show=flagged&amp;q=mfa&amp;sort=title"'
    assert f'id="show-narrowed" class="rv-chip rv-chip-narrowed" {chip}' in page
    # The empty state names the search, the narrowing and the flagged view.
    assert 'id="checklist-empty"' in page and "No control matches" in page
    text = "No control of identity, not protected that changed or needs a look"
    assert f'{text} has "mfa" in its name, id, domain or owner.' in page
    assert 'Searched for "mfa".' in page and "Order: name, a to z." in page


def test_a_sorted_column_says_so_to_assistive_technology() -> None:
    rows = rows_of("A")
    by_name = render(ChecklistQuery(sort="title"), rows)
    assert 'aria-sort="ascending">Control</th>' in by_name
    by_status = render(ChecklistQuery(sort="status"), rows)
    assert 'aria-sort="other">Status</th>' in by_status
    by_evidence = render(ChecklistQuery(sort="evidence"), rows)
    assert 'aria-sort="ascending">Evidence dated</th>' in by_evidence


def test_the_tools_lay_out_on_the_canvas_band_and_stack_on_a_phone() -> None:
    section = FOLLOW_UP.split("/* ---------- The tools of the checklist", 1)[1]
    assert ".rv-checklist-toolbar {\n  align-items: flex-end;\n}" in section
    assert ".rv-checklist-chips {\n  flex-basis: 100%;\n}" in section
    assert "@media (max-width: 599px)" in section
    assert "#" not in section.split("*/", 1)[1]
    assert 'class="rv-toolbar rv-checklist-toolbar"' in CHECKLIST


# --- the routes ------------------------------------------------------------------


async def test_the_checklist_searches_filters_and_orders_its_rows(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    address = f"/clients/{client_id}/checklist"

    control = LIBRARY.controls[0]
    found = await ui_browser.get(address, params={"q": control.id.lower()})
    assert found.status_code == 200 and structure_problems(found.text) == []
    assert [match[0] for match in ROW.findall(found.text)] == [control.id]
    assert f'Searched for "{control.id.lower()}".' in found.text

    by_name = await ui_browser.get(address, params={"sort": "title"})
    assert by_name.status_code == 200 and structure_problems(by_name.text) == []
    titles = [htmlib.unescape(title) for title in TITLE_LINK.findall(by_name.text)]
    assert len(titles) == len(LIBRARY.controls)
    assert titles == sorted(titles, key=str.casefold)

    worst = await ui_browser.get(address, params={"sort": "status"})
    assert worst.status_code == 200
    ranks = [STATUS_RANK[key] for key in ROW_STATUS.findall(worst.text)]
    assert len(ranks) == len(LIBRARY.controls) and ranks == sorted(ranks)

    narrowed = await ui_browser.get(address, params={"status": "not-checked"})
    assert narrowed.status_code == 200 and structure_problems(narrowed.text) == []
    assert set(ROW_STATUS.findall(narrowed.text)) <= {"not-checked"}
    chosen = '<option value="not-checked" selected>Not checked</option>'
    assert chosen in narrowed.text
    excluded = await ui_browser.get(address, params={"status": "not-applicable"})
    assert excluded.status_code == 200

    nothing = await ui_browser.get(address, params={"q": "zz no such control zz"})
    assert nothing.status_code == 200 and structure_problems(nothing.text) == []
    assert 'id="checklist-empty"' in nothing.text
    assert "No control matches" in nothing.text
    assert '<table id="checklist"' not in nothing.text
    assert f"0 of {len(LIBRARY.controls)} controls shown." in nothing.text

    for query in ({"sort": "blue"}, {"sort": ""}, {"status": "blue"}):
        refused = await ui_browser.get(address, params=query)
        assert refused.status_code == 422, query
