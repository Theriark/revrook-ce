"""The details a report prints that come from the installation and from the moment
its snapshot was made, through the pages: the logo of the business (Settings), what
each check found (kept with the snapshot) and the name of the person who prepared it.
"""

import base64
import html
import re

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.checks.library import load_library
from app.evidence.service import EvidenceContext
from app.models import AuditEvent, ControlResult
from app.preferences import MAX_LOGO_BYTES
from ui_helpers import make_report, seed_client, sign_in

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
SEEN = re.compile(r"<dt>What was checked</dt><dd>(.*?)</dd>", re.DOTALL)


async def test_a_logo_is_kept_shown_on_the_cover_and_removed(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    report = await make_report(ui_browser, csrf, client_id)
    assert (await ui_browser.get("/settings/logo")).status_code == 404
    assert "<img" not in (await ui_browser.get(f"{report}/preview/qbr")).text

    # A file is a logo by its first bytes, not by its name or the type it is sent as.
    refused = await ui_browser.post(
        "/settings/logo",
        data={"csrf_token": csrf},
        files={"logo": ("logo.png", b"<svg onload=alert(1)/>", "image/png")},
    )
    assert refused.status_code == 422 and "PNG, JPEG or WebP" in refused.text
    too_big = await ui_browser.post(
        "/settings/logo",
        data={"csrf_token": csrf},
        files={"logo": ("big.png", PNG + bytes(MAX_LOGO_BYTES), "image/png")},
    )
    assert too_big.status_code == 422
    assert f"at most {MAX_LOGO_BYTES // 1024} KB" in too_big.text
    nothing = await ui_browser.post("/settings/logo", data={"csrf_token": csrf})
    assert nothing.status_code == 422 and "Choose a logo file first" in nothing.text
    assert (await ui_browser.get("/settings/logo")).status_code == 404

    stored = await ui_browser.post(
        "/settings/logo",
        data={"csrf_token": csrf},
        files={"logo": ("logo.png", PNG, "image/png")},
    )
    assert stored.status_code == 303
    assert stored.headers["location"] == "/settings?saved=1"
    served = await ui_browser.get("/settings/logo")
    assert served.status_code == 200 and served.content == PNG
    assert served.headers["content-type"] == "image/png"
    page = (await ui_browser.get("/settings")).text
    assert '<img class="rv-cover-logo" src="/settings/logo" alt="Your logo">' in page
    assert "Remove logo" in page and "A logo is saved." in page

    # The cover of a report carries the picture inside the file, and the preview
    # lets exactly that through.
    preview = await ui_browser.get(f"{report}/preview/qbr")
    encoded = base64.b64encode(PNG).decode("ascii")
    assert (
        f'<img class="cover-mark" src="data:image/png;base64,{encoded}" alt="">'
        in preview.text
    )
    assert "img-src data:" in preview.headers["content-security-policy"]

    removed = await ui_browser.post("/settings/logo/remove", data={"csrf_token": csrf})
    assert removed.status_code == 303
    assert (await ui_browser.get("/settings/logo")).status_code == 404
    assert "<img" not in (await ui_browser.get(f"{report}/preview/qbr")).text
    assert "Remove logo" not in (await ui_browser.get("/settings")).text

    # The audit trail says the logo changed, never what it is. It is never emptied,
    # so the two lines of this test are its last two.
    async with async_sessionmaker(db_engine)() as session:
        found = await session.execute(
            select(AuditEvent.detail)
            .where(AuditEvent.action == "settings.msp_logo")
            .order_by(AuditEvent.id)
        )
        assert list(found.scalars())[-2:] == [{"bytes": len(PNG)}, {"removed": True}]


async def test_a_logo_cannot_be_sent_without_signing_in(
    ui_browser: httpx.AsyncClient,
) -> None:
    assert (await ui_browser.get("/settings/logo")).status_code in (302, 303)


async def test_a_report_says_what_each_check_found_and_who_prepared_it(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    named = await ui_browser.post(
        "/account/name", data={"csrf_token": csrf, "display_name": "Sam Synthetic"}
    )
    assert named.status_code == 303
    report = await make_report(ui_browser, csrf, client_id)
    snapshot_id = int(report.rsplit("/", 1)[1])

    # One line for every control, kept when the snapshot was made.
    async with async_sessionmaker(db_engine)() as session:
        found = await session.execute(
            select(ControlResult.control_id, ControlResult.detail).where(
                ControlResult.snapshot_id == snapshot_id
            )
        )
        kept = {control_id: detail["text"].strip() for control_id, detail in found}
    assert set(kept) == {control.id for control in load_library().controls}
    assert all(kept.values())

    text = (await ui_browser.get(f"{report}/preview/qbr")).text
    # The name the person chose stands on the cover, not the sign-in name.
    assert "<dt>Prepared by</dt><dd>Sam Synthetic</dd>" in text
    findings = text.split('id="findings"')[1].split("</section>")[0]
    shown = [html.unescape(line) for line in SEEN.findall(findings)]
    assert shown and set(shown) <= set(kept.values())

    # Nothing more is kept: one line for each control of the one snapshot made.
    async with async_sessionmaker(db_engine)() as session:
        total = len(list(await session.execute(select(ControlResult.id))))
    assert total == len(kept)
