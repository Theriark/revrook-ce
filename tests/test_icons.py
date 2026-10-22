"""The icon set and its four sizes (docs/design-system.md, Icons), the marks of
the evidence sources and the brand lockup (THE-824).

Every icon is drawn by the macro of `_icons.html` at one of four named sizes, so
the icons of a kind are the same size on every page: sm inside a control, md
beside a line of text, lg the mark of a card, xl the mark of an empty state. The
stylesheet holds the values as tokens. The brand is the rook mark, drawn on
nothing, in a tile the stylesheet draws, beside the text wordmark.
"""

import re
from pathlib import Path

import pytest
from test_brand_contrast import RULES, VARIABLES

from app.sources import DEFAULT_SOURCE_ICON, SOURCE_ICONS, SOURCE_NAMES, source_icon
from app.ui.auth import templates
from app.ui.brand import BRAND_FILES

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app/ui/templates"
ICONS = (TEMPLATES / "_icons.html").read_text(encoding="utf-8")
BRAND = (TEMPLATES / "_brand.html").read_text(encoding="utf-8")
SIZES = {"sm": 18, "md": 22, "lg": 36, "xl": 48}
ICON_CALL = re.compile(r"i\.icon\(([^)]*)\)")
NAMED_CALL = re.compile(r'^"[a-z-]+"(?:, "(?:sm|md|lg|xl)")?$|^glyph, "sm"$')
EMPTY = re.compile(
    r'<div class="rv-empty([^"]*)"[^>]*>\s*\{\{ i\.icon\("[a-z-]+", "(\w+)"\)'
)


def block(selector: str) -> dict[str, str]:
    found = [decl for sel, decl in RULES if sel == selector]
    assert len(found) == 1, selector
    return found[0]


def draw(source: str, **context: object) -> str:
    return templates.env.from_string(source).render(**context)


# --- the macro ----------------------------------------------------------------


@pytest.mark.parametrize(("size", "px"), sorted(SIZES.items()))
def test_an_icon_carries_its_named_size_and_its_pixels(size: str, px: int) -> None:
    html = draw('{% import "_icons.html" as i %}{{ i.icon("home", "' + size + '") }}')
    opening = f'<svg class="rv-icon rv-icon-{size}" width="{px}" height="{px}"'
    assert html.startswith(opening)
    assert 'aria-hidden="true" focusable="false"' in html
    assert 'stroke="currentColor" stroke-width="1.75"' in html


def test_the_size_beside_a_line_of_text_is_the_default() -> None:
    html = draw('{% import "_icons.html" as i %}{{ i.icon("clients") }}')
    assert html.startswith('<svg class="rv-icon rv-icon-md" width="22" height="22"')


def test_every_icon_is_drawn_at_a_named_size_never_a_number() -> None:
    for path in sorted(TEMPLATES.glob("*.html")):
        if path.name == "_icons.html":
            continue
        for call in ICON_CALL.findall(path.read_text(encoding="utf-8")):
            assert NAMED_CALL.match(call), f"{path.name}: i.icon({call})"


def test_the_stylesheet_holds_the_scale_and_an_icon_never_sets_its_own() -> None:
    for size, px in SIZES.items():
        assert VARIABLES[f"--rv-icon-{size}"] == f"{px}px", size
    assert block(".rv-icon")["width"] == "var(--rv-icon-md)"
    for size in ("sm", "lg", "xl"):
        rule = block(f".rv-icon-{size}")
        token = f"var(--rv-icon-{size})"
        assert rule == {"width": token, "height": token}
    for selector, declarations in RULES:
        if " .rv-icon" in selector:
            assert "width" not in declarations, selector
            assert "height" not in declarations, selector


# --- where each size is used ----------------------------------------------------


def test_an_empty_state_opens_with_the_large_mark() -> None:
    found = 0
    for path in sorted(TEMPLATES.glob("*.html")):
        for classes, size in EMPTY.findall(path.read_text(encoding="utf-8")):
            found += 1
            expected = "lg" if "rv-empty-small" in classes else "xl"
            assert size == expected, f"{path.name}: {classes.strip()} draws {size}"
    assert found >= 12


def test_the_rail_draws_navigation_beside_text_and_controls_small() -> None:
    nav = (TEMPLATES / "_nav.html").read_text(encoding="utf-8")
    links = re.findall(r'class="rv-nav-link"[^>]*>\{\{ i\.icon\("[a-z-]+"\) \}\}', nav)
    assert len(links) == 7
    assert 'i.icon("signout", "sm")' in nav
    switch = (TEMPLATES / "_theme.html").read_text(encoding="utf-8")
    assert 'i.icon(glyph, "sm")' in switch
    assert block(".rv-header .rv-nav-link")["gap"] == "12px"
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert base.count('<li>{{ i.icon("check", "md") }}') == 3


