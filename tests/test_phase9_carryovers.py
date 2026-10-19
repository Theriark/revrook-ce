"""Carry-overs from the review of phase 8 (THE-315 and THE-316), each with a test.

The tests that need PostgreSQL (DATABASE_URL) are skipped without it. The others read
files or render reports and run anywhere.
"""

import asyncio
import re
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.checks.library import load_library
from app.clients import create_client
from app.evidence.errors import ClientNotFoundError
from app.evidence.locking import lock_client
from app.evidence.service import EvidenceContext
from app.models import Client, ReportExport
from app.reports.completeness import completeness_problems
from app.reports.export import ExportNotFoundError, export_report, read_export
from app.reports.render import QBR, render_report
from app.reports.view import ReportError, ReportView, build_view
from app.scoring.snapshot import parse_snapshot, render_snapshot
from app.textcheck import control_character
from app.ui import reports as ui_reports
from helpers import create_test_client
from tools import report_clients
from ui_helpers import (
    NAME,
    QUARTER,
    make_report,
    post_export,
    seed_client,
    sign_in,
)

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = load_library()


def view_of(name: str = "A", **context_changes: Any) -> ReportView:
    context = replace(report_clients.context_for(name), **context_changes)
    return build_view(
        report_clients.snapshot_bytes(LIBRARY, name),
        LIBRARY,
        context,
        report_clients.previous_bytes(LIBRARY, name),
    )


def files_of(folder: Path) -> set[str]:
    """The names of the files below a folder that may not exist."""
    return {str(path) for path in folder.rglob("*") if path.is_file()}


def thin_view() -> ReportView:
    """A client whose evidence is too thin to rate: nothing is known."""
    snapshot = parse_snapshot(report_clients.snapshot_bytes(LIBRARY, "A"))
    controls = tuple(
        replace(item, status="unknown", quality=Fraction(0), evidence_at=None)
        for item in snapshot.controls
    )
    data = render_snapshot(replace(snapshot, controls=controls))
    return build_view(data, LIBRARY, report_clients.context_for("A"))


# --- F2 / N7: the score line under Insufficient evidence ----------------------------


def test_the_facts_line_says_lower_bound_when_the_evidence_is_too_thin() -> None:
    view = thin_view()
    assert view.result.insufficient
    text = render_report(QBR, view).decode("utf-8")
    assert "<dt>Lower bound of the score</dt>" in text
    assert "a lower bound only" in text
    assert "<dt>Score</dt>" not in text


def test_the_facts_line_says_score_when_the_evidence_is_enough() -> None:
    text = render_report(QBR, view_of("A")).decode("utf-8")
    assert "<dt>Score</dt><dd>89.5 out of 100</dd>" in text
    assert "Lower bound of the score" not in text


# --- F3 / N8: the sentence about a capped score -------------------------------------


def test_the_cap_sentence_names_the_control_and_keeps_its_title_apart() -> None:
    text = render_report(QBR, view_of("C")).decode("utf-8")
    assert (
        "The score of 86.6 is held at 49 because PC-ACC-02 is not protected "
        "(Every administrator uses MFA)." in text
    )
    assert "because Every administrator" not in text
    assert "MFA.)" not in text and "MFA. (" not in text


# --- F4: control characters in names ------------------------------------------------


@pytest.mark.parametrize("character", ["\x00", "\x07", "\x1b", "\x7f"])
def test_a_control_character_is_found(character: str) -> None:
    assert control_character(f"Alder{character}Finch") == character
    assert control_character(f"Alder{character}Finch", allow_breaks=True) == character


def test_a_note_may_hold_tabs_and_line_breaks_but_a_name_may_not() -> None:
    assert control_character("one\ntwo\tthree\r") == "\n"
    assert control_character("one\ntwo\tthree\r", allow_breaks=True) is None
    assert control_character("Alder and Finch Ltd. (Réseau)") is None


