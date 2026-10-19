"""The view models of the client pages: checklist rows, filter, sources, period."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.checks.library import load_library
from app.checks.model import ControlResult
from app.evidence.assurance import Assurance
from app.evidence.expiry import Freshness
from app.evidence.service import EvidenceView
from app.reports.status import NOT_APPLICABLE, PROTECTED
from app.reports.topics import TOPICS
from app.reports.view import (
    EVIDENCE_CURRENT,
    EVIDENCE_EXPIRED,
    EVIDENCE_EXPIRING,
    ReportView,
    build_view,
)
from app.ui.common import FormError, last_quarter, read_period, sentence
from app.ui.viewmodels import (
    CURRENT,
    EXCEPTION_FLAG,
    EXPIRED,
    EXPIRED_FLAG,
    EXPIRING_FLAG,
    MISSING,
    NOT_ASSIGNED,
    NOT_MEASURED,
    STALE,
    checklist_rows,
    coverage_text,
    flags_of,
    only_flagged,
    read_earlier,
    reason_text,
    refresh_list,
    source_rows,
)
from tools import report_clients

LIBRARY = load_library()
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def view_of(name: str) -> ReportView:
    return build_view(
        report_clients.snapshot_bytes(LIBRARY, name),
        LIBRARY,
        report_clients.context_for(name),
        report_clients.previous_bytes(LIBRARY, name),
    )


def result(numerator: int | None, denominator: int | None) -> ControlResult:
    return ControlResult(
        control_id="PC-ACC-01",
        status="pass",
        reason=None,
        detail="",
        numerator=numerator,
        denominator=denominator,
        quality=Decimal(1),
        assurance="automatic-export",
        evidence_at=NOW,
        age_days=0,
        max_age_days=35,
        stale=False,
    )


def evidence_view(
    code: str, days_old: int, freshness: Freshness, assurance: Assurance
) -> EvidenceView:
    captured = NOW - timedelta(days=days_old)
    return EvidenceView(
        item_id=days_old,
        source_code=code,
        assurance=assurance,
        captured_at=captured,
        expires_at=captured + timedelta(days=35),
        freshness=freshness,
        revisions=1,
        files_kept=0,
        sha256="ab" * 32,
        size_bytes=10,
    )


def export_view(code: str, days_old: int, freshness: Freshness) -> EvidenceView:
    return evidence_view(code, days_old, freshness, Assurance.AUTOMATIC_EXPORT)


@pytest.mark.parametrize("name", ["A", "B", "C"])
def test_a_row_is_changed_when_its_label_differs_from_the_earlier_report(
    name: str,
) -> None:
    view = view_of(name)
    earlier_name = report_clients.EARLIER[name]
    if earlier_name is None:
        rows = checklist_rows(view, {}, None, {}, set())
        assert not any(item.changed for item in rows)
        return
    data = report_clients.previous_bytes(LIBRARY, name)
    assert data is not None
    earlier_context = report_clients.context_for(earlier_name)
    earlier_view = build_view(data, LIBRARY, earlier_context)
    before = {row.control_id: row.label for row in earlier_view.rows}
    rows = checklist_rows(view, {}, read_earlier(data), {}, set())
    expected = set()
    for row in view.rows:
        if before[row.control_id] != row.label:
            expected.add(row.control_id)
    changed = {item.row.control_id for item in rows if item.changed}
    assert changed == expected
    assert 0 < len(changed) < len(rows)
    for item in rows:
        if item.changed:
            assert item.changed_from == before[item.row.control_id]
            assert item.changed_from != item.row.label


def test_without_an_earlier_report_no_row_is_changed() -> None:
    rows = checklist_rows(view_of("B"), {}, None, {}, set())
    assert len(rows) == len(LIBRARY.controls)
    assert not any(item.changed for item in rows)
    assert read_earlier(None) is None
    assert read_earlier(b"not a snapshot") is None


@pytest.mark.parametrize("name", ["A", "B", "C"])
def test_the_filter_keeps_exactly_the_rows_that_changed_or_need_a_look(
    name: str,
) -> None:
    view = view_of(name)
    earlier = read_earlier(report_clients.previous_bytes(LIBRARY, name))
    rows = checklist_rows(view, {}, earlier, {}, set())
    kept = only_flagged(rows)
    assert kept == [item for item in rows if item.changed or item.flagged]
    kept_ids = {item.row.control_id for item in kept}
    for item in rows:
        if item.row.control_id in kept_ids:
            continue
        # A row that is dropped is protected (or not applicable), with evidence
        # that is current, and it did not change.
        assert item.row.label in (PROTECTED, NOT_APPLICABLE)
        assert item.row.evidence_state in (EVIDENCE_CURRENT, "No dated evidence")
        assert not item.changed and not item.reasons


def test_client_a_has_rows_the_filter_drops() -> None:
    rows = checklist_rows(view_of("A"), {}, None, {}, set())
    kept = only_flagged(rows)
    assert 0 < len(kept) < len(rows)
    assert any(item.row.label == PROTECTED for item in rows if item not in kept)


def test_an_open_exception_or_old_evidence_flags_a_row() -> None:
    protected = next(item for item in view_of("A").rows if item.label == PROTECTED)
    current = replace(protected, evidence_state=EVIDENCE_CURRENT)
    assert flags_of(current, False) == ()
    assert flags_of(current, True) == (EXCEPTION_FLAG,)
    expired = replace(protected, evidence_state=EVIDENCE_EXPIRED)
    assert flags_of(expired, False) == (EXPIRED_FLAG,)
    expiring = replace(protected, evidence_state=EVIDENCE_EXPIRING)
    assert flags_of(expiring, True) == (EXPIRING_FLAG, EXCEPTION_FLAG)


def test_a_row_that_is_not_protected_says_why_in_words() -> None:
    rows = checklist_rows(view_of("B"), {}, None, {}, set())
    texts = {"Needs attention", "Not protected", "Not checked"}
    for item in rows:
        if item.row.label.text in texts:
            assert item.row.label.text in item.reasons


def test_the_owner_comes_from_the_topic_of_the_control() -> None:
    topic = TOPICS[0]
    rows = checklist_rows(view_of("A"), {}, None, {topic.key: "Sam"}, set())
    by_id = {item.row.control_id: item for item in rows}
    for control_id in topic.control_ids:
        assert by_id[control_id].owner == "Sam"
    other = next(item for item in rows if item.row.control_id not in topic.control_ids)
    assert other.owner == NOT_ASSIGNED


def test_the_exception_flag_is_set_for_the_controls_that_have_one() -> None:
    rows = checklist_rows(view_of("A"), {}, None, {}, {"PC-ACC-01"})
    by_id = {item.row.control_id: item for item in rows}
    assert EXCEPTION_FLAG in by_id["PC-ACC-01"].reasons
    assert EXCEPTION_FLAG not in by_id["PC-ACC-02"].reasons


def test_coverage_is_written_as_counts_and_a_share() -> None:
    assert coverage_text(result(9, 10)) == "9 of 10 (90%)"
    assert coverage_text(result(1, 3)) == "1 of 3 (33%)"
    assert coverage_text(result(0, 4)) == "0 of 4 (0%)"
    assert coverage_text(result(None, None)) == NOT_MEASURED
    assert coverage_text(result(0, 0)) == NOT_MEASURED
    assert coverage_text(None) == NOT_MEASURED


def test_a_reason_is_put_into_words() -> None:
    assert reason_text(None) == ""
    assert "no such field" in reason_text("licence_or_scope")
    assert reason_text("something_new") == "something_new"


def test_sources_are_listed_by_name_and_the_oldest_export_is_refreshed_first() -> None:
    views = [
        export_view("device-inventory", 2, Freshness.CURRENT),
        export_view("network-export", 50, Freshness.STALE),
        export_view("backup-export", 100, Freshness.EXPIRED),
        export_view("backup-export", 120, Freshness.EXPIRED),
        evidence_view("training-csv", 1, Freshness.CURRENT, Assurance.ATTESTATION),
    ]
    wanted = ["backup-export", "device-inventory", "dns-check", "network-export"]
    rows = source_rows(views, wanted)
    assert [row.code for row in rows] == [
        "backup-export",
        "device-inventory",
        "network-export",
        "dns-check",
    ]
    by_code = {row.code: row for row in rows}
    assert by_code["device-inventory"].state == CURRENT
    assert by_code["device-inventory"].refresh is None
    assert by_code["network-export"].state == STALE
    assert by_code["backup-export"].state == EXPIRED
    assert by_code["backup-export"].exports == 2
    assert by_code["backup-export"].captured_at == NOW - timedelta(days=100)
    assert by_code["dns-check"].state == MISSING
    assert by_code["dns-check"].captured_at is None
    assert "training-csv" not in by_code
    refresh = refresh_list(rows)
    assert [row.code for row in refresh] == [
        "backup-export",
        "network-export",
        "dns-check",
    ]
    assert all(row.refresh for row in refresh)
    dns_refresh = by_code["dns-check"].refresh
    assert dns_refresh is not None and "public DNS check" in dns_refresh


def test_a_source_that_is_not_wanted_is_still_listed_when_it_was_imported() -> None:
    views = [
        evidence_view("leavers-csv", 3, Freshness.CURRENT, Assurance.AUTOMATIC_EXPORT)
    ]
    rows = source_rows(views, [])
    assert [(row.code, row.name) for row in rows] == [("leavers-csv", "Leavers list")]
    assert refresh_list(rows) == []


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 10, 17), (date(2026, 7, 1), date(2026, 9, 30))),
        (date(2026, 10, 1), (date(2026, 7, 1), date(2026, 9, 30))),
        (date(2026, 1, 15), (date(2025, 10, 1), date(2025, 12, 31))),
        (date(2026, 3, 31), (date(2025, 10, 1), date(2025, 12, 31))),
        (date(2026, 4, 1), (date(2026, 1, 1), date(2026, 3, 31))),
        (date(2026, 12, 31), (date(2026, 7, 1), date(2026, 9, 30))),
    ],
)
def test_the_default_period_is_the_last_full_quarter(
    today: date, expected: tuple[date, date]
) -> None:
    assert last_quarter(today) == expected
    assert read_period("", "", today) == expected


def test_a_period_is_read_and_checked() -> None:
    today = date(2026, 10, 17)
    assert read_period("2026-08-01", "2026-09-30", today) == (
        date(2026, 8, 1),
        date(2026, 9, 30),
    )
    assert read_period("2026-08-01", "", today) == (date(2026, 8, 1), date(2026, 9, 30))
    assert read_period("2026-10-17", "2026-10-17", today)[1] == today


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("2026-09-30", "2026-07-01", "ends before it starts"),
        ("2026-07-01", "2026-10-18", "cannot end in the future"),
        ("2025-01-01", "2026-10-17", "longer than 400 days"),
        ("yesterday", "", "start of the period must be a date"),
        ("", "30/09/2026", "end of the period must be a date"),
    ],
)
def test_a_bad_period_is_refused_with_a_422(start: str, end: str, message: str) -> None:
    with pytest.raises(FormError, match=message) as caught:
        read_period(start, end, date(2026, 10, 17))
    assert caught.value.status_code == 422


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("name must be 1 to 200 characters", "Name must be 1 to 200 characters."),
        ("Already a sentence.", "Already a sentence."),
        ("  spaced  ", "Spaced."),
        ("", ""),
    ],
)
def test_a_message_starts_with_a_capital_and_ends_with_a_full_stop(
    text: str, expected: str
) -> None:
    assert sentence(text) == expected
