"""Phase 9 part 2 (THE-320): page structure, summary wording and the review notes.

D-1 the structure of every page and report (tests/html_structure.py), D-2 singular
and plural words in the summary, N-1 invisible characters in names, N-2 line breaks
counted as the browser counts them, N-3 a snapshot of one client under another, N-4
an autosave refusal shown in the status line, O-8 a double submit of a snapshot.

The tests that need PostgreSQL (DATABASE_URL) are skipped without it.
"""

import json
import re
from dataclasses import replace
from datetime import timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.checks.library import load_library
from app.drafts import DraftError, check_text, load_draft
from app.evidence.service import EvidenceContext
from app.models import Client, ExceptionRecord, ReportExport, Snapshot
from app.reports.completeness import MAX_TEXT
from app.reports.render import KINDS, render_report
from app.reports.view import Finding, ReportView, _movement, _plural, build_view
from app.textcheck import control_character, normalise_breaks
from app.ui.auth import templates
from app.ui.brand import BRAND_FILES
from helpers import NOW, FakeClock, create_test_client
from html_structure import structure_problems
from tools import report_clients
from ui_helpers import (
    NAME,
    exported_id,
    make_report,
    page_routes,
    post_export,
    sample_path,
    seed_client,
    sign_in,
    title_of,
)

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "app" / "ui" / "templates"
LIBRARY = load_library()
CONTROL = "PC-ACC-01"
HOSTILE = '<b id="main">"Alder" & Finch</b><h1>x</h1><img src="/x.png">'
RAW_MARKUP = '<b id="main">'
# Pages of earlier phases that a signed-in person opens; the phase 9 pages are read
# from the application (tests/ui_helpers.py page_routes).
EARLIER_PAGES = ("/", "/evidence/integrity", "/imports/profile-editor")
REPORT_PATHS = ("/preview/", "/download")
# 2000 characters when a line break is LF, as the browser counts for maxlength, and
# 2666 when the form sends each break as CRLF.
LONG_NOTE = "ab\r\n" * 666 + "ab"
# The stylesheet link carries the asset version (?v=<digest>), see app/ui/brand.py.
STYLESHEET_LINK = 'href="/static/css/revrook.css?v='
# A placeholder for the CSRF field of a rendered template; not a real token.
PLACEHOLDER_TOKEN = "x" * 32


def view_of(name: str = "A", **context_changes: Any) -> ReportView:
    context = replace(report_clients.context_for(name), **context_changes)
    return build_view(
        report_clients.snapshot_bytes(LIBRARY, name),
        LIBRARY,
        context,
        report_clients.previous_bytes(LIBRARY, name),
    )


async def count(engine: AsyncEngine, model: type) -> int:
    async with async_sessionmaker(engine)() as session:
        query = select(func.count()).select_from(model)
        return int((await session.execute(query)).scalar_one())


def htmx_headers(csrf: str) -> dict[str, str]:
    return {"HX-Request": "true", "X-CSRF-Token": csrf}


# --- D-1: the structure check itself ------------------------------------------------


def test_the_structure_check_finds_what_it_looks_for() -> None:
    bad = (
        "<!doctype html><html><body><h1>a</h1><h1>b</h1>"
        '<p><div id="x"></div></p><span id="x"></span><img src="/a.png">'
        '<input name="q"><label for="nope">L</label><em></strong>'
        '<form hx-target="#gone"></form></body></html>'
    )
    found = "\n".join(structure_problems(bad))
    for expected in (
        "<html> has no lang",
        "2 <h1> elements",
        "0 <main> elements",
        "<div> inside <p>",
        "the id 'x' is used twice",
        "has no alt",
        "<input name='q'> has no label",
        "<label for='nope'> names no element",
        "</strong> closes nothing that is open",
        "</body> closes <em>",
        "hx-target='gone' names no element",
    ):
        assert expected in found, expected
    assert "left open: ['div']" in "\n".join(structure_problems("<div>"))


def test_a_well_formed_page_has_no_problem() -> None:
    good = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"></head><body>'
        '<main><h1>Title</h1><label for="q">Query</label><input id="q" name="q">'
        '<label><input type="checkbox" name="c"> Choose</label>'
        '<input type="hidden" name="t"><img src="/a.png" alt=""><br>'
        '<svg><rect width="1" height="1"/></svg></main></body></html>'
    )
    assert structure_problems(good) == []


# --- D-1: the reports, with the worked clients and with hostile text ---------------


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("name", sorted(report_clients.NAMES))
def test_every_report_is_well_formed(kind: str, name: str) -> None:
    text = render_report(kind, view_of(name)).decode("utf-8")
    assert structure_problems(text) == []


