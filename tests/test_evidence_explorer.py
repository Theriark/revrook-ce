"""The Evidence Explorer preview (docs/evidence-explorer-preview.md): the view model,
the page, the JSON it serves, the vendored three.js build and the fallbacks.

The view model tests use the worked clients of the report tests and need no
database. The page tests need PostgreSQL (DATABASE_URL) and are skipped without it.
The files tests check what the browser is given: the pinned library (hash for hash),
the stylesheet (tokens only), the scene script (no eval, nothing from outside, the
handlers every fallback needs) and the template (no inline script, every status an
icon and its words).
"""

import hashlib
import json
import re
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.checks.library import load_library
from app.db import make_engine
from app.evidence.service import EvidenceContext
from app.importers.registry import build_default_registry
from app.main import create_app
from app.reports.status import (
    NEEDS_ATTENTION,
    NOT_APPLICABLE,
    NOT_CHECKED,
    NOT_PROTECTED,
    PROTECTED,
    StatusLabel,
)
from app.reports.view import build_view
from app.settings import Settings
from app.sources import SOURCE_NAMES
from app.ui.auth import templates
from app.ui.brand import BRAND_FILES, STATIC_DIR
from app.ui.explorer import (
    DATA_PATH,
    EXPLORER_ASSETS,
    EXPLORER_VERSION,
    PATH,
    explorer_version,
    page_context,
)
from app.ui.explorer_view import (
    ExplorerCounts,
    adapters_of,
    build_explorer,
    explorer_json,
    verdict_text,
)
from app.ui.viewmodels import CURRENT, MISSING, STALE, SourceRow
from helpers import NOW, create_admin, create_test_client
from html_structure import structure_problems
from tools import report_clients
from ui_helpers import NAME, STATUS, STATUS_SPAN, seed_client, sign_in

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = load_library()
VENDOR = STATIC_DIR / "vendor/three"
PINNED = json.loads((VENDOR / "PINNED.json").read_text(encoding="utf-8"))
SCRIPT = (STATIC_DIR / "js/evidence-explorer.js").read_text(encoding="utf-8")
CSS = (STATIC_DIR / "css/evidence-explorer.css").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "app/ui/templates/evidence_explorer.html").read_text(
    encoding="utf-8"
)
UNREACHABLE = "postgresql+asyncpg://revrook:unused@127.0.0.1:1/revrook"
HEX_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b")
DIGEST = re.compile(r"[0-9a-f]{12}")
NODE_ROW = re.compile(r'<tr data-node="(source|control):([^"]+)"')
# What every fallback of the scene script needs, and what it must never do.
REQUIRED_IN_SCRIPT = (
    '"/static/vendor/three/three.module.js"',
    'getContext("webgl2")',
    "prefers-reduced-motion: reduce",
    "webglcontextlost",
    "webglcontextrestored",
    "visibilitychange",
    "IntersectionObserver",
    "ResizeObserver",
    "pagehide",
    "renderer.dispose()",
    "forceContextLoss()",
    "geometry.dispose()",
    "material.dispose()",
    "root.revrookExplorer",
    'credentials: "same-origin"',
)
FORBIDDEN_IN_SCRIPT = ("eval(", "new Function", "innerHTML", "document.write", "http")
DYNAMIC_CODE = ("new Function(", "eval(", "document.write(", "importScripts(")
ALL_LABELS = (PROTECTED, NEEDS_ATTENTION, NOT_PROTECTED, NOT_CHECKED, NOT_APPLICABLE)
LABEL_KEYS = {label.key for label in ALL_LABELS}
PLACEHOLDER_TOKEN = "x" * 32


def report_view(name: str) -> tuple:
    view = build_view(
        report_clients.snapshot_bytes(LIBRARY, name),
        LIBRARY,
        report_clients.context_for(name),
    )
    return view.rows, view.snapshot.as_of


def sources_for(rows: tuple) -> list[SourceRow]:
    """A source row for every adapter the rows read: the first two current, the
    third stale, the rest never imported."""
    adapters = adapters_of(LIBRARY)
    codes = sorted({code for row in rows for code in adapters[row.control_id]})
    made: list[SourceRow] = []
    for index, code in enumerate(codes):
        if index < 2:
            state, captured, exports = CURRENT, NOW - timedelta(days=3), 2
        elif index == 2:
            state, captured, exports = STALE, NOW - timedelta(days=50), 1
        else:
            state, captured, exports = MISSING, None, 0
        expires = None if captured is None else captured + timedelta(days=35)
        made.append(
            SourceRow(
                code=code,
                name=SOURCE_NAMES.get(code, code),
                state=state,
                captured_at=captured,
                expires_at=expires,
                exports=exports,
                refresh=None,
            )
        )
    return sorted(made, key=lambda item: (item.name, item.code))


