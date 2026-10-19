"""The security checklist of phase 11 (docs/security-review.md): one test per item.

Each section below belongs to one item of the document, in its order: authentication,
CSRF, uploads, formula injection, XSS, secrets, pseudonymisation, retention, rate
limits, resource limits. The tests that need PostgreSQL are skipped without
DATABASE_URL; the others read files. Synthetic data only, no network.
"""

import csv
import io
import re
import zipfile
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app import api as api_module
from app import api_ops, metrics
from app.api import API_RATE_LIMIT, API_RATE_WINDOW_SECONDS
from app.auth import LOCKOUT_THRESHOLD, MAX_PASSWORD_LENGTH
from app.dataexport import MAX_EXPORT_BYTES, cell
from app.evidence.deletion import delete_client
from app.evidence.retention import purge_expired_raw
from app.evidence.service import EvidenceContext
from app.limits import FORM_OVERHEAD_BYTES, MAX_BODY_BYTES
from app.main import MAX_PARALLEL_LOGINS, create_app
from app.ratelimit import ConcurrencyGate, SlidingWindowLimiter
from app.security import hash_api_token, verify_password
from app.settings import Settings, SettingsError, load_settings
from app.ui import auth as ui_auth
from app.ui import clients as ui_clients
from app.ui import evidence as ui_evidence
from app.ui import profiles as ui_profiles
from app.ui import reports as ui_reports
from app.ui import site as ui_site
from app.ui import system as ui_system
from app.ui.common import MAX_PERIOD_DAYS
from helpers import (
    NOW,
    PASSWORD,
    SYNTHETIC_USERS,
    WRONG_PASSWORD,
    FakeClock,
    audit_baseline,
    audit_since,
    create_admin,
    create_test_client,
    database_dump,
    export_evidence,
    get_csrf,
    issue_token,
    login,
    make_context,
    upload,
    users_csv,
)
from repo_files import ROOT, source_files
from ui_helpers import app_answers, make_report, route_app, seed_client, sign_in

