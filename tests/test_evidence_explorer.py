"""The Evidence Explorer preview (docs/evidence-explorer-preview.md): the view model,
the page (the companies ring without a client, a client's evidence wall with one),
the JSON the wall reads, the vendored three.js build and the fallbacks.

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
    COUNTED_LABELS,
    LABELS,
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
from app.ui.dashboard import posture_of
from app.ui.explorer import (
    DATA_PATH,
    EXPLORER_ASSETS,
    EXPLORER_VERSION,
    PATH,
    explorer_version,
    page_context,
)
from app.ui.explorer_view import (
    WORST_FIRST,
    ExplorerCounts,
    adapters_of,
    build_explorer,
    build_portfolio,
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
CARD_SCRIPT = (STATIC_DIR / "js/scene-card.js").read_text(encoding="utf-8")
CSS = (STATIC_DIR / "css/evidence-explorer.css").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "app/ui/templates/evidence_explorer.html").read_text(
    encoding="utf-8"
)
UNREACHABLE = "postgresql+asyncpg://revrook:unused@127.0.0.1:1/revrook"
HEX_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b")
DIGEST = re.compile(r"[0-9a-f]{12}")
NODE_ROW = re.compile(r'<tr data-node="(source|control):([^"]+)"')
CLIENT_ROW = re.compile(r'<tr data-node="client:(\d+)"')
CONTROL_CARD = re.compile(r'<template id="control-card-([^"]+)">(.*?)</template>', re.S)
CARD_PAIR = re.compile(r'<li data-client="(\d+)" data-label="([a-z-]+)">')
FILTER = re.compile(
    r'data-status="([a-z-]+)" aria-pressed="(true|false)">[^<]+ \((\d+)\)</button>'
)
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


def portfolio_for(*names: str):
    """The companies ring of worked clients, ids 7, 8, ... in the order given."""
    clients = []
    for index, name in enumerate(names):
        view = build_view(
            report_clients.snapshot_bytes(LIBRARY, name),
            LIBRARY,
            report_clients.context_for(name),
        )
        posture = posture_of(7 + index, report_clients.NAMES[name], view, None, 3)
        clients.append((posture, view.rows))
    return build_portfolio(LIBRARY, clients, {7: 40}, NOW)


def render_page(view, clients, companies=None) -> str:
    context = page_context(clients, view, companies)
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
    # Every source a control reads has an importer, or is the public DNS check,
    # which revrook runs itself; the mail controls read it.
    read = {code for codes in adapters.values() for code in codes}
    assert read - importers == {"dns-check"}
    assert "dns-check" in adapters["PC-EML-01"] and "dns-check" in adapters["PC-EML-03"]


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


def test_the_companies_ring_has_every_control_and_every_pair() -> None:
    ring = portfolio_for("A", "B")
    assert len(ring.controls) == len(LIBRARY.controls) == 51
    assert [client.posture.client_id for client in ring.clients] == [7, 8]
    assert [client.size for client in ring.clients] == [40, 0]
    for client in ring.clients:
        assert sum(client.counts) == 51 and len(client.counts) == len(LABELS)
    pairs = 0
    for control in ring.controls:
        assert {pair.client_id for pair in control.pairs} == {7, 8}
        assert sum(control.counts) == len(control.pairs) == 2
        # The tile takes the worst label, and the card lists the worst first.
        ranks = [WORST_FIRST.index(pair.label) for pair in control.pairs]
        assert ranks == sorted(ranks) and control.worst == control.pairs[0].label
        pairs += len(control.pairs)
    # A link per pair except the not applicable ones, counted per status.
    assert [label for label, _ in ring.links] == list(COUNTED_LABELS)
    not_applicable = sum(c.counts[LABELS.index(NOT_APPLICABLE)] for c in ring.controls)
    assert sum(count for _, count in ring.links) == pairs - not_applicable
    # Without a client read, every control is still a tile, not checked.
    empty = build_portfolio(LIBRARY, [], {}, NOW)
    assert len(empty.controls) == 51 and not empty.clients
    assert {control.worst for control in empty.controls} == {NOT_CHECKED}
    assert all(count == 0 for _, count in empty.links)


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


def test_the_companies_ring_is_read_from_the_page_and_its_card_cloned() -> None:
    # Nothing fetched: the rows of the tables and the lists of the card templates.
    for needed in (
        "function readCompanies(page)",
        'page.querySelectorAll("#explorer-companies tr[data-node]")',
        'page.querySelectorAll("#explorer-controls tr[data-node]")',
        'template.content.querySelectorAll("[data-client]")',
        "data = companies ? readCompanies(document) : await loadData(url);",
        'const CARD_URL = "./scene-card.js" + new URL(import.meta.url).search;',
        "({ sceneCard } = await import(CARD_URL));",
        "card.open(entry.card, entry.top, camera, keyed);",
        # A link per pair in its status, hidden by its filter, faint until chosen,
        # gone when another node is chosen.
        "label: pair.label,",
        "bundles[key].mesh.visible = shown.has(key);",
        "setAlpha(link, !focus ? LINK_OPACITY.faint : on ? LINK_OPACITY.lit"
        " : selected ? 0 : LINK_OPACITY.dim);",
        "if (shown.has(link.label) && link.ends.indexOf(id) >= 0) {",
        'button.getAttribute("aria-pressed") === "true" ? "false" : "true"',
        # The keys of the ring: step, open, close, and the brackets turn it.
        "ArrowLeft: () => step(-1),",
        "Enter: () => open(),",
        "Escape: () => leave(),",
        '"[": () => turnBy(-TURN_STEP),',
        "window.location.assign(entry.href)",
        "scene.traverse(disposeObject);",
    ):
        assert needed in SCRIPT, needed
    for forbidden in FORBIDDEN_IN_SCRIPT:
        assert forbidden not in CARD_SCRIPT, forbidden
    assert "source.cloneNode(true)" in CARD_SCRIPT
    assert "keep && keep.contains(target)" in CARD_SCRIPT


def body_of(name: str) -> str:
    """The text of the function `name` of the scene script, up to the closing brace
    at its own indent."""
    start = SCRIPT.index(f"function {name}(")
    line = SCRIPT.rfind("\n", 0, start) + 1
    indent = SCRIPT[line:start]
    return SCRIPT[start : SCRIPT.index(f"\n{indent}}}\n", start)]


def test_the_offices_of_the_ring_are_the_kenney_models_with_the_built_fallback() -> (
    None
):
    # The ring reads the model of every client's office once it is shown (the seed
    # is the client's id, as on Home's street); office.js builds an office in code
    # when its model failed. The blocks of a client's wall stay built in code.
    for needed in (
        "({ officeBuilding, office, loadModels, officeModel } = await import(",
        'officeModel(client.score, clientSeed(client, index)) : ""',
        'return Number(client.id.replace(/^client:/, "")) || index + 7;',
        "const built = office(THREE, city, {",
        "score: client.score,",
        "seed: clientSeed(client, index),",
        "const built = officeBuilding(THREE, {\n      width: 0.5,",
    ):
        assert needed in SCRIPT, needed
    assert SCRIPT.index("await import(THREE_URL)") < SCRIPT.index(
        "city = await loadModels("
    )


def test_the_links_of_the_ring_are_tubes_bundled_per_domain() -> None:
    # Thin tubes, few segments, one merged mesh per status (one draw each), each
    # through the hub above its control's domain.
    radius = re.search(r"const TUBE_RADIUS = ([0-9.]+);", SCRIPT)
    assert radius and 0.012 <= float(radius.group(1)) <= 0.02
    segments = re.search(r"const TUBE_SEGMENTS = (\d+);", SCRIPT)
    sides = re.search(r"const TUBE_SIDES = (\d+);", SCRIPT)
    assert segments and int(segments.group(1)) <= 24
    assert sides and int(sides.group(1)) <= 6
    for needed in (
        "new THREE.TubeGeometry(curve, TUBE_SEGMENTS, TUBE_RADIUS, TUBE_SIDES, false)",
        "[office.top, hubs.get(entry.control.domain), entry.top]",
        "const geometry = mergeTubes(THREE, tubes[key]);",
        "vertexColors: true, transparent: true, depthWrite: false",
    ):
        assert needed in SCRIPT, needed
    # Each tube is freed once merged; a pair is no longer a THREE.Line of its own.
    assert "tube.dispose();" in body_of("mergeTubes")
    assert "new THREE.Line(" not in SCRIPT.split("const links = [];", 1)[1]


def test_the_flow_moves_only_on_shown_not_protected_links_and_never_reduced() -> None:
    flowing = body_of("flowing")
    assert "!options.reducedMotion" in flowing and "flow.active.length" in flowing
    paint = body_of("paint")
    assert 'shown.has("not-protected")' in paint
    assert "!selected || link.ends.indexOf(selected) >= 0" in paint
    assert 'path: pair.label === "not-protected"' in SCRIPT
    # Frames go on only while something moves and the stage can be seen; the flow
    # alone draws about 30 a second.
    frame = body_of("frame")
    assert "if (turning() || tween || (flowing() && live())) {" in frame
    assert "now - lastDraw >= FLOW_FRAME_MS" in frame
    assert "return !hidden && inView && !lost;" in body_of("live")
    # A change to reduced motion ends a glide where it was going.
    assert "target.copy(tween.to.target);" in body_of("applyMotion")


def test_the_names_over_the_ring_are_an_aria_hidden_overlay_of_plain_text() -> None:
    for needed in (
        'overlay.setAttribute("aria-hidden", "true");',
        'overlay.className = "rv-explorer-labels";',
        "strong.textContent = name;",
        "small.textContent = extra;",
        "canvas.after(overlay);",
        # Placed on every frame drawn, hidden behind the camera or when crowded.
        "item.behind = box.z > 1 || box.z < -1;",
        'item.element.classList.toggle("is-hidden", !show);',
    ):
        assert needed in SCRIPT, needed
    assert "placeLabels();" in body_of("render")
    # Kept inside the stage.
    place = body_of("placeLabels")
    assert "clamp(box.left, 4, Math.max(4, width - item.width - 4))" in place
    for needed in (
        ".rv-explorer-labels {",
        "pointer-events: none;",
        "font-size: var(--rv-fs-xs);",
        ".rv-explorer-label.is-hidden {",
        ".rv-explorer-label.is-faded {",
    ):
        assert needed in CSS, needed
    reduced = CSS.split("@media (prefers-reduced-motion: reduce)", 1)[1]
    assert ".rv-explorer-label {" in reduced and "transition: none;" in reduced


def test_the_home_view_of_the_ring_holds_its_rim_its_bands_and_every_name() -> None:
    # The rim of the floor (outside the widest band) is a corner of the fit, the
    # names count as their boxes (or only their points sideways on a phone), and
    # the point the camera looks at is lowered until the ring stands mid-stage.
    assert "FLOOR_RADIUS * Math.cos(a), 0, FLOOR_RADIUS * Math.sin(a)" in SCRIPT
    resize = body_of("resize")
    assert 'named: companies ? "boxes" : false' in resize
    assert 'pose.named = "anchors";' in resize
    assert "lift: companies" in resize and "target.copy(center);" in resize
    fit = body_of("fitDistance")
    assert "if (pose.lift) {" in fit and "pose.target.y = target.y;" in fit
    assert "span.wide <= edge && span.high <= edge && span.low >= -edge" in fit
    extent = body_of("extent")
    assert "labelBox(item, width, height, middle)" in extent
    # The same box places a name and fits the view, so the two cannot disagree.
    assert "labelBox(item, width, height, middle)" in body_of("placeLabels")
    assert 'reach: extent(probes, companies ? "anchors" : false),' in SCRIPT


def test_a_choice_frames_its_node_and_escape_returns_to_the_whole_ring() -> None:
    choice = body_of("frameChoice")
    assert "const near = related(entry.id);" in choice
    assert (
        "glide({ pitch: home.pitch, distance: home.distance, target: center },"
        " FOCUS_MS);"
    ) in choice
    assert "frameChoice(entry);" in body_of("select")
    glide = body_of("glide")
    assert "if (options.reducedMotion) {" in glide and "tween = null;" in glide
    reset = body_of("reset")
    assert "focused = false;" in reset and "target.copy(center);" in reset


def test_the_finish_is_built_in_code_and_every_new_resource_is_freed() -> None:
    # An environment map from a small room of panels: no file, no addon.
    environment = body_of("environmentMap")
    assert "new THREE.PMREMGenerator(renderer)" in environment
    assert "pmrem.fromScene(room, 0.04)" in environment
    assert "pmrem.dispose();" in environment and "box.dispose();" in environment
    assert "examples/" not in SCRIPT and "addons" not in SCRIPT
    # The glow: additive sprites with a canvas radial gradient, never picked.
    assert "createRadialGradient" in body_of("glowTexture")
    assert "blending: THREE.AdditiveBlending," in SCRIPT
    assert "sprite.raycast = () => {};" in SCRIPT
    # Shadows drawn once (nothing moves), again after a restored context, as is the
    # environment map; fog fades the far rim.
    assert "renderer.shadowMap.autoUpdate = false;" in SCRIPT
    assert "PCFSoftShadowMap;" not in SCRIPT
    restored = SCRIPT.split('"webglcontextrestored",', 1)[1].split("{ signal }", 1)[0]
    assert "renderer.shadowMap.needsUpdate = true;" in restored
    assert "environment = environmentMap(THREE, renderer);" in restored
    assert "new THREE.Fog(GROUND" in SCRIPT
    # dispose() frees the canvas texture, the environment map and the overlay too.
    dispose = body_of("dispose")
    for needed in (
        "scene.traverse(disposeObject);",
        "glow.dispose();",
        "environment.dispose();",
        "scene.environment = null;",
        "overlay.remove();",
    ):
        assert needed in dispose, needed
    # The sectors stand clearly apart and carry their names.
    gap = re.search(r"const COMPANY_GAP = ([0-9.]+);", SCRIPT)
    wall_gap = re.search(r"const SECTOR_GAP = ([0-9.]+);", SCRIPT)
    assert gap and wall_gap and float(gap.group(1)) >= 2 * float(wall_gap.group(1))
    assert "const gap = data.companies ? COMPANY_GAP : SECTOR_GAP;" in SCRIPT
    assert 'domainName: row.getAttribute("data-domain-name") || "",' in SCRIPT


def test_the_scene_reaches_the_tables_and_follows_the_motion_setting() -> None:
    # The tables sit below the card, so their rows and buttons are found on the page.
    assert 'page.querySelectorAll(".rv-explorer-pick")' in SCRIPT
    assert 'page.querySelectorAll("tr[data-node]")' in SCRIPT
    assert "root.querySelectorAll" not in SCRIPT
    # A focusable stage that answers keys is an application, not a still image.
    assert 'setAttribute("role", "application")' in SCRIPT
    assert '"role", "img"' not in SCRIPT
    # A change of the reduced-motion setting reaches a wall already drawn.
    assert 'motionQuery.addEventListener("change"' in SCRIPT
    assert "wall.applyMotion()" in SCRIPT
    # A refusal shows only its plain sentence, a title no doubled full stop.
    assert 'typeof body.detail === "string"' in SCRIPT
    assert r'control.title.replace(/\.$/, "")' in SCRIPT
    assert ".rv-explorer-hover:empty" in CSS


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
    assert html.count('aria-current="page"') == 2  # the rail and the breadcrumb
    assert "Evidence Explorer</span></a>" in html
    # The view chooser offers the companies ring first; the wall is not it.
    assert '<option value="">All companies</option>' in html
    assert 'data-explorer-view="companies"' not in html

    empty = render_page(None, [])
    assert structure_problems(empty) == []
    assert 'id="explorer-no-clients"' in empty
    assert 'href="/clients">Add a client' in empty
    # The shell's own scripts are on every page; the scene module is not loaded here.
    assert 'id="explorer"' not in empty and "evidence-explorer.js" not in empty


# --- the routes (PostgreSQL) ----------------------------------------------------------


def test_the_companies_ring_page_has_its_tables_cards_and_filters() -> None:
    ring = portfolio_for("A", "B")
    companies = {
        "portfolio": ring,
        "unread": [],
        "card_focus": {},
        "card_refresh": {7: 2, 8: 0},
    }
    html = render_page(None, [(7, "Alpha"), (8, "Beta")], companies)
    assert structure_problems(html) == []
    assert 'data-explorer-view="companies"' in html and "data-explorer-url" not in html
    assert '<option value="" selected>All companies</option>' in html
    assert html.count('aria-current="page"') == 2  # the rail and the breadcrumb
    # The record: a row per client and per control, each with its Show in scene.
    assert CLIENT_ROW.findall(html) == ["7", "8"]
    assert len(NODE_ROW.findall(html)) == 51
    assert html.count('class="rv-button-quiet rv-button-small rv-explorer-pick"') == 53
    assert 'id="explorer-sources"' not in html and 'id="explorer-status"' not in html
    # The company card of each client, as on Home, and a card per control listing
    # every client with its status; their links open in the drawer of the page.
    for client_id in (7, 8):
        assert html.count(f'<template id="client-card-{client_id}">') == 1
    assert 'href="/clients/7/evidence">Exports to refresh: 2</a>' in html
    cards = CONTROL_CARD.findall(html)
    assert len(cards) == 51
    for control_id, body in cards:
        assert [client for client, _ in CARD_PAIR.findall(body)] != []
        for client in ("7", "8"):
            link = f'href="/clients/{client}/controls/{control_id}" data-drawer>'
            assert link in body, (control_id, client)
    assert 'id="control-drawer"' in html
    # One filter per linked status, its count the links of the cards; at first the
    # not protected and the needs attention links show.
    pairs = [label for _, body in cards for _, label in CARD_PAIR.findall(body)]
    filters = FILTER.findall(html)
    assert [key for key, _, _ in filters] == [label.key for label in COUNTED_LABELS]
    for key, pressed, count in filters:
        assert int(count) == pairs.count(key), key
        assert (pressed == "true") == (key in ("not-protected", "needs-attention"))
    assert len(STATUS_SPAN.findall(html)) == len(STATUS.findall(html))
    assert "<style" not in html.split("<main", 1)[1] and " style=" not in html
    # Each control row names its domain, for the floor of its sector.
    names = {domain.code: domain.name for domain in LIBRARY.domains}
    for control in ring.controls:
        assert control.domain_name == names[control.domain]
    assert html.count('data-domain-name="Identity and MFA"') == sum(
        1 for control in ring.controls if control.domain == "ACC"
    )


async def test_the_page_and_its_data_show_the_same_client(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    # The link of the evidence page opens that client's wall, as before.
    page = await ui_browser.get(f"{PATH}?client_id={client_id}")
    html = page.text
    assert page.status_code == 200 and structure_problems(html) == []
    assert 'data-explorer-view="companies"' not in html
    assert f'data-explorer-url="{DATA_PATH}?client_id={client_id}"' in html
    assert html.count('<tr data-node="control:') == 51
    assert len(STATUS_SPAN.findall(html)) == len(STATUS.findall(html))
    assert page.headers["cache-control"] == "no-store, no-transform"

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


async def test_without_a_client_the_page_is_the_companies_ring(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    first = await seed_client(db_engine, ui_ctx)
    second = await seed_client(db_engine, ui_ctx, "Second Client Ltd")
    for path in (PATH, f"{PATH}?client_id="):
        page = await ui_browser.get(path)
        html = page.text
        assert page.status_code == 200 and structure_problems(html) == [], path
        assert 'data-explorer-view="companies"' in html
        assert "data-explorer-url" not in html
        assert sorted(int(found) for found in CLIENT_ROW.findall(html)) == sorted(
            [first, second]
        )
        assert len(NODE_ROW.findall(html)) == 51
        assert len(CONTROL_CARD.findall(html)) == 51
        for client_id in (first, second):
            assert f'<template id="client-card-{client_id}">' in html
        assert len(STATUS_SPAN.findall(html)) == len(STATUS.findall(html))
    # The seeded clients fail some controls: the default filters have links to show.
    shown = [int(n) for _, pressed, n in FILTER.findall(html) if pressed == "true"]
    assert sum(shown) > 0


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