def explorer_for(name: str = "A"):
    rows, as_of = report_view(name)
    name_of = report_clients.NAMES[name]
    return build_explorer(LIBRARY, 7, name_of, as_of, rows, sources_for(rows))


def render_page(view, clients) -> str:
    context = page_context(clients, view)
    return templates.get_template("evidence_explorer.html").render(
        **context,
        user=SimpleNamespace(username="admin"),
        csrf_token=PLACEHOLDER_TOKEN,
        brand_files=frozenset(BRAND_FILES),
    )


def make_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


# --- the view model -------------------------------------------------------------------


def test_every_control_reads_known_adapters_and_manual_ones_read_none() -> None:
    adapters = adapters_of(LIBRARY)
    importers = set(build_default_registry().source_codes())
    assert set(adapters) == {control.id for control in LIBRARY.controls}
    assert "entra-registration" in adapters["PC-ACC-01"]
    for control in LIBRARY.controls:
        if control.manual_only:
            assert adapters[control.id] == (), control.id
        for code in adapters[control.id]:
            assert code in SOURCE_NAMES, code
    # Every adapter a control reads has an importer, except the two the release
    # notes list as missing (their controls stay Not checked).
    read = {code for codes in adapters.values() for code in codes}
    assert read - importers <= {"secure-score", "exchange-export"} or read <= importers


def test_the_view_links_only_both_ends_and_counts_every_control() -> None:
    view = explorer_for("A")
    codes = {source.code for source in view.sources}
    assert len(view.controls) == len(LIBRARY.controls) == 51
    assert [domain.code for domain in view.domains] == [d.code for d in LIBRARY.domains]
    assert sum(domain.controls for domain in view.domains) == 51
    for control in view.controls:
        assert set(control.sources) <= codes, control.control_id
        assert control.label in LABEL_KEYS, control.control_id
        assert control.label_icon in {"check", "alert", "cross", "question", "dash"}
    for source in view.sources:
        for control_id in source.controls:
            control = next(c for c in view.controls if c.control_id == control_id)
            assert source.code in control.sources
    counts = view.counts
    total = counts.protected + counts.needs_attention + counts.not_protected
    assert total + counts.not_checked + counts.not_applicable == 51
    assert counts.links == sum(len(s.controls) for s in view.sources) > 0
    assert counts.sources == len(view.sources) == counts.current + counts.to_refresh
    assert counts.current == 2
    assert view.ruleset == f"{LIBRARY.ruleset_id} {LIBRARY.version}"
    assert view.as_of.endswith("+00:00")


def test_the_json_is_plain_data_the_scene_can_read() -> None:
    view = explorer_for("B")
    data = json.loads(json.dumps(explorer_json(view)))
    assert data["client_id"] == 7 and data["client_name"] == report_clients.NAMES["B"]
    assert {"sources", "controls", "domains", "counts", "verdict"} <= set(data)
    assert data["verdict"]["key"] in LABEL_KEYS - {"not-applicable"}
    first = data["controls"][0]
    assert set(first) == {
        "control_id",
        "title",
        "domain",
        "gate",
        "label",
        "label_text",
        "label_icon",
        "evidence_state",
        "evidence_at",
        "sources",
    }
    pillar = data["sources"][0]
    assert set(pillar) == {
        "code",
        "name",
        "state",
        "state_text",
        "state_icon",
        "captured_at",
        "expires_at",
        "exports",
        "controls",
    }


def test_the_verdict_names_the_worst_thing_first() -> None:
    view = explorer_for("A")

    def with_counts(**changes: int) -> str:
        base = ExplorerCounts(0, 0, 0, 0, 0, 3, 1, 2, 9)
        return verdict_text(replace(view, counts=replace(base, **changes)))

    assert with_counts(not_protected=3, needs_attention=2) == (
        "3 controls not protected"
    )
    assert with_counts(not_protected=1) == "1 control not protected"
    assert with_counts(needs_attention=2, protected=5) == "2 controls need attention"
    assert with_counts(needs_attention=1) == "1 control needs attention"
    assert with_counts(protected=40, not_checked=6) == (
        "40 of 46 counted controls protected"
    )
    assert with_counts(protected=46) == "All 46 counted controls protected"
    assert with_counts(not_checked=51) == "Nothing has been checked yet"
    assert isinstance(view.verdict, StatusLabel)