@pytest.mark.parametrize("kind", KINDS)
def test_a_report_with_hostile_text_is_well_formed(kind: str) -> None:
    view = view_of(
        "B",
        msp_name=HOSTILE,
        client_name=HOSTILE,
        prepared_by=HOSTILE,
        next_quarter_plan=(HOSTILE, HOSTILE),
        findings={CONTROL: Finding(HOSTILE, HOSTILE, HOSTILE, HOSTILE)},
        topic_owners={"mfa": HOSTILE},
    )
    text = render_report(kind, view).decode("utf-8")
    assert structure_problems(text) == []
    assert RAW_MARKUP not in text and "&lt;b id=" in text


# --- D-1: the page templates and the brand shell ------------------------------------


@pytest.mark.parametrize("name", ["login.html", "setup.html"])
@pytest.mark.parametrize("value", ["", HOSTILE])
def test_the_public_pages_are_well_formed(name: str, value: str) -> None:
    text = templates.get_template(name).render(
        title="Sign in",
        errors=[value] if value else [],
        username=value,
        csrf_token=PLACEHOLDER_TOKEN,
        brand_files=frozenset(BRAND_FILES),
    )
    assert structure_problems(text) == []
    assert RAW_MARKUP not in text


def test_every_page_template_uses_the_brand_shell() -> None:
    for path in sorted(TEMPLATE_DIR.glob("*.html")):
        if path.name.startswith("_") or path.name == "base.html":
            continue
        source = path.read_text(encoding="utf-8")
        assert source.startswith('{% extends "base.html" %}'), path.name