DOCUMENT = ROOT / "docs" / "security-review.md"
ITEMS = [
    "Authentication",
    "CSRF",
    "Uploads",
    "Formula injection",
    "XSS",
    "Secrets",
    "Pseudonymisation",
    "Retention",
    "Rate limits",
    "Resource limits",
]
ROUTERS = (
    ui_auth.router,
    ui_clients.router,
    ui_evidence.router,
    ui_profiles.router,
    ui_reports.router,
    ui_site.router,
    ui_system.router,
    api_module.router,
    api_ops.router,
    metrics.router,
)
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PARAMETER = re.compile(r"\{[a-z_]+\}")
SAMPLE = {"{control_id}": "PC-ACC-01", "{kind}": "qbr"}
HOSTILE = "<script>alert(1)</script><img src=x onerror=alert(2)>"
SECRET_PATTERNS = [
    re.compile(r"rvk_[A-Za-z0-9_-]{32,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
]
TEST_REFERENCE = re.compile(r"`(tests/[A-Za-z0-9_./-]+\.py)(?:::([A-Za-z0-9_]+))?`")


def fill(path: str) -> str:
    """A route path with a value for each parameter."""
    return PARAMETER.sub(lambda found: SAMPLE.get(found.group(0), "1"), path)


def routes(api: bool, methods: set[str]) -> list[tuple[str, str]]:
    """(method, path) of the routes of the application, API or pages.

    The routers are read directly, because FastAPI keeps an included router lazily
    and `app.routes` then holds no path for it. A route counts only when the
    application answers it, so a router that is declared but not included fails the
    length checks.
    """
    app = route_app()
    found: set[tuple[str, str]] = set()
    for source in (app, *ROUTERS):
        for route in source.routes:
            path: str = getattr(route, "path", "")
            if not path or path.startswith("/api/") is not api:
                continue
            for method in getattr(route, "methods", None) or ():
                if method in methods and app_answers(app, fill(path), method):
                    found.add((method, path))
    return sorted(found)


API_ROUTES = routes(True, {"GET", "POST", "PUT", "PATCH", "DELETE"})
PAGE_POSTS = routes(False, UNSAFE_METHODS)


async def bearer(engine: AsyncEngine) -> dict[str, str]:
    return {"Authorization": f"Bearer {await issue_token(engine)}"}


# --- 1. Authentication ---


def test_the_route_lists_are_read_from_the_application() -> None:
    assert len(API_ROUTES) >= 15
    assert ("GET", "/api/v1/export") in API_ROUTES
    assert ("DELETE", "/api/v1/schedules/{schedule_id}") in API_ROUTES
    assert len(PAGE_POSTS) >= 15
    posted = {path for _, path in PAGE_POSTS}
    assert {"/login", "/setup", "/logout", "/system/export"} <= posted
    assert "/imports/profile-editor/save" in posted


@pytest.mark.parametrize(("method", "path"), API_ROUTES)
async def test_every_api_route_refuses_a_token_that_is_not_valid(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    headers = {"Authorization": "Bearer rvk_not-a-real-token"}
    answer = await client.request(method, fill(path), headers=headers)
    assert answer.status_code == 401, (method, path)
    assert answer.headers["www-authenticate"] == "Bearer"


async def test_five_wrong_passwords_lock_the_account_even_for_the_right_one(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await create_admin(db_engine)
    for _ in range(LOCKOUT_THRESHOLD - 1):
        assert (await login(client, password=WRONG_PASSWORD)).status_code == 401
    assert (await login(client, password=WRONG_PASSWORD)).status_code == 429
    locked = await login(client)
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) > 0


async def test_a_password_over_the_length_limit_is_refused_without_a_hash(
    client: httpx.AsyncClient,
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await create_admin(db_engine)
    hashed: list[int] = []

    def counting_verify(stored_hash: str, password: str) -> bool:
        hashed.append(len(password))
        return verify_password(stored_hash, password)

    monkeypatch.setattr("app.auth.verify_password", counting_verify)
    # A wrong password within the limit runs one Argon2 check, so the counter works.
    short = await login(client, password=WRONG_PASSWORD)
    assert short.status_code == 401
    assert hashed == [len(WRONG_PASSWORD)]
    hashed.clear()
    # Over the limit it is a 401 as well, and no Argon2 check runs at all.
    answer = await login(client, password="x" * (MAX_PASSWORD_LENGTH + 1))
    assert answer.status_code == 401
    assert hashed == []


def test_the_gate_lets_in_up_to_its_limit_and_frees_a_place_on_leave() -> None:
    gate = ConcurrencyGate(2)
    assert gate.try_enter() and gate.try_enter()
    assert not gate.try_enter()
    gate.leave()
    assert gate.try_enter()
    for _ in range(4):
        gate.leave()
    # Leaving more often than entering never lets in more than the limit.
    assert [gate.try_enter() for _ in range(3)] == [True, True, False]


async def test_a_sign_in_over_the_gate_is_told_to_wait_and_nothing_is_checked(
    web_app: FastAPI, client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await create_admin(db_engine)
    csrf = await get_csrf(client, "/login")
    form = {"username": "admin", "password": PASSWORD, "csrf_token": csrf}
    baseline = await audit_baseline(db_engine)
    web_app.state.login_gate = ConcurrencyGate(0)
    busy = await client.post("/login", data=form)
    assert busy.status_code == 429
    assert busy.headers["retry-after"] == "5"
    assert "Many sign-ins" in busy.text
    assert await audit_since(db_engine, baseline) == []
    web_app.state.login_gate = ConcurrencyGate(MAX_PARALLEL_LOGINS)
    assert (await client.post("/login", data=form)).status_code == 303


async def test_the_gate_is_released_after_every_sign_in(
    web_app: FastAPI, client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await create_admin(db_engine)
    web_app.state.login_gate = ConcurrencyGate(1)
    for _ in range(3):
        wrong = await login(client, password=WRONG_PASSWORD)
        assert wrong.status_code == 401


# --- 2. CSRF ---


@pytest.mark.parametrize(("method", "path"), PAGE_POSTS)
async def test_every_state_changing_page_route_refuses_a_request_without_a_token(
    method: str, path: str
) -> None:
    transport = httpx.ASGITransport(app=route_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as browser:
        answer = await browser.request(method, fill(path), data={"field": "value"})
    assert answer.status_code == 403, (method, path)


async def test_a_bearer_header_does_not_exempt_a_page_from_the_csrf_check() -> None:
    transport = httpx.ASGITransport(app=route_app())
    headers = {"Authorization": "Bearer rvk_synthetic"}
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as browser:
        answer = await browser.post("/logout", headers=headers, data={"a": "b"})
    assert answer.status_code == 403


async def test_the_api_needs_a_token_and_not_a_csrf_token(
    client: httpx.AsyncClient,
) -> None:
    body = {"name": "Csrf Test Ltd"}
    assert (await client.post("/api/v1/clients", json=body)).status_code == 403
    wrong = {"Authorization": "Bearer rvk_wrong"}
    answer = await client.post("/api/v1/clients", json=body, headers=wrong)
    assert answer.status_code == 401


async def test_the_session_cookie_is_not_a_credential_for_the_api(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    answer = await ui_browser.post(
        "/api/v1/clients", json={"name": "Cookie Ltd"}, headers={"X-CSRF-Token": csrf}
    )
    assert answer.status_code == 401


# --- 3. Uploads ---


@pytest.fixture
async def small_uploads(
    ui_settings: Settings, db_engine: AsyncEngine, clock: FakeClock
) -> AsyncIterator[httpx.AsyncClient]:
    """The application with an upload limit of 1000 bytes."""
    app = create_app(
        replace(ui_settings, import_max_bytes=1000), engine=db_engine, clock=clock
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as browser:
        yield browser


async def test_an_upload_over_the_limit_is_413_and_one_without_a_size_is_411(
    small_uploads: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token = await bearer(db_engine)
    path = "/api/v1/clients/1/evidence"
    big = b"x" * (FORM_OVERHEAD_BYTES + 1000 + 1)
    refused = await small_uploads.post(path, headers=token, content=big)
    assert refused.status_code == 413

    async def pieces() -> AsyncIterator[bytes]:
        yield b"a,b\n"
        yield b"1,2\n"

    chunked = await small_uploads.post(path, headers=token, content=pieces())
    assert chunked.status_code == 411


async def test_the_name_of_an_uploaded_file_is_never_kept(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token = await bearer(db_engine)
    made = await ui_browser.post(
        "/api/v1/clients", headers=token, json={"name": "Upload Name Ltd"}
    )
    path = f"/api/v1/clients/{made.json()['id']}/evidence"
    form = {
        "source_code": "reference-csv",
        "captured_at": (NOW - timedelta(days=2)).isoformat(),
    }
    name = "../../etc/passwd-synthetic.csv"
    files = {"file": (name, users_csv(), "text/csv")}
    sent = await ui_browser.post(path, headers=token, data=form, files=files)
    assert sent.status_code == 201, sent.text
    assert "passwd-synthetic" not in await database_dump(db_engine)


async def test_a_file_that_is_not_text_is_refused_not_a_500(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token = await bearer(db_engine)
    made = await ui_browser.post(
        "/api/v1/clients", headers=token, json={"name": "Binary Ltd"}
    )
    path = f"/api/v1/clients/{made.json()['id']}/evidence"
    form = {
        "source_code": "reference-csv",
        "captured_at": (NOW - timedelta(days=2)).isoformat(),
    }
    data = b"user_principal_name,mfa_registered\x00\nalice,true\n"
    files = {"file": ("export.csv", data, "text/csv")}
    refused = await ui_browser.post(path, headers=token, data=form, files=files)
    assert refused.status_code == 422


# --- 4. Formula injection ---


def test_a_cell_that_would_run_as_a_formula_gets_an_apostrophe() -> None:
    for text in ("=1+1", "+44", "-5 dashes", "@sum", "\tTab", "\rReturn"):
        assert cell(text) == "'" + text
    assert cell("plain") == "plain"
    assert cell("a=b") == "a=b"
    assert cell(-5) == "-5"
    assert cell(None) == ""


async def test_the_export_defuses_a_client_name_that_starts_like_a_formula(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token = await bearer(db_engine)
    names = ["=1+1 Ltd", "+44 Ltd", "-dash Ltd", "@at Ltd"]
    for name in names:
        made = await client.post("/api/v1/clients", headers=token, json={"name": name})
        assert made.status_code == 201, made.text
    export = await client.get("/api/v1/export", headers=token)
    assert export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        text = archive.read("clients.csv").decode("utf-8")
    exported = {row[1] for row in list(csv.reader(io.StringIO(text)))[1:]}
    assert exported == {"'" + name for name in names}


# --- 5. XSS ---


async def test_a_hostile_client_name_is_escaped_on_every_page(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx, HOSTILE)
    report = await make_report(ui_browser, csrf, client_id)
    paths = [
        "/clients",
        f"/clients/{client_id}",
        f"/clients/{client_id}/checklist",
        f"/clients/{client_id}/evidence",
        f"/clients/{client_id}/reports",
        report,
        f"{report}/preview/qbr",
    ]
    for path in paths:
        page = await ui_browser.get(path)
        assert page.status_code == 200, path
        assert "<script>alert(1)" not in page.text, path
        assert "<img src=x" not in page.text, path
        policy = page.headers["content-security-policy"]
        if path.endswith("/preview/qbr"):
            # The preview forbids everything but its own inline style.
            assert policy.startswith("default-src 'none'")
            assert "script-src" not in policy
        else:
            assert "unsafe-inline" not in policy and "unsafe-eval" not in policy
    listing = await ui_browser.get("/clients")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in listing.text


def test_no_template_turns_escaping_off() -> None:
    offenders = []
    for path in (ROOT / "app").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"\|\s*safe\b|autoescape\s+false|\|\s*markup\b", text):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []
    # Trusted markup is built in two places only: the charts and the report CSS.
    builders = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "app").rglob("*.py")
        if "Markup(" in path.read_text(encoding="utf-8")
    )
    assert builders == ["app/reports/charts.py", "app/reports/render.py"]


# --- 6. Secrets ---


def test_secret_settings_stay_out_of_the_repr_of_the_settings(
    env: dict[str, str],
) -> None:
    secrets = {
        "SMTP_PASSWORD": "smtp-synthetic-password-0123",
        "METRICS_TOKEN": "metrics-synthetic-token-0123456789",
    }
    text = repr(load_settings({**env, **secrets}))
    for value in (*secrets.values(), *env.values()):
        assert value not in text


def test_a_bad_environment_is_reported_without_repeating_its_values() -> None:
    bad = {
        "SECRET_KEY": "tiny-synthetic",
        "FERNET_KEY": "not-a-key-synthetic",
        "DATABASE_URL": "mysql://user:pw-synthetic@host/db",
        "SMTP_PORT": "port-synthetic",
    }
    with pytest.raises(SettingsError) as raised:
        load_settings(bad)
    message = str(raised.value)
    for variable, value in bad.items():
        assert variable in message
        assert value not in message


async def test_a_token_and_a_password_are_stored_only_as_hashes(
    db_engine: AsyncEngine,
) -> None:
    token = await issue_token(db_engine)
    dump = await database_dump(db_engine)
    assert token not in dump
    assert hash_api_token(token) in dump
    assert PASSWORD not in dump
    assert "$argon2id$" in dump


def test_no_file_of_the_repository_holds_a_secret_that_looks_real() -> None:
    hits = []
    for path in source_files():
        text = path.read_text(encoding="utf-8")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                hits.append(f"{path.relative_to(ROOT).as_posix()}: {pattern.pattern}")
    assert hits == []


# --- 7. Pseudonymisation ---


async def test_user_names_are_replaced_before_anything_is_stored(
    db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ui_ctx, "Pseudonym Ltd")
    await upload(db_engine, ui_ctx, client_id, export_evidence(), NOW)
    dump = await database_dump(db_engine)
    for user, _ in SYNTHETIC_USERS:
        assert user not in dump
        assert user.split("@")[0] not in dump


# --- 8. Retention ---


async def test_a_kept_file_goes_when_its_retention_ends_and_with_its_client(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    ctx = make_context(settings, tmp_path, raw_retention_days=7)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    client_id = await create_test_client(db_engine, ctx, "Retention Ltd")
    await upload(db_engine, ctx, client_id, export_evidence(), NOW)
    assert ctx.files.count_client_files(client_id) == 1
    async with factory() as session, session.begin():
        removed = await purge_expired_raw(session, ctx.files, NOW + timedelta(days=8))
    assert removed == 1
    assert ctx.files.count_client_files(client_id) == 0

    other = users_csv((("zed.synthetic@example.test", True),))
    again = export_evidence(data=other, captured_at=NOW - timedelta(days=1))
    await upload(db_engine, ctx, client_id, again, NOW)
    assert ctx.files.count_client_files(client_id) == 1
    await delete_client(
        factory,
        ctx.files,
        client_id,
        confirm_name="Retention Ltd",
        actor_user_id=None,
        now=NOW,
    )
    assert ctx.files.count_client_files(client_id) == 0
    assert "Retention Ltd" not in await database_dump(db_engine)


# --- 9. Rate limits ---


async def test_the_api_refuses_a_request_over_the_limit_with_retry_after(
    web_app: FastAPI, client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token = await bearer(db_engine)
    web_app.state.api_limiter = SlidingWindowLimiter(3, 60.0)
    for _ in range(3):
        assert (await client.get("/api/v1/whoami", headers=token)).status_code == 200
    refused = await client.get("/api/v1/whoami", headers=token)
    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) >= 1


# --- 10. Resource limits ---


def test_the_resource_limits_are_the_documented_numbers(settings: Settings) -> None:
    assert MAX_BODY_BYTES == 1024 * 1024
    assert MAX_EXPORT_BYTES == 256 * 1024 * 1024
    assert MAX_PERIOD_DAYS == 400
    assert MAX_PASSWORD_LENGTH == 256
    assert API_RATE_LIMIT == 120 and API_RATE_WINDOW_SECONDS == 60.0
    assert MAX_PARALLEL_LOGINS == 4
    assert settings.import_max_bytes == 20 * 1024 * 1024
    assert settings.import_max_rows == 200_000


# --- the document itself ---


def test_the_review_document_covers_every_item_and_leaves_nothing_open() -> None:
    text = DOCUMENT.read_text(encoding="utf-8")
    for number, name in enumerate(ITEMS, start=1):
        assert f"## {number}. {name}\n" in text, name
    sections = re.split(r"^## \d+\. ", text, flags=re.MULTILINE)[1:]
    assert len(sections) == len(ITEMS)
    for section in sections:
        for label in ("**Checked:**", "**Result:**", "**Test:**"):
            assert label in section, (section.splitlines()[0], label)
    for line in text.splitlines():
        if line.startswith("|") and ("| High |" in line or "| Medium |" in line):
            assert "| Open |" not in line, line
    for number in ("1 MiB", "256 MiB", "400 days", "120 requests", "20 MiB"):
        assert number in text, number


def test_every_test_the_review_document_names_exists() -> None:
    text = DOCUMENT.read_text(encoding="utf-8")
    references = TEST_REFERENCE.findall(text)
    assert len(references) >= len(ITEMS)
    for filename, function in references:
        path = ROOT / filename
        assert path.is_file(), filename
        if function:
            assert f"def {function}(" in path.read_text(encoding="utf-8"), function
