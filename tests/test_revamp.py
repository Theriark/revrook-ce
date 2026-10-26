"""The revamp of the interface (THE-1313, REV-316): the stylesheet layer that turns
the rail to stone in the light theme and opens every page with the charcoal keep
band, the keep panel of Home (the gauge beside the rookery) and the ground of the
scenes. No database: the stylesheet, the templates and the scene script are read
as files, and the colour pairs the layer adds are checked for contrast.
"""

import re
from pathlib import Path

from app.ui.brand import ASSET_FILES, STATIC_DIR

ROOT = Path(__file__).resolve().parent.parent
CSS = (STATIC_DIR / "css/revamp.css").read_text(encoding="utf-8")
BASE = (ROOT / "app/ui/templates/base.html").read_text(encoding="utf-8")
HOME = (ROOT / "app/ui/templates/home.html").read_text(encoding="utf-8")
SCENES = (STATIC_DIR / "js/scenes.js").read_text(encoding="utf-8")
BODY_MINIMUM = 4.5
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
DECLARATION = re.compile(r"(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;")
BAND_SELECTOR = ".rv-keep,\n.rv-content > .rv-page-header,"


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def block(selector: str) -> dict[str, str]:
    """The colour tokens of the first rule that starts with `selector`."""
    css = strip_comments(CSS)
    start = css.index(selector + " {" if selector.endswith("]") else selector)
    body = css[css.index("{", start) + 1 : css.index("}", start)]
    return {name: value.lower() for name, value in DECLARATION.findall(body)}


def luminance(colour: str) -> float:
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


LIGHT = block(":root")
DARK = block(':root[data-theme="dark"]')
BAND = block(BAND_SELECTOR)


# --- the stylesheet -------------------------------------------------------------------


def test_the_layer_is_in_the_shell_after_every_other_stylesheet() -> None:
    assert "css/revamp.css" in ASSET_FILES
    link = '<link rel="stylesheet" href="/static/css/revamp.css?v={{ asset_version }}">'
    assert link in BASE
    assert BASE.index("css/scenes.css") < BASE.index(link)
    assert BASE.index("css/revrook-retest.css") < BASE.index(link)


def test_the_layer_loads_nothing_and_writes_colours_only_as_tokens() -> None:
    css = strip_comments(CSS)
    assert "url(" not in css and "@import" not in css and "http" not in css
    # Every colour literal is the value of a custom property: the rules draw with
    # roles, so the band and the themes change the tokens and nothing else.
    for line in css.splitlines():
        if HEX.search(line):
            assert line.strip().startswith("--"), line


def test_the_dark_theme_and_the_system_preference_set_the_same_tokens() -> None:
    css = strip_comments(CSS)
    media = css.split("@media (prefers-color-scheme: dark) {", 1)[1]
    system_body = media[media.index("{") + 1 : media.index("}")]
    system = {name: value.lower() for name, value in DECLARATION.findall(system_body)}
    assert system == DARK
    assert set(DARK) <= set(LIGHT)


def test_the_rail_reads_in_both_themes() -> None:
    for theme in (LIGHT, DARK):
        ground = theme["--rv-rail-ground"]
        for text in ("--rv-rail-ink", "--rv-rail-quiet"):
            assert contrast(theme[text], ground) >= BODY_MINIMUM, (text, ground)
            assert contrast(theme[text], theme["--rv-rail-hover"]) >= BODY_MINIMUM
        assert contrast(theme["--rv-rail-strong"], theme["--rv-rail-current"]) >= 7
    # The rail wordmark: rook takes the link colour of each theme
    assert contrast("#4c5bd4", LIGHT["--rv-rail-ground"]) >= BODY_MINIMUM
    assert contrast("#8b97f2", DARK["--rv-rail-ground"]) >= BODY_MINIMUM
    # Every rail rule of revrook.css draws with these tokens, given here
    rail = strip_comments(CSS).split(".rv-app .rv-header {", 1)[1].split("}", 1)[0]
    for token in ("--rv-rail:", "--rv-stone:", "--rv-stone-dim:", "--rv-white:"):
        assert token in rail, token


