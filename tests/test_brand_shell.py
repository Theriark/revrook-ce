"""The brand layout: titles, logo, favicons, static files and CSP-safe templates."""

import re
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import make_engine
from app.main import create_app
from app.settings import Settings
from app.ui.auth import templates
from app.ui.brand import BRAND_DIR, BRAND_FILES, STATIC_DIR, available_brand_files
from helpers import create_admin, login

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "app/ui/templates"
TEMPLATE_NAMES = sorted(path.name for path in TEMPLATE_DIR.glob("*.html"))
UNREACHABLE = "postgresql+asyncpg://revrook:unused@127.0.0.1:1/revrook"
LINK_ATTRIBUTE = re.compile(r'\b(?:src|href|srcset|action)="([^"]*)"')
TITLE = re.compile(r"<title>(.*?)</title>")
DENSITIES = frozenset({"1x", "2x"})
LOGO_TAG = '<img class="rv-logo" src="/static/brand/logo-horizontal-1200x400.png"'
WORDMARK = (
    '<span class="rv-wordmark"><span class="rv-wordmark-rev">rev</span>'
    '<span class="rv-wordmark-rook">rook</span></span>'
)


def make_client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def title_of(html: str) -> str:
    match = TITLE.search(html)
    assert match is not None, "the page has no title"
    return match.group(1)


def render_login(brand_files: frozenset[str]) -> str:
    return templates.get_template("login.html").render(
        title="Sign in",
        errors=[],
        username="",
        csrf_token="synthetic",
        brand_files=brand_files,
    )


def template_source(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def test_the_layout_templates_exist() -> None:
    for name in ("base.html", "home.html", "login.html", "setup.html"):
        assert name in TEMPLATE_NAMES


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_templates_have_no_inline_script_style_or_handler(name: str) -> None:
    source = template_source(name)
    assert "<style" not in source
    assert not re.search(r"\sstyle=", source)
    assert not re.search(r"\son[a-z]+=", source)
    assert "javascript:" not in source
    for script in re.findall(r"<script[^>]*>", source):
        assert ' src="/static/' in script, f"inline script: {script}"
    assert not re.search(r"<script[^>]*>[^<\s]", source)


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_templates_load_nothing_from_another_origin(name: str) -> None:
    source = template_source(name)
    assert "http://" not in source
    assert "https://" not in source
    for value in LINK_ATTRIBUTE.findall(source):
        for url in value.replace(",", " ").split():
            if url in DENSITIES:
                continue
            assert url.startswith(("/", "#")), f"{url} is not a same-origin path"
            assert not url.startswith("//"), f"{url} is protocol-relative"


def test_the_header_shows_the_approved_logo_and_favicons() -> None:
    html = render_login(frozenset(BRAND_FILES))
    assert LOGO_TAG in html
    assert "/static/brand/logo-horizontal-2400x800.png 2x" in html
    assert 'height="36"' in html
    assert 'alt="revrook"' in html
    assert 'rel="icon" type="image/png" sizes="32x32"' in html
    assert 'href="/static/brand/favicon-32x32.png"' in html
    assert 'rel="apple-touch-icon" sizes="180x180"' in html
    assert 'href="/static/brand/favicon-180x180.png"' in html
    assert WORDMARK not in html
    assert title_of(html) == "Sign in - revrook"


def test_without_the_brand_files_the_text_wordmark_is_shown() -> None:
    html = render_login(frozenset())
    assert "/static/brand/" not in html
    assert WORDMARK in html


def test_the_layout_links_the_stylesheets_script_and_footer() -> None:
    html = render_login(frozenset())
    assert 'href="/static/vendor/pico/pico.min.css"' in html
    assert 'href="/static/css/revrook.css"' in html
    assert '<script src="/static/vendor/htmx/htmx.min.js" defer></script>' in html
    assert 'data-theme="light"' in html
    assert 'class="rv-footer"' in html
    assert "not a certification, audit or attestation" in html


def test_only_approved_brand_files_are_in_the_brand_folder() -> None:
    present = {p.name for p in BRAND_DIR.iterdir()} if BRAND_DIR.is_dir() else set()
    assert present <= set(BRAND_FILES), present - set(BRAND_FILES)
    assert available_brand_files() == frozenset(present)


def test_available_brand_files_lists_only_existing_files(tmp_path: Path) -> None:
    (tmp_path / "favicon-32x32.png").write_bytes(b"synthetic")
    (tmp_path / "unrelated.png").write_bytes(b"synthetic")
    assert available_brand_files(tmp_path) == frozenset({"favicon-32x32.png"})
    assert available_brand_files(tmp_path / "missing") == frozenset()


@pytest.mark.parametrize(
    ("path", "media_type"),
    [
        ("/static/css/revrook.css", "text/css"),
        ("/static/vendor/pico/pico.min.css", "text/css"),
        ("/static/vendor/htmx/htmx.min.js", "javascript"),
    ],
)
async def test_static_files_are_served_with_the_security_headers(
    settings: Settings, path: str, media_type: str
) -> None:
    app = create_app(settings, engine=make_engine(UNREACHABLE))
    async with make_client(app) as client:
        response = await client.get(path)
    assert response.status_code == 200
    assert media_type in response.headers["content-type"]
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert (STATIC_DIR / path.removeprefix("/static/")).is_file()


async def test_the_first_run_page_uses_the_layout(client: httpx.AsyncClient) -> None:
    response = await client.get("/setup")
    assert response.status_code == 200
    assert title_of(response.text) == "Create the administrator - revrook"
    assert 'href="/static/css/revrook.css"' in response.text
    assert 'class="rv-header"' in response.text


async def test_the_login_and_home_pages_use_the_layout(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await create_admin(db_engine)
    page = await client.get("/login")
    assert title_of(page.text) == "Sign in - revrook"
    assert 'class="rv-header"' in page.text
    signed_in = await login(client)
    assert signed_in.status_code == 303
    home = await client.get("/")
    assert home.status_code == 200
    assert title_of(home.text) == "Home - revrook"
    assert 'aria-current="page"' in home.text
    assert "Signed in as admin" in home.text
