"""Two limits of the charts that must never break or hide a page (THE-901).

A stored band the scoring model does not know is left out of the bands of the
clients list instead of raising, and the score history of a client says in words
when the cap on the reports it reads leaves older ones out of the chart.
"""

from dataclasses import replace

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.checks.library import load_library
from app.evidence.service import EvidenceContext
from app.ui.charts import band_counts
from app.ui.clientlist import (
    BAND_KEYS,
    NO_REPORT_KEY,
    ClientCard,
    band_key,
    last_report_of,
)
from html_structure import structure_problems
from tools import report_clients
from tools.score_inputs import AS_OF
from ui_helpers import make_report, seed_client, sign_in

LIBRARY = load_library()


def card(number: int, name: str, report: object = None) -> ClientCard:
    return ClientCard(number, name, 0, None, None, report)  # type: ignore[arg-type]


def test_a_stored_band_the_model_does_not_know_never_breaks_the_count() -> None:
    known = last_report_of(report_clients.inputs(LIBRARY, "A", AS_OF))
    unknown = replace(known, band="Outstanding")
    assert band_key(unknown.band) not in BAND_KEYS
    counts = band_counts([card(1, "Alder", known), card(2, "Birch", unknown)])
    assert [item.key for item in counts] == [*BAND_KEYS, NO_REPORT_KEY]
    assert sum(item.count for item in counts) == 1
    assert {item.key: item.count for item in counts}[band_key(known.band)] == 1


async def test_the_history_says_when_the_cap_leaves_older_reports_out(
    ui_browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ui_ctx: EvidenceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    await make_report(ui_browser, csrf, client_id)
    # A second report of another period, so it is not taken for a double click.
    second = await ui_browser.post(
        f"/clients/{client_id}/reports/snapshot",
        data={
            "csrf_token": csrf,
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
        },
    )
    assert second.status_code == 303
    address = f"/clients/{client_id}/reports"
    within = await ui_browser.get(address, params={"span": "all"})
    assert within.status_code == 200 and 'id="history-capped"' not in within.text
    monkeypatch.setattr("app.ui.reports.MAX_SNAPSHOTS", 1)
    capped = await ui_browser.get(address, params={"span": "all"})
    assert capped.status_code == 200 and structure_problems(capped.text) == []
    assert 'id="history-capped"' in capped.text
    assert "Only the newest 1 reports of this client are drawn" in capped.text
    fragment = await ui_browser.get(
        f"/clients/{client_id}/charts/history",
        params={"span": "all"},
        headers={"HX-Request": "true"},
    )
    assert fragment.status_code == 200 and 'id="history-capped"' in fragment.text