def test_every_word_in_the_band_reads_on_the_keep_in_both_themes() -> None:
    words = (
        "--rv-text",
        "--rv-text-secondary",
        "--rv-link",
        "--rv-status-protected",
        "--rv-status-needs-attention",
        "--rv-status-not-protected",
        "--rv-status-not-checked",
    )
    for theme in (LIGHT, DARK):
        for ground in ("--rv-keep", "--rv-keep-raised"):
            for word in words:
                ratio = contrast(BAND[word], theme[ground])
                assert ratio >= BODY_MINIMUM, (word, ground, round(ratio, 2))


def test_every_status_chip_reads_on_its_tint() -> None:
    light_status = {
        "protected": "#1b6e3c",
        "needs-attention": "#8a5a00",
        "not-protected": "#b3261e",
        "not-checked": "#5a5e6b",
    }
    for key, colour in light_status.items():
        assert contrast(colour, LIGHT[f"--rv-tint-{key}"]) >= BODY_MINIMUM, key
    for key in light_status:
        tint = DARK[f"--rv-tint-{key}"]
        assert BAND[f"--rv-tint-{key}"] == tint
        assert contrast(BAND[f"--rv-status-{key}"], tint) >= BODY_MINIMUM, key
    for key in light_status:
        assert f"span.rv-status-{key}" in CSS


def test_the_band_carries_the_header_the_tabs_and_the_problem_page() -> None:
    css = strip_comments(CSS)
    head = BAND_SELECTOR + css.split(BAND_SELECTOR, 1)[1].split("{", 1)[0]
    for selector in (
        ".rv-content > .rv-page-header",
        ".rv-content > .rv-tabs-strip",
        ".rv-content > .rv-problem",
    ):
        assert selector in head, selector
    # The battlement edge is the background of the band itself, no image
    assert "repeating-linear-gradient(90deg, var(--rv-keep)" in css


def test_the_band_runs_to_the_right_edge_of_the_window() -> None:
    # THE-1347: the band stopped at the 1200px of the content on a wide window
    css = strip_comments(CSS)
    assert ".rv-main {\n  overflow-x: clip;\n}" in css
    layer = css.split(".rv-content > .rv-page-header::before,", 1)[1].split("}")[0]
    assert "inset: 0 -100vw 0 0;" in layer and "z-index: -1;" in layer
    tabs = css.split(".rv-content > .rv-tabs-strip {", 1)[1].split("}")[0]
    assert "fill 0 / 0 / 0 100vw" in tabs


def test_motion_stays_off_under_reduced_motion() -> None:
    assert "@media (prefers-reduced-motion: reduce)" in CSS
    assert "transition:" not in strip_comments(CSS).split("prefers-reduced")[0]


# --- Home --------------------------------------------------------------------------


def test_home_puts_the_gauge_beside_the_rookery_in_the_keep() -> None:
    rookery = HOME.split('id="rookery"', 1)[1].split("</section>", 1)[0]
    panel = rookery.split('<div class="rv-keep rv-keep-panel" id="keep-panel">', 1)[1]
    assert panel.index('id="portfolio-gauge"') < panel.index("rookery-scene")
    assert rookery.index("keep-panel") < rookery.index('id="drivers-summary"')
    # The ring is drawn for the eye; its number and words are text beside it
    ring = '<svg viewBox="0 0 120 120" width="168" height="168" aria-hidden="true"'
    assert ring in panel
    assert '<span class="rv-gauge-number">{{ mean.earned_text }}</span>' in panel
    assert "so this is a lower bound" in panel
    assert "No score yet" in panel


def test_home_lays_the_dashboard_in_two_rows_and_keeps_every_part() -> None:
    first = HOME.split('<div class="rv-dash-row', 2)
    assert len(first) == 3
    # The trend chart takes the wider column of its row: its drawing is 640 wide
    assert first[1].startswith(' rv-dash-row-trend">')
    assert 'id="needs-attention"' in first[1] and 'id="trend"' in first[1]
    assert 'id="domains"' in first[2] and 'id="recent-changes"' in first[2]
    assert '<div class="rv-two">' not in HOME
    # The page stays one image (the sparkline): the gauge is hidden from the
    # accessibility tree, the bars are the drivers macro
    assert HOME.count('role="img"') == 1