def test_the_assets_of_the_preview_have_their_own_version(tmp_path: Path) -> None:
    assert DIGEST.fullmatch(EXPLORER_VERSION)
    assert explorer_version(STATIC_DIR) == EXPLORER_VERSION
    copy = tmp_path / "static"
    for name in EXPLORER_ASSETS:
        target = copy / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((STATIC_DIR / name).read_bytes())
    assert explorer_version(copy) == EXPLORER_VERSION
    (copy / "js/evidence-explorer.js").write_text("// changed", encoding="utf-8")
    assert explorer_version(copy) != EXPLORER_VERSION


# --- the vendored library -------------------------------------------------------------


def test_the_pinned_three_build_is_the_one_recorded_hash_for_hash() -> None:
    assert PINNED["name"] == "three" and PINNED["version"] == "0.186.1"
    assert PINNED["license"] == "MIT"
    assert PINNED["tarballIntegrity"].startswith("sha512-")
    assert set(PINNED["files"]) == {"three.module.js", "three.core.js", "LICENSE"}
    for name, record in PINNED["files"].items():
        data = (VENDOR / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == record["sha256"], name
        assert len(data) == record["bytes"], name
    present = {path.name for path in VENDOR.iterdir()}
    assert present == set(PINNED["files"]) | {"PINNED.json"}


def test_the_vendored_build_is_three_r186_under_mit_and_runs_no_dynamic_code() -> None:
    module = (VENDOR / "three.module.js").read_text(encoding="utf-8")
    core = (VENDOR / "three.core.js").read_text(encoding="utf-8")
    licence = (VENDOR / "LICENSE").read_text(encoding="utf-8")
    assert "REVISION = '186'" in core
    assert "from './three.core.js'" in module
    for text in (module, core):
        assert "SPDX-License-Identifier: MIT" in text
        for forbidden in DYNAMIC_CODE:
            assert forbidden not in text, forbidden
    assert "Permission is hereby granted" in licence
    assert "three.js" in licence.lower()


@pytest.mark.parametrize(
    ("path", "media_type"),
    [
        ("/static/vendor/three/three.module.js", "javascript"),
        ("/static/vendor/three/three.core.js", "javascript"),
        ("/static/vendor/three/PINNED.json", "json"),
        ("/static/js/evidence-explorer.js", "javascript"),
        ("/static/css/evidence-explorer.css", "text/css"),
    ],
)
async def test_the_files_of_the_scene_are_served_under_the_strict_policy(
    settings: Settings, path: str, media_type: str
) -> None:
    app = create_app(settings, engine=make_engine(UNREACHABLE))
    async with make_client(app) as client:
        response = await client.get(path)
    assert response.status_code == 200
    assert media_type in response.headers["content-type"]
    policy = response.headers["content-security-policy"]
    assert "default-src 'self'" in policy
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy
    assert response.headers["x-content-type-options"] == "nosniff"


# --- the script, the stylesheet and the template --------------------------------------


def test_the_scene_script_has_every_fallback_and_nothing_from_outside() -> None:
    for needed in REQUIRED_IN_SCRIPT:
        assert needed in SCRIPT, needed
    for forbidden in FORBIDDEN_IN_SCRIPT:
        assert forbidden not in SCRIPT, forbidden
    assert (STATIC_DIR / "vendor/three/three.module.js").is_file()
    # Status is shape and colour: each label has its own build, and the no-WebGL
    # branch returns before the library is imported.
    for label in ("needs-attention", "not-protected", "not-checked", "not-applicable"):
        assert f'label === "{label}"' in SCRIPT, label
    assert SCRIPT.index("supportsWebGL2()") < SCRIPT.index("await import(THREE_URL)")


def test_the_stylesheet_draws_with_tokens_only_and_respects_reduced_motion() -> None:
    assert HEX_LITERAL.search(CSS) is None
    assert "prefers-reduced-motion: reduce" in CSS
    assert "aspect-ratio: 16 / 9;" in CSS and "aspect-ratio: 4 / 3;" in CSS
    assert "touch-action: pan-y pinch-zoom;" in CSS
    assert "background-color: var(--rv-charcoal);" in CSS
    assert "url(" not in CSS and "@import" not in CSS


def test_the_template_loads_the_scene_as_a_module_and_keeps_the_tables_first() -> None:
    script = '<script type="module" src="/static/js/evidence-explorer.js?v='
    assert script + '{{ explorer_version }}"></script>' in TEMPLATE
    link = '<link rel="stylesheet" href="/static/css/evidence-explorer.css?v='
    assert link + '{{ explorer_version }}">' in TEMPLATE
    assert 'data-explorer-url="{{ data_url }}"' in TEMPLATE
    assert "The scene needs script and WebGL 2" in TEMPLATE
    assert TEMPLATE.index('id="explorer-sources"') < TEMPLATE.index("<script")
    assert 'aria-live="polite"' in TEMPLATE
    assert "<style" not in TEMPLATE and " style=" not in TEMPLATE


def test_the_page_renders_with_every_status_as_an_icon_and_its_words() -> None:
    view = explorer_for("C")
    html = render_page(view, [(7, view.client_name), (8, "Other Client")])
    assert structure_problems(html) == []
    assert html.count('<tr data-node="control:') == 51
    assert html.count('<tr data-node="source:') == len(view.sources)
    assert len(STATUS_SPAN.findall(html)) == len(STATUS.findall(html))
    assert f'<option value="7" selected>{view.client_name}</option>' in html
    assert 'id="explorer-no-clients"' not in html
    assert "Manual evidence (no export)" in html
    assert f"?v={EXPLORER_VERSION}" in html
    assert html.count('aria-current="page"') == 1
    assert "Evidence Explorer</span></a>" in html

    empty = render_page(None, [])
    assert structure_problems(empty) == []
    assert 'id="explorer-no-clients"' in empty
    assert 'href="/clients">Add a client' in empty
    assert 'id="explorer"' not in empty and "<script" not in empty


# --- the routes (PostgreSQL) ----------------------------------------------------------


async def test_the_page_and_its_data_show_the_same_client(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    page = await ui_browser.get(PATH)
    html = page.text
    assert page.status_code == 200 and structure_problems(html) == []
    assert f'data-explorer-url="{DATA_PATH}?client_id={client_id}"' in html
    assert html.count('<tr data-node="control:') == 51
    assert len(STATUS_SPAN.findall(html)) == len(STATUS.findall(html))
    assert page.headers["cache-control"] == "no-store"

    data = await ui_browser.get(f"{DATA_PATH}?client_id={client_id}")
    assert data.status_code == 200
    assert "application/json" in data.headers["content-type"]
    assert data.headers["cache-control"] == "no-store"
    body = data.json()
    assert body["client_id"] == client_id and body["client_name"] == NAME
    assert len(body["controls"]) == 51 and body["counts"]["links"] > 0
    codes = {source["code"] for source in body["sources"]}
    assert {"device-inventory", "backup-export"} <= codes
    # The seeded backup export is 100 days old: that source is not current.
    backup = next(s for s in body["sources"] if s["code"] == "backup-export")
    assert backup["state"] != "protected" and backup["controls"]
    for control in body["controls"]:
        assert set(control["sources"]) <= codes
    # The page lists the same rows the JSON carries.
    rows = {(kind, key) for kind, key in NODE_ROW.findall(html)}
    assert rows == {("source", s["code"]) for s in body["sources"]} | {
        ("control", c["control_id"]) for c in body["controls"]
    }


async def test_a_bad_or_unknown_client_is_refused_as_a_page_and_as_json(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    await create_test_client(db_engine, ui_ctx)
    not_a_number = await ui_browser.get(f"{PATH}?client_id=abc")
    assert not_a_number.status_code == 422
    assert "whole number" in not_a_number.text
    unknown = await ui_browser.get(f"{PATH}?client_id=999999")
    assert unknown.status_code == 404 and "no such client" in unknown.text
    as_json = await ui_browser.get(f"{DATA_PATH}?client_id=999999")
    assert as_json.status_code == 404
    assert as_json.json() == {"detail": "There is no such client."}
    bad_json = await ui_browser.get(f"{DATA_PATH}?client_id=-1")
    assert bad_json.status_code == 422 and "detail" in bad_json.json()


async def test_without_clients_the_page_is_an_empty_state_and_the_data_a_404(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await sign_in(ui_browser, db_engine)
    page = await ui_browser.get(PATH)
    assert page.status_code == 200 and structure_problems(page.text) == []
    assert 'id="explorer-no-clients"' in page.text
    data = await ui_browser.get(DATA_PATH)
    assert data.status_code == 404
    assert data.json() == {"detail": "There are no clients yet."}


async def test_the_data_needs_a_signed_in_user(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await create_admin(db_engine)
    plain = await ui_browser.get(DATA_PATH)
    assert plain.status_code == 303 and plain.headers["location"] == "/login"
    htmx = await ui_browser.get(DATA_PATH, headers={"HX-Request": "true"})
    assert htmx.status_code == 200 and htmx.headers["HX-Redirect"] == "/login"
    page = await ui_browser.get(PATH)
    assert page.status_code == 303 and page.headers["location"] == "/login"