async def test_every_page_is_well_formed_with_normal_and_hostile_data(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    checked: list[str] = []
    for name in (NAME, HOSTILE):
        client_id = await seed_client(db_engine, ui_ctx, name)
        headers = htmx_headers(csrf)
        note = await ui_browser.post(
            f"/clients/{client_id}/controls/{CONTROL}/note",
            data={"did": name, "recommend": name, "need": name, "by_when": name},
            headers=headers,
        )
        assert note.status_code == 200, note.text
        details = await ui_browser.post(
            f"/clients/{client_id}/reports/details",
            data={"plan": f"{name}\n{name}", "prepared_by": name, "owner-mfa": name},
            headers=headers,
        )
        assert details.status_code == 200, details.text
        added = await ui_browser.post(
            f"/clients/{client_id}/exceptions",
            data={
                "csrf_token": csrf,
                "control_id": CONTROL,
                "owner": name,
                "reason": name,
                "review_date": (NOW.date() + timedelta(days=90)).isoformat(),
            },
        )
        assert added.status_code == 303, added.text
        report = await make_report(ui_browser, csrf, client_id)
        if name == HOSTILE:
            saved = await ui_browser.post(
                "/settings", data={"csrf_token": csrf, "msp_name": HOSTILE}
            )
            assert saved.status_code == 303
        exported = await post_export(ui_browser, csrf, report, "qbr")
        assert exported.status_code == 303, exported.text
        values = {
            "client_id": str(client_id),
            "snapshot_id": report.rsplit("/", 1)[1],
            "export_id": str(exported_id(exported)),
            "control_id": CONTROL,
        }
        paths: list[str] = list(EARLIER_PAGES)
        for template in page_routes("GET"):
            kinds = KINDS if "{kind}" in template else ("",)
            for kind in kinds:
                paths.append(sample_path(template, {**values, "kind": kind}))
        paths.append(f"/clients/{client_id + 100000}")  # the problem page, a 404
        for path in paths:
            answer = await ui_browser.get(path)
            expected = 404 if path.endswith(str(client_id + 100000)) else 200
            assert answer.status_code == expected, path
            problems = structure_problems(answer.text)
            assert problems == [], f"{path}: {problems}"
            assert RAW_MARKUP not in answer.text, path
            if not any(part in path for part in REPORT_PATHS):
                assert title_of(answer.text).endswith(" - revrook"), path
                assert STYLESHEET_LINK in answer.text, path
            checked.append(path)
    assert len(checked) >= 2 * (len(page_routes("GET")) + len(EARLIER_PAGES))


# --- D-2: singular and plural in the summary ----------------------------------------


def test_the_summary_says_one_point_and_one_control_in_the_singular() -> None:
    a = view_of("A").summary_lines
    assert a[1] == (
        "Since the report of 2026-07-17 the score rose by 40.5 points and the "
        "evidence coverage fell by 1 point."
    )
    assert a[2] == (
        "Of 50 controls, 42 are Protected, 7 need attention, 0 are not protected "
        "and 1 was not checked."
    )
    c = view_of("C").summary_lines
    assert c[1] == (
        "Since the report of 2026-07-17 the score fell by 40.5 points and the "
        "evidence coverage rose by 1 point."
    )
    assert c[2] == (
        "Of 51 controls, 43 are Protected, 7 need attention, 1 is not protected "
        "and 0 were not checked."
    )
    b = view_of("B").summary_lines
    assert b[2] == (
        "Of 51 controls, 17 are Protected, 11 need attention, 11 are not protected "
        "and 12 were not checked."
    )
    for lines in (a, b, c):
        assert not re.search(r"\b1 (are|were|need|points)\b", " ".join(lines))
        assert "+" not in " ".join(lines[1:])


@pytest.mark.parametrize(
    ("value", "places", "expected"),
    [
        (Fraction(0), 1, "the score did not change"),
        (Fraction(1, 100), 1, "the score did not change"),
        (Fraction(1), 0, "the score rose by 1 point"),
        (Fraction(-1), 0, "the score fell by 1 point"),
        (Fraction(2), 0, "the score rose by 2 points"),
        (Fraction(-5, 2), 1, "the score fell by 2.5 points"),
        (Fraction(1), 1, "the score rose by 1.0 points"),
    ],
)
def test_a_movement_is_told_in_words(
    value: Fraction, places: int, expected: str
) -> None:
    assert _movement("the score", value, places) == expected


def test_a_count_takes_the_word_that_fits_it() -> None:
    assert _plural(1, "needs", "need") == "1 needs"
    assert _plural(0, "needs", "need") == "0 need"
    assert _plural(2, "is", "are") == "2 are"


# --- N-1: invisible and reordering characters in names ------------------------------


# Bidi override, zero-width space, byte order mark, line and paragraph separator,
# written with chr() so that no editor or transport can change them.
INVISIBLE = [chr(0x202E), chr(0x200B), chr(0xFEFF), chr(0x2028), chr(0x2029)]


@pytest.mark.parametrize("character", INVISIBLE)
def test_a_name_may_not_hold_an_invisible_or_reordering_character(
    character: str,
) -> None:
    assert control_character(f"Alder{character}Finch") == character


@pytest.mark.parametrize("character", INVISIBLE[:3])
def test_a_note_may_not_hold_one_either_phase_10_carry_over_o_5(
    character: str,
) -> None:
    # The bidi override, the zero-width space and the byte order mark are refused in
    # every text that can reach a report, notes and owners included.
    assert control_character(f"Alder{character}Finch", allow_breaks=True) == character


@pytest.mark.parametrize("character", INVISIBLE[3:])
def test_a_note_keeps_the_line_and_paragraph_separators(character: str) -> None:
    assert control_character(f"Alder{character}Finch", allow_breaks=True) is None


async def test_a_client_named_with_a_bidi_override_is_refused(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    refused = await ui_browser.post(
        "/clients", data={"csrf_token": csrf, "name": "Alder" + chr(0x202E) + "Finch"}
    )
    assert refused.status_code == 422 and "U+202E" in refused.text
    msp = await ui_browser.post(
        "/settings",
        data={"csrf_token": csrf, "msp_name": "Zero" + chr(0x200B) + "Width"},
    )
    assert msp.status_code == 422
    assert await count(db_engine, Client) == 0


# --- N-2: line breaks counted as the browser counts them ----------------------------


def test_line_breaks_are_counted_as_the_browser_counts_them() -> None:
    assert normalise_breaks("a\r\nb\rc\n") == "a\nb\nc\n"
    assert MAX_TEXT == 2000
    assert len(LONG_NOTE) > MAX_TEXT
    saved = check_text("What we did", LONG_NOTE, MAX_TEXT)
    assert len(saved) == MAX_TEXT and "\r" not in saved
    with pytest.raises(DraftError, match="longer than 2000"):
        check_text("What we did", LONG_NOTE + "x", MAX_TEXT)
    # The four note fields live in the body the control page and the drawer share.
    control = (TEMPLATE_DIR / "_control_body.html").read_text(encoding="utf-8")
    assert control.count(f'maxlength="{MAX_TEXT}"') == 4


async def test_a_note_sent_with_crlf_breaks_is_saved_at_the_limit(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await create_test_client(db_engine, ui_ctx, NAME)
    note = await ui_browser.post(
        f"/clients/{client_id}/controls/{CONTROL}/note",
        data={"did": LONG_NOTE},
        headers=htmx_headers(csrf),
    )
    assert note.status_code == 200 and "Saved at" in note.text
    async with async_sessionmaker(db_engine)() as session:
        draft = await load_draft(session, client_id)
    assert draft.findings[CONTROL].did == normalise_breaks(LONG_NOTE)
    added = await ui_browser.post(
        f"/clients/{client_id}/exceptions",
        data={
            "csrf_token": csrf,
            "control_id": CONTROL,
            "owner": "Office manager",
            "reason": LONG_NOTE,
            "compensating_control": LONG_NOTE,
            "review_date": (NOW.date() + timedelta(days=90)).isoformat(),
        },
    )
    assert added.status_code == 303, added.text
    async with async_sessionmaker(db_engine)() as session:
        reason = (await session.execute(select(ExceptionRecord.reason))).scalar_one()
    assert len(reason) == MAX_TEXT and "\r" not in reason


# --- N-3: a snapshot of one client under another client -----------------------------


async def test_a_snapshot_of_one_client_is_a_404_under_another(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    mine = await seed_client(db_engine, ui_ctx)
    other = await seed_client(db_engine, ui_ctx, "Other Client Ltd")
    report = await make_report(ui_browser, csrf, mine)
    snapshot_id = report.rsplit("/", 1)[1]
    assert (await ui_browser.get(report)).status_code == 200
    stolen = f"/clients/{other}/reports/{snapshot_id}"
    for path in (stolen, f"{stolen}/preview/qbr", f"{stolen}/preview/insurance"):
        answer = await ui_browser.get(path)
        assert answer.status_code == 404, path
        assert NAME not in answer.text, path
    exported = await post_export(ui_browser, csrf, stolen, "qbr")
    assert exported.status_code == 404
    assert NAME not in exported.text
    assert await count(db_engine, ReportExport) == 0


# --- N-4: an autosave that is refused says so in its status line --------------------


def htmx_rule(config: dict[str, Any], status: int) -> dict[str, Any]:
    """The first response rule htmx applies to a status (it tests each code as a
    regular expression against the status, in order)."""
    for rule in config["responseHandling"]:
        if re.search(rule["code"], str(status)):
            found: dict[str, Any] = rule
            return found
    raise AssertionError(f"no rule for {status}")


def test_the_autosave_forms_swap_a_refusal_into_their_status_line() -> None:
    base = (TEMPLATE_DIR / "base.html").read_text(encoding="utf-8")
    meta = re.search(r"<meta name=\"htmx-config\" content='([^']*)'>", base)
    assert meta is not None
    config = json.loads(meta.group(1))
    for status in (403, 404, 409, 413, 422, 500):
        rule = htmx_rule(config, status)
        assert rule["swap"] is True and rule["error"] is False, status
    assert htmx_rule(config, 200)["swap"] is True
    assert htmx_rule(config, 204)["swap"] is False
    assert htmx_rule(config, 401)["swap"] is False
    for name, target in (
        ("_control_body.html", "note-status"),
        ("reports.html", "details-status"),
    ):
        source = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
        assert f'hx-target="#{target}" hx-swap="innerHTML"' in source, name
        assert re.search(rf'<div id="{target}" [^>]*aria-live="polite"', source), name


async def test_an_autosave_for_a_deleted_client_says_nothing_was_saved(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await create_test_client(db_engine, ui_ctx, "Vanishing Ltd")
    async with async_sessionmaker(db_engine)() as session, session.begin():
        await session.execute(delete(Client).where(Client.id == client_id))
    for path, fields in (
        (f"/clients/{client_id}/controls/{CONTROL}/note", {"did": "Typed text"}),
        (f"/clients/{client_id}/reports/details", {"plan": "Typed text"}),
    ):
        answer = await ui_browser.post(path, data=fields, headers=htmx_headers(csrf))
        assert answer.status_code == 404, path
        assert 'class="rv-errors" role="alert"' in answer.text
        assert "Nothing was saved" in answer.text
        assert "saved as you type" not in answer.text
    missing = await ui_browser.get("/no-such-page", headers={"HX-Request": "true"})
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("text/html")
    assert "no longer exists" in missing.text
    # Asked for as a page, the same address is the problem page (THE-505).
    plain = await ui_browser.get("/no-such-page")
    assert plain.status_code == 404
    assert plain.headers["content-type"].startswith("text/html")
    assert 'class="rv-problem"' in plain.text


# --- O-8: a double submit of the snapshot form makes one snapshot --------------------


async def test_a_double_submit_of_the_snapshot_form_makes_one_snapshot(
    ui_browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ui_ctx: EvidenceContext,
    clock: FakeClock,
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    first = await make_report(ui_browser, csrf, client_id)
    clock.advance(5)
    second = await make_report(ui_browser, csrf, client_id)
    assert second == first
    assert await count(db_engine, Snapshot) == 1
    other_period = await ui_browser.post(
        f"/clients/{client_id}/reports/snapshot",
        data={
            "csrf_token": csrf,
            "period_start": "2026-04-01",
            "period_end": "2026-06-30",
        },
    )
    assert other_period.status_code == 303
    assert other_period.headers["location"] != first
    clock.advance(60)
    later = await make_report(ui_browser, csrf, client_id)
    assert later not in (first, other_period.headers["location"])
    assert await count(db_engine, Snapshot) == 3