# --- the scenes ---------------------------------------------------------------------


def test_the_scene_takes_its_ground_from_the_stage_and_adds_depth() -> None:
    assert 'getPropertyValue("--rv-scene-ground")' in SCENES
    assert "renderer.setClearColor(ground, 1);" in SCENES
    assert "new THREE.Fog(ground," in SCENES
    assert "scene.fog.near = home.distance" in SCENES
    assert "--rv-scene-ground: var(--rv-keep);" in CSS


def test_the_scene_takes_the_new_ground_after_a_theme_switch() -> None:
    # THE-1347: the ground was read once, so a switch of theme left the old band
    apply = SCENES.split("function applyGround() {", 1)[1].split("}", 1)[0]
    for step in (
        "groundOf(root)",
        "renderer.setClearColor(next, 1);",
        "scene.fog.color.setHex(next);",
        "sky.groundColor.setHex(next);",
        "floor.material.color.setHex(next);",
        "invalidate();",
    ):
        assert step in apply, step
    assert 'attributeFilter: ["data-theme"]' in SCENES
    assert 'matchMedia("(prefers-color-scheme: dark)")' in SCENES
    assert "themeWatcher.disconnect();" in SCENES.split("function dispose() {", 1)[1]


# --- the THE-1314 baseline defects --------------------------------------------------


def test_a_control_names_its_sources_and_folds_the_library_rule() -> None:
    body = (ROOT / "app/ui/templates/_control_body.html").read_text(encoding="utf-8")
    checked = body.split('id="checked"', 1)[1].split("</section>", 1)[0]
    # The plain result leads; the library's letters and field names are folded
    assert checked.index("rv-result-detail") < checked.index("rv-rule-more")
    assert '{{ read_from|join(", ") }}' in checked
    folded = checked.split('<details class="rv-rule-more">', 1)[1]
    assert '<p class="rv-rule">{{ control.rule.text }}</p>' in folded
    page = (ROOT / "app/ui/clients.py").read_text(encoding="utf-8")
    assert "library.source_codes.get(code, code) for code in control.sources" in page


def test_long_lists_show_twelve_rows_on_a_phone_and_every_row_on_demand() -> None:
    for name, table, words in (
        ("evidence_imports.html", "items", "items"),
        ("evidence_explorer.html", "explorer-controls", "controls"),
    ):
        page = (ROOT / "app/ui/templates" / name).read_text(encoding="utf-8")
        link = f'<p class="rv-table-more"><a href="#{table}">Show all '
        assert link in page and f"{words}</a></p>" in page, name
        assert page.index(f'id="{table}"') < page.index(link)
    phone = strip_comments(CSS).split("@media (max-width: 767px) {", 1)[1]
    assert "tbody tr:nth-child(n + 13) {\n    display: none;" in phone
    assert ":target tbody tr:nth-child(n + 13) {\n    display: grid;" in phone
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);" in phone


def test_the_checklist_domains_have_a_heading_style() -> None:
    assert ".rv-checklist .rv-group-row th {" in CSS
    assert "main .rv-checklist tbody tr.rv-group-row {" in CSS


def test_the_numbers_under_a_chart_keep_their_words_whole() -> None:
    # The founder saw "Insufficient evidence" cut in the table under the score
    # chart: at 390px the cell was 61px wide and the band broke a few letters a
    # line. On a phone each report is a card; wider, a word and a date stay whole.
    chart = (ROOT / "app/ui/templates/_chart.html").read_text(encoding="utf-8")
    table = chart.split('<details class="rv-chart-data">', 1)[1].split("</table>")[0]
    assert '<table class="rv-table-cards rv-trend-table">' in table
    for label in ("Report date", "Score", "Band"):
        assert f'<td data-label="{label}"' in table
    css = strip_comments(CSS)
    assert ".rv-chart-data .rv-table-scroll td {\n  overflow-wrap: break-word;" in css
    assert ".rv-chart-data td a {\n  white-space: nowrap;" in css