def test_a_report_with_a_control_character_in_a_name_cannot_be_exported() -> None:
    view = view_of("A", client_name="Alder\x07Finch")
    assert any("contains a control character" in p for p in completeness_problems(view))
    note = view_of("A", next_quarter_plan=("Plan\x00line",))
    assert any("control character" in p for p in completeness_problems(note))
    fine = view_of("A", next_quarter_plan=("Line one\ntwo",))
    assert not any("control character" in p for p in completeness_problems(fine))


@pytest.mark.parametrize("name", ["Bad\x00Name", "Bad\x07Name"])
async def test_a_client_cannot_be_created_with_a_control_character(
    db_engine: AsyncEngine, ui_ctx: EvidenceContext, name: str
) -> None:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        with pytest.raises(ValueError, match="control character"):
            await create_client(session, ui_ctx.cipher, name)


# --- N1 / F1, N2, N3, N5, N4: the files and the documents ---------------------------


def test_the_print_stylesheet_and_the_spike_claim_one_footer_per_section() -> None:
    css = (ROOT / "app" / "reports" / "print.css").read_text(encoding="utf-8")
    spike = (ROOT / "docs" / "pdf-spike.md").read_text(encoding="utf-8")
    assert "footer at its end only" in css
    assert "footer of every section" in (
        ROOT / "app" / "reports" / "disclaimer.py"
    ).read_text(encoding="utf-8")
    assert "carries its footer" in spike and "on its last sheet only" in spike


def test_the_documents_say_not_assessed_and_make_no_pyphen_statement() -> None:
    for name in ("pdf-spike.md", "licences.md"):
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        assert "Pyphen" not in text, name
        assert "gates failed" not in text, name
    licences = (ROOT / "docs" / "licences.md").read_text(encoding="utf-8")
    assert "were not assessed" in licences
    assert "**not assessed**" in (ROOT / "docs" / "pdf-spike.md").read_text(
        encoding="utf-8"
    )