def test_the_import_area_and_the_drawer_draw_the_mark_of_a_card() -> None:
    editor = (TEMPLATES / "profile_editor.html").read_text(encoding="utf-8")
    assert 'class="rv-dropzone">\n{{ i.icon("upload", "lg") }}' in editor
    result = (TEMPLATES / "_profile_editor_result.html").read_text(encoding="utf-8")
    assert result.count(', "lg") }}') == 4


# --- the marks of the sources ----------------------------------------------------


def test_every_source_has_a_mark_the_icon_set_draws() -> None:
    assert set(SOURCE_ICONS) == set(SOURCE_NAMES)
    for code, name in SOURCE_ICONS.items():
        assert f'name == "{name}"' in ICONS, code
    assert f'name == "{DEFAULT_SOURCE_ICON}"' in ICONS
    assert source_icon("entra-registration") == "cloud"
    assert source_icon("something-new") == DEFAULT_SOURCE_ICON


def test_a_source_mark_is_a_tile_beside_the_name() -> None:
    html = draw('{% import "_icons.html" as i %}{{ i.source_mark("backup-export") }}')
    assert html.startswith('<span class="rv-source-mark" aria-hidden="true">')
    assert '<svg class="rv-icon rv-icon-md"' in html
    imports = (TEMPLATES / "evidence_imports.html").read_text(encoding="utf-8")
    cell = '<th scope="row"><span class="rv-source-name">{{ i.source_mark(row.code) }}'
    assert cell in imports
    home = (TEMPLATES / "home.html").read_text(encoding="utf-8")
    assert '<ul class="rv-integrations" aria-label="The exports revrook reads">' in home
    assert home.count("i.source_mark(code)") == 1
    tile = block(".rv-source-mark")
    assert tile["background-color"] == "var(--rv-canvas)"
    assert tile["border"] == "1px solid var(--rv-line)"


# --- the brand lockup ------------------------------------------------------------


def test_the_lockup_is_the_mark_in_its_tile_beside_the_wordmark() -> None:
    html = draw(
        '{% import "_brand.html" as b %}{{ b.lockup(brand_files) }}',
        brand_files=frozenset(BRAND_FILES),
    )
    assert html.startswith('<span class="rv-lockup rv-lockup-row">')
    assert (
        '<span class="rv-mark"><img class="rv-mark-img" '
        'src="/static/brand/logo-mark-512x512.png" '
        'srcset="/static/brand/logo-mark-512x512.png 1x, '
        '/static/brand/logo-mark-1024x1024.png 2x" width="512" height="512" alt="">'
    ) in html
    assert '<span class="rv-wordmark"><span class="rv-wordmark-rev">rev</span>' in html
    stacked = draw(
        '{% import "_brand.html" as b %}{{ b.lockup(brand_files, "stack") }}',
        brand_files=frozenset({"logo-mark-512x512.png"}),
    )
    assert stacked.startswith('<span class="rv-lockup rv-lockup-stack">')
    assert "srcset" not in stacked
    bare = draw(
        '{% import "_brand.html" as b %}{{ b.lockup(brand_files) }}',
        brand_files=frozenset(),
    )
    assert "rv-mark" not in bare and "rv-wordmark" in bare
    # Only the mark, which is drawn on nothing, is used: the composed files carry
    # a surround that showed as a lighter box on the darker rail of the dark theme.
    assert "logo-mark-512x512.png" in BRAND
    assert "logo-horizontal" not in BRAND and "logo-stacked" not in BRAND


def test_the_tile_and_the_mark_have_their_sizes_in_each_place() -> None:
    assert block(".rv-mark")["width"] == "40px"
    assert block(".rv-mark")["background-color"] == "var(--rv-mark-tile)"
    assert block(".rv-mark-img")["transform"] == "translateX(13%)"
    panel = [decl for sel, decl in RULES if sel == ".rv-auth-panel .rv-mark"]
    assert [rule["width"] for rule in panel] == ["72px", "128px"]  # then from 768px
    css = (ROOT / "app/static/css/revrook.css").read_text(encoding="utf-8")
    for width, selector in (
        ("1024px", ".rv-app .rv-header .rv-mark"),
        ("768px", ".rv-auth-panel .rv-mark"),
        ("768px", ".rv-signed-out .rv-header .rv-mark"),
    ):
        pattern = rf"@media \(min-width: {width}\) \{{.*?  {re.escape(selector)} \{{"
        assert re.search(pattern, css, flags=re.DOTALL), selector
    assert "\n  .rv-app .rv-header .rv-wordmark {\n    display: none;\n  }" in css
    narrow = "\n  .rv-signed-out .rv-header .rv-wordmark {\n    display: none;\n  }"
    below = re.search(r"@media \(max-width: 1023px\) \{(.*?)\n\}\n", css, re.DOTALL)
    assert below is not None and narrow in below.group(1)
