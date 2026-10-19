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
from app.ui.brand import (
    ASSET_FILES,
    BRAND_DIR,
    BRAND_FILES,
    STATIC_DIR,
    asset_version,
    available_brand_files,
)
from helpers import create_admin, login

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "app/ui/templates"
TEMPLATE_NAMES = sorted(path.name for path in TEMPLATE_DIR.glob("*.html"))
UNREACHABLE = "postgresql+asyncpg://revrook:unused@127.0.0.1:1/revrook"
LINK_ATTRIBUTE = re.compile(r'\b(?:src|href|srcset|action)="([^"]*)"')
TEMPLATE_EXPRESSION = re.compile(r"\{\{.*?\}\}")
TITLE = re.compile(r"<title>(.*?)</title>")
DENSITIES = frozenset({"1x", "2x"})
LOGO_TAG = '<img class="rv-logo" src="/static/brand/logo-horizontal-1200x400.png"'
WORDMARK = (
    '<span class="rv-wordmark"><span class="rv-wordmark-rev">rev</span>'
    '<span class="rv-wordmark-rook">rook</span></span>'
)
# The digest of the stylesheets and scripts of this checkout (the `v` query).
VERSION = asset_version()
DIGEST = re.compile(r"[0-9a-f]{12}")


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
        csrf_token="test-token",
        brand_files=brand_files,
    )


def template_source(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def script_tag(path: str) -> str:
    return f'<script src="{path}?v={VERSION}" defer></script>'


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
        # A template expression is one placeholder, so its spaces do not split a path.
        value = TEMPLATE_EXPRESSION.sub("0", value)
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
    assert f'href="/static/vendor/pico/pico.min.css?v={VERSION}"' in html
    assert f'href="/static/css/revrook.css?v={VERSION}"' in html
    assert script_tag("/static/vendor/htmx/htmx.min.js") in html
    assert script_tag("/static/js/revrook.js") in html
    assert 'data-theme="light"' in html
    assert 'class="rv-footer"' in html
    assert "not a certification, audit or attestation" in html


def test_every_stylesheet_and_script_link_carries_the_asset_version() -> None:
    # A cache in front of the installation keeps a static file for hours, so an
    # address without the digest could serve an old stylesheet with a new page.
    html = render_login(frozenset(BRAND_FILES))
    linked = re.findall(r'(?:href|src)="(/static/(?:css|js|vendor)/[^"]+)"', html)
    assert len(linked) == len(ASSET_FILES)
    expected = [f"/static/{name}?v={VERSION}" for name in ASSET_FILES]
    assert sorted(linked) == sorted(expected)
    # The brand files are the approved assets and never change: no version.
    for brand in re.findall(r'(?:href|src|srcset)="(/static/brand/[^" ]+)', html):
        assert "?" not in brand, brand


def test_the_asset_version_is_a_digest_of_the_stylesheets_and_scripts(
    tmp_path: Path,
) -> None:
    assert DIGEST.fullmatch(VERSION), VERSION
    assert asset_version(STATIC_DIR) == VERSION
    for name in ASSET_FILES:
        assert (STATIC_DIR / name).is_file(), name
    copy = tmp_path / "static"
    for name in ASSET_FILES:
        target = copy / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((STATIC_DIR / name).read_bytes())
    assert asset_version(copy) == VERSION
    # A changed file gives a new address, and a missing one still gives a version.
    (copy / "css/revrook.css").write_text("body { margin: 0; }", encoding="utf-8")
    changed = asset_version(copy)
    assert changed != VERSION and DIGEST.fullmatch(changed)
    (copy / "css/revrook.css").unlink()
    missing = asset_version(copy)
    assert missing not in (VERSION, changed) and DIGEST.fullmatch(missing)


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


async def test_a_versioned_address_serves_the_same_file(settings: Settings) -> None:
    app = create_app(settings, engine=make_engine(UNREACHABLE))
    async with make_client(app) as client:
        response = await client.get(f"/static/css/revrook.css?v={VERSION}")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    expected = (STATIC_DIR / "css/revrook.css").read_text(encoding="utf-8")
    assert response.text == expected


async def test_the_first_run_page_uses_the_layout(client: httpx.AsyncClient) -> None:
    response = await client.get("/setup")
    assert response.status_code == 200
    assert title_of(response.text) == "Create the administrator - revrook"
    assert f'href="/static/css/revrook.css?v={VERSION}"' in response.text
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
