"""Phase 8 end-to-end check, run inside the image of the stack by phase_08.sh.

    docker exec -i <web container> python - < scripts/e2e/phase_08_check.py

Builds a synthetic snapshot from the control library that ships in the image (nothing
is read from the database and nothing leaves the machine), then proves in the image:
both reports render, every page carries the disclaimer, the last page has it in full,
the same snapshot gives the same bytes, a hostile client name and exception text are
printed as text, and a claim with no dated evidence blocks the export.
"""

import re
from datetime import UTC, date, datetime, timedelta
from fractions import Fraction

from app.checks.library import load_library
from app.exceptions import ExceptionEntry
from app.reports.completeness import ExportBlockedError, ensure_complete
from app.reports.disclaimer import DISCLAIMER, GENERATED_WITH
from app.reports.render import INSURANCE, QBR, render_report
from app.reports.view import ReportContext, build_view
from app.scoring.engine import domain_weights
from app.scoring.model import DEFAULT_THRESHOLDS, ControlInput
from app.scoring.snapshot import EvidenceRef, SnapshotInput, render_snapshot

AS_OF = datetime(2026, 10, 17, 8, 0, tzinfo=UTC)
LIBRARY = load_library()
HOSTILE = "<script>alert(1)</script> & 'x'"
SECTION = re.compile(r'<section class="page[^"]*" id="([^"]+)".*?</section>', re.DOTALL)


def snapshot(undated: bool = False) -> bytes:
    controls = []
    for index, control in enumerate(LIBRARY.controls):
        status = ("pass", "partial", "fail", "unknown")[index % 4]
        at = None if status == "unknown" else AS_OF - timedelta(days=2 + index % 5)
        if undated and index == 0:
            status, at = "pass", None
        controls.append(
            ControlInput(
                control_id=control.id,
                domain=control.domain,
                weight=control.weight,
                gate=control.gate,
                status=status,
                quality=Fraction(0 if status == "unknown" else 1),
                evidence_at=at,
                max_age_days=control.max_age_days.automatic,
            )
        )
    return render_snapshot(
        SnapshotInput(
            ruleset_id=LIBRARY.ruleset_id,
            ruleset_version=LIBRARY.version,
            importer_version="importers-e2e",
            as_of=AS_OF,
            thresholds=DEFAULT_THRESHOLDS,
            domains=domain_weights(LIBRARY),
            controls=tuple(controls),
            evidence=(EvidenceRef("evidence-0001", "ab" * 32),),
        )
    )


def context(
    client: str = "Synthetic Client Ltd", reason: str = "Accepted"
) -> ReportContext:
    return ReportContext(
        msp_name="Synthetic MSP",
        client_name=client,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 9, 30),
        prepared_by="Sam Technician",
        generated_on=date(2026, 10, 17),
        data_sources=("Synthetic export",),
        exceptions=(
            ExceptionEntry(
                LIBRARY.controls[0].id,
                "Office manager",
                reason,
                None,
                date(2026, 12, 1),
            ),
        ),
    )


def pages_of(html: str) -> list[str]:
    return [match.group(0) for match in SECTION.finditer(html)]


data = snapshot()
for kind in (QBR, INSURANCE):
    view = build_view(data, LIBRARY, context())
    first = render_report(kind, view)
    again = render_report(kind, build_view(data, LIBRARY, context()))
    assert first == again, f"{kind}: the same snapshot gave other bytes"
    html = first.decode("utf-8")
    pages = pages_of(html)
    assert len(pages) >= 4, (kind, len(pages))
    for page in pages:
        footer = page.split('<footer class="page-footer">')[-1]
        assert DISCLAIMER in footer and GENERATED_WITH in footer, kind
    assert 'class="disclaimer-full"' in pages[-1], kind
    assert "<img" not in html and "<script" not in html, kind
    print(f"phase_08: {kind} renders {len(pages)} pages, each with the disclaimer")

    hostile = build_view(data, LIBRARY, context(HOSTILE, HOSTILE))
    text = render_report(kind, hostile).decode("utf-8")
    assert "<script" not in text and "&lt;script&gt;" in text, kind
    print(f"phase_08: {kind} prints a hostile name and exception text as text")

try:
    ensure_complete(build_view(snapshot(undated=True), LIBRARY, context()))
except ExportBlockedError as blocked:
    assert "no dated evidence" in blocked.problems[0], blocked.problems
    print("phase_08: a result with no dated evidence blocks the export")
else:
    raise AssertionError("an undated claim was allowed to be exported")
