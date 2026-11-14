"""A report as a PDF file: app/reports/pdf.py and the Download PDF button.

The page tests need PostgreSQL. The print test needs a Chromium: the image has one
(the compose smoke test prints a report inside the container, scripts/e2e/phase_00.sh)
and so does the CI runner; a machine without one skips it.
"""

import re
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.evidence.service import EvidenceContext
from app.reports import pdf as pdf_module
from app.reports.pdf import BROWSERS, PdfError, find_browser, pdf_of
from app.ui import reports as ui_reports
from ui_helpers import make_report, seed_client, sign_in

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden" / "reports" / "qbr-client-a.html"
# Chrome on Windows is not on the PATH; a developer there still runs the print test.
WINDOWS_CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def test_the_browser_of_the_image_is_looked_for_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert BROWSERS[0] == "chromium-headless-shell"
    asked: list[str] = []

    def which(name: str) -> str | None:
        asked.append(name)
        return f"/usr/bin/{name}" if name == "chromium" else None

    monkeypatch.setattr(pdf_module.shutil, "which", which)
    assert find_browser() == "/usr/bin/chromium"
    assert asked == ["chromium-headless-shell", "chromium"]
    monkeypatch.setattr(pdf_module.shutil, "which", lambda name: None)
    assert find_browser() is None


def test_what_cannot_be_printed_is_an_error_not_a_file() -> None:
    with pytest.raises(PdfError, match="no single head"):
        pdf_of(b"<p>not a report</p>", "a-browser")
    with pytest.raises(PdfError):
        pdf_of(GOLDEN.read_bytes(), str(ROOT / "there-is-no-such-browser"))


def test_a_report_prints_to_a_tagged_pdf_and_runs_no_script() -> None:
    browser = str(WINDOWS_CHROME) if WINDOWS_CHROME.is_file() else find_browser()
    if browser is None:
        pytest.skip("no Chromium on this machine")
    report = GOLDEN.read_bytes()
    # A script that would leave one line on one sheet, had the browser run it.
    planted = report.replace(
        b"</body>", b"<script>document.body.textContent = 'ran'</script></body>"
    )
    assert planted != report
    data = pdf_of(planted, browser)
    assert data.startswith(b"%PDF-")
    assert len(re.findall(rb"/Type\s*/Page\b", data)) >= 10
    # A4, as the print stylesheet asks, and not the paper of the browser.
    assert re.search(rb"/MediaBox \[0 0 59[45][.\d]* 84[12][.\d]*\]", data)
    # Tagged, so a screen reader finds the headings and the tables.
    assert b"/StructTreeRoot" in data and b"/MarkInfo" in data


async def test_the_report_page_offers_the_pdf_only_where_a_browser_can_make_it(
    ui_browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ui_ctx: EvidenceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    report = await make_report(ui_browser, csrf, client_id)
    state = ui_browser._transport.app.state  # type: ignore[attr-defined]

    # No browser on the machine: no button, the print hint, and the address says so.
    state.pdf_browser = None
    page = (await ui_browser.get(report)).text
    assert "/pdf/" not in page and "print it from your browser" in page
    refused = await ui_browser.get(f"{report}/pdf/qbr")
    assert refused.status_code == 404
    assert "no browser to make a PDF" in refused.text

    # With one: a button for each report, and the file is the preview, printed.
    printed: list[tuple[bytes, str]] = []

    def fake(html: bytes, browser: str) -> bytes:
        printed.append((html, browser))
        return b"%PDF-1.4 a test file"

    state.pdf_browser = "a-browser"
    monkeypatch.setattr(ui_reports, "pdf_of", fake)
    page = (await ui_browser.get(report)).text
    for kind in ("qbr", "insurance"):
        assert f'href="{report}/pdf/{kind}" download>Download PDF</a>' in page
    assert "print it from your browser" not in page
    got = await ui_browser.get(f"{report}/pdf/qbr")
    assert got.status_code == 200 and got.content == b"%PDF-1.4 a test file"
    assert got.headers["content-type"] == "application/pdf"
    assert re.fullmatch(
        r'attachment; filename="qbr-[a-z0-9-]+-\d{4}-\d{2}-\d{2}\.pdf"',
        got.headers["content-disposition"],
    )
    assert "no-store" in got.headers["cache-control"]
    preview = (await ui_browser.get(f"{report}/preview/qbr")).content
    assert printed == [(preview, "a-browser")]
    assert (await ui_browser.get(f"{report}/pdf/nope")).status_code == 404

    # A browser that fails leaves a readable refusal, not an error page of the server.
    def broken(html: bytes, browser: str) -> bytes:
        raise PdfError("exit 1")

    monkeypatch.setattr(ui_reports, "pdf_of", broken)
    failed = await ui_browser.get(f"{report}/pdf/qbr")
    assert failed.status_code == 503 and "could not be made" in failed.text


async def test_a_pdf_needs_a_signed_in_person(ui_browser: httpx.AsyncClient) -> None:
    ui_browser._transport.app.state.pdf_browser = "a-browser"  # type: ignore[attr-defined]
    answer = await ui_browser.get("/clients/1/reports/1/pdf/qbr")
    assert answer.status_code == 303 and "/login" in answer.headers["location"]
