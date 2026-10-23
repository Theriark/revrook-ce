"""Two limits of the charts that must never break or hide a page (THE-901, THE-953).

A stored band the scoring model does not know is left out of the bands of the
clients list instead of raising, and the list says how many clients that leaves out
of the bars so the bars never silently disagree with the total. The score history of
a client says in words when the cap on the reports it reads leaves older ones out of
the chart, and says nothing when no report is left out.
"""

from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.checks.library import load_library
from app.evidence.service import EvidenceContext
from app.ui import clients as ui_clients
from app.ui.charts import band_counts, unclassified_count
from app.ui.clientlist import (
    BAND_KEYS,
    NO_REPORT_KEY,
    ClientCard,
    LastReport,
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


def test_the_clients_in_an_unknown_band_are_counted_apart() -> None:
    known = last_report_of(report_clients.inputs(LIBRARY, "A", AS_OF))
    unknown = replace(known, band="Outstanding")
    cards = [card(1, "Alder", known), card(2, "Birch", unknown), card(3, "Cedar")]
    cards.append(card(4, "Dogwood", replace(known, band="Exceptional")))
    bars = band_counts(cards)
    assert unclassified_count(cards) == bars.unclassified == 2
    # Every client is in a bar or in the count of the clients without one.
    assert sum(item.count for item in bars) + unclassified_count(cards) == len(cards)
    assert unclassified_count([]) == 0
    assert unclassified_count([card(1, "Alder", known), card(2, "Cedar")]) == 0


async def test_the_list_says_how_many_clients_no_bar_counts(
    ui_browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ui_ctx: EvidenceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    await make_report(ui_browser, csrf, client_id)
    plain = await ui_browser.get("/clients")
    assert plain.status_code == 200 and 'id="bands-unclassified"' not in plain.text
    real = ui_clients.last_reports

    def other_ruleset(
        documents: Iterable[tuple[int, Mapping[str, Any]]],
    ) -> dict[int, LastReport]:
        found = real(documents)
        return {key: replace(row, band="Outstanding") for key, row in found.items()}

    monkeypatch.setattr(ui_clients, "last_reports", other_ruleset)
    page = await ui_browser.get("/clients")
    assert page.status_code == 200 and structure_problems(page.text) == []
    assert 'id="bands-unclassified"' in page.text
    assert "1 client has a last report in a band this version does not know" in (
        page.text
    )
    assert 'class="rv-band-count">0</span>' in page.text
    assert f'href="/clients/{client_id}"' in page.text


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
    # A cap that equals the number of reports drops nothing, so there is no notice.
    monkeypatch.setattr("app.ui.reports.MAX_SNAPSHOTS", 2)
    exact = await ui_browser.get(address, params={"span": "all"})
    assert exact.status_code == 200 and 'id="history-capped"' not in exact.text
    monkeypatch.setattr("app.ui.reports.MAX_SNAPSHOTS", 1)
    capped = await ui_browser.get(address, params={"span": "all"})
    assert capped.status_code == 200 and structure_problems(capped.text) == []
    assert 'id="history-capped"' in capped.text
    assert "Only the newest report of this client is drawn" in capped.text
    assert "1 reports" not in capped.text
    fragment = await ui_browser.get(
        f"/clients/{client_id}/charts/history",
        params={"span": "all"},
        headers={"HX-Request": "true"},
    )
    assert fragment.status_code == 200 and 'id="history-capped"' in fragment.text