def test_markupsafe_is_a_direct_dependency_with_a_row_in_the_licence_table() -> None:
    names = re.findall(
        r"^([A-Za-z0-9_.-]+)",
        (ROOT / "requirements.in").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert "markupsafe" in [name.lower() for name in names]
    licences = (ROOT / "docs" / "licences.md").read_text(encoding="utf-8")
    assert "| markupsafe |" in licences
    assert "markupsafe==" in (ROOT / "requirements.txt").read_text(encoding="utf-8")


def test_the_pdf_measurement_is_opt_in_and_the_workflows_are_untouched() -> None:
    phase_08 = (ROOT / "scripts" / "e2e" / "phase_08.sh").read_text(encoding="utf-8")
    assert 'if [[ "${RUN_PDF_SPIKE:-0}" == "1" ]]' in phase_08
    measure_call = phase_08.index("scripts/pdf-spike/measure.sh")
    assert measure_call > phase_08.index("RUN_PDF_SPIKE")
    workflows = sorted(
        path.name for path in (ROOT / ".github" / "workflows").glob("*.yml")
    )
    assert workflows == ["ci.yml", "promote-production.yml", "promote-stage.yml"]


# --- ownership of an export (IDOR) --------------------------------------------------


async def test_an_export_is_only_read_for_the_client_it_belongs_to(
    db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    mine = await create_test_client(db_engine, ui_ctx, "Mine Ltd")
    other = await create_test_client(db_engine, ui_ctx, "Other Ltd")
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        record, data = await export_report(
            session, ui_ctx.files, view_of(), QBR, client_id=mine
        )
    async with factory() as session:
        again, copy = await read_export(session, ui_ctx.files, mine, record.id)
        assert copy == data and again.id == record.id
        with pytest.raises(ExportNotFoundError, match="for this client"):
            await read_export(session, ui_ctx.files, other, record.id)


async def test_the_download_of_another_clients_export_is_a_404(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    mine = await seed_client(db_engine, ui_ctx)
    other = await seed_client(db_engine, ui_ctx, "Other Client Ltd")
    report = await make_report(ui_browser, csrf, mine)
    exported = await post_export(ui_browser, csrf, report, "qbr")
    assert exported.status_code == 303
    export_id = exported.headers["location"].rsplit("=", 1)[1]
    own = await ui_browser.get(f"/clients/{mine}/exports/{export_id}/download")
    assert own.status_code == 200
    stolen = await ui_browser.get(f"/clients/{other}/exports/{export_id}/download")
    assert stolen.status_code == 404
    assert NAME not in stolen.text


# --- an export under a concurrent delete leaves no file without a row ---------------


async def test_an_export_waits_for_a_delete_and_then_leaves_no_file(
    db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ui_ctx, "Vanishing Ltd")
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def export() -> None:
        async with factory() as session, session.begin():
            await export_report(
                session, ui_ctx.files, view_of(), QBR, client_id=client_id
            )

    async with factory() as deleting, deleting.begin():
        await lock_client(deleting, client_id)
        racing = asyncio.create_task(export())
        await asyncio.sleep(0.5)
        assert not racing.done(), "the export did not wait for the client's lock"
        await deleting.execute(delete(Client).where(Client.id == client_id))
    with pytest.raises(ClientNotFoundError):
        await racing
    assert not ui_ctx.files.client_dir(client_id).exists()


# --- the refusals are 4xx, never 500 ------------------------------------------------


async def test_an_export_that_claims_too_much_is_a_422_with_every_problem(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    report = await make_report(ui_browser, csrf, client_id, msp=False)
    before = files_of(ui_ctx.files.client_dir(client_id))
    page = await ui_browser.get(report)
    assert page.status_code == 200 and "to fix first" in page.text
    refused = await post_export(ui_browser, csrf, report, "qbr")
    assert refused.status_code == 422
    assert "cannot be exported yet" in refused.text
    assert "the MSP name is empty" in refused.text
    history = await ui_browser.get(f"/clients/{client_id}/exports")
    assert "Nothing has been exported" in history.text
    assert files_of(ui_ctx.files.client_dir(client_id)) == before


@pytest.mark.parametrize(
    "error", [ReportError("the snapshot is unreadable"), ValueError("odd")]
)
async def test_a_report_or_value_error_is_a_422(
    ui_browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ui_ctx: EvidenceContext,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    report = await make_report(ui_browser, csrf, client_id)

    async def broken(*args: Any, **kwargs: Any) -> ReportView:
        raise error

    monkeypatch.setattr(ui_reports, "build_report_view", broken)
    assert (await ui_browser.get(report)).status_code == 422
    assert (await ui_browser.get(f"{report}/preview/qbr")).status_code == 422
    assert (await post_export(ui_browser, csrf, report, "qbr")).status_code == 422


async def test_a_damaged_copy_is_a_409_and_a_missing_one_too(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    await ui_browser.post(
        "/settings", data={"csrf_token": csrf, "msp_name": "Synthetic MSP Ltd"}
    )
    report = await make_report(ui_browser, csrf, client_id)
    exported = await post_export(ui_browser, csrf, report, "qbr")
    export_id = exported.headers["location"].rsplit("=", 1)[1]
    async with async_sessionmaker(db_engine)() as session:
        row = await session.get(ReportExport, int(export_id))
    assert row is not None
    stored = ui_ctx.files.root / row.storage_key
    stored.write_bytes(stored.read_bytes() + b"<!-- changed -->")
    address = f"/clients/{client_id}/exports/{export_id}/download"
    damaged = await ui_browser.get(address)
    assert damaged.status_code == 409 and "does not match" in damaged.text
    assert b"changed" not in damaged.content
    stored.unlink()
    gone = await ui_browser.get(address)
    assert gone.status_code == 409 and "missing" in gone.text


async def test_an_unknown_report_kind_is_refused_with_a_4xx(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    report = await make_report(ui_browser, csrf, client_id)
    assert (await post_export(ui_browser, csrf, report, "deck")).status_code == 422
    assert (await post_export(ui_browser, csrf, report, "")).status_code == 422
    assert (await ui_browser.get(f"{report}/preview/deck")).status_code == 404
    bad_period = await ui_browser.post(
        f"/clients/{client_id}/reports/snapshot",
        data={"csrf_token": csrf, "period_start": QUARTER[1], "period_end": QUARTER[0]},
    )
    assert bad_period.status_code == 422
