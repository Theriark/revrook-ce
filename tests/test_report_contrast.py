"""WCAG 2 contrast of every foreground and background pair in the report stylesheet.

The brand contrast test (tests/test_brand_contrast.py) reads app/static/css/revrook.css;
this one reads the stylesheets of the reports (app/reports/report.css and print.css) the
same way. Every rule that sets a text colour sets its background-color too, so each
pair is read from the file. Body and status text need 4.5 to 1, text of 24px or larger
3 to 1; status colours and secondary text only on white; gray never as text.
"""

import re
from pathlib import Path

import pytest

REPORTS = Path(__file__).resolve().parent.parent / "app" / "reports"
STYLESHEETS = ("report.css", "print.css")
HEX = re.compile(r"#[0-9a-fA-F]{6}")
VAR = re.compile(r"var\((--[a-z0-9-]+)\)")
BODY_MINIMUM = 4.5
LARGE_MINIMUM = 3.0
LARGE_TEXT_PX = 24.0
ROOT_FONT_PX = 16.0
WHITE_ONLY = (
    "--rv-status-protected",
    "--rv-status-needs-attention",
    "--rv-status-not-protected",
    "--rv-status-not-checked",
    "--rv-text-secondary",
)
# The values of the approved brand tokens; the report stylesheet must not drift.
BRAND = {
    "--rv-charcoal": "#2d2f3a",
    "--rv-accent": "#4c5bd4",
    "--rv-stone": "#d9d6cf",
    "--rv-gray": "#8a8f98",
    "--rv-white": "#ffffff",
}


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def parse_rules(css: str) -> list[tuple[str, dict[str, str]]]:
    rules = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", strip_comments(css)):
        declarations: dict[str, str] = {}
        for part in body.split(";"):
            if ":" in part:
                name, value = part.split(":", 1)
                declarations[name.strip()] = " ".join(value.split())
        rules.append((" ".join(selector.split()), declarations))
    return rules


def load(name: str) -> list[tuple[str, dict[str, str]]]:
    return parse_rules((REPORTS / name).read_text(encoding="utf-8"))


RULES = [(name, *rule) for name in STYLESHEETS for rule in load(name)]
VARIABLES = {
    key: value
    for _, _, declarations in RULES
    for key, value in declarations.items()
    if key.startswith("--")
}


def resolve(value: str) -> str | None:
    for _ in range(10):
        match = VAR.fullmatch(value.strip())
        if match is None:
            break
        value = VARIABLES.get(match.group(1), "")
    value = value.strip()
    return value.lower() if HEX.fullmatch(value) else None


def luminance(colour: str) -> float:
    channels = []
    for start in (1, 3, 5):
        c = int(colour[start : start + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def ratio(first: str, second: str) -> float:
    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def font_px(value: str | None) -> float:
    if value is None:
        return 0.0
    match = re.fullmatch(r"([0-9.]+)(px|rem|em)", value)
    assert match is not None, f"unsupported font-size {value!r}"
    size = float(match.group(1))
    return size if match.group(2) == "px" else size * ROOT_FONT_PX


def text_rules() -> list[tuple[str, str, dict[str, str]]]:
    return [(sheet, sel, decl) for sheet, sel, decl in RULES if "color" in decl]


def pair_ids() -> list[str]:
    return [f"{sheet}:{selector}" for sheet, selector, _ in text_rules()]


def test_the_stylesheets_have_text_rules_and_the_brand_tokens() -> None:
    assert len(text_rules()) >= 20
    for token, value in BRAND.items():
        assert resolve(f"var({token})") == value, token


@pytest.mark.parametrize(
    ("sheet", "selector", "declarations"), text_rules(), ids=pair_ids()
)
def test_every_text_colour_of_a_report_has_a_background_and_enough_contrast(
    sheet: str, selector: str, declarations: dict[str, str]
) -> None:
    assert "background-color" in declarations, f"{selector} sets no background-color"
    foreground = resolve(declarations["color"])
    background = resolve(declarations["background-color"])
    assert foreground is not None, declarations["color"]
    assert background is not None, declarations["background-color"]
    large = font_px(declarations.get("font-size")) >= LARGE_TEXT_PX
    minimum = LARGE_MINIMUM if large else BODY_MINIMUM
    assert ratio(foreground, background) >= minimum, (selector, declarations)


def test_status_and_secondary_text_are_on_white_only() -> None:
    white = resolve("var(--rv-white)")
    for sheet, selector, declarations in text_rules():
        used = VAR.fullmatch(declarations["color"].strip())
        if used is not None and used.group(1) in WHITE_ONLY:
            assert resolve(declarations["background-color"]) == white, (
                sheet,
                selector,
            )
    for token in WHITE_ONLY:
        colour = resolve(f"var({token})")
        assert colour is not None and ratio(colour, "#ffffff") >= BODY_MINIMUM, token


def test_gray_is_never_text_and_violet_blue_is_never_text_on_charcoal() -> None:
    charcoal = resolve("var(--rv-charcoal)")
    for sheet, selector, declarations in text_rules():
        used = VAR.fullmatch(declarations["color"].strip())
        name = used.group(1) if used else ""
        assert name != "--rv-gray", (sheet, selector)
        if name == "--rv-accent":
            assert resolve(declarations["background-color"]) != charcoal, selector


def test_a_hex_colour_is_never_written_outside_the_token_block() -> None:
    for sheet, selector, declarations in RULES:
        if selector == ":root":
            continue
        for name, value in declarations.items():
            if name in ("color", "background-color"):
                assert HEX.search(value) is None, (sheet, selector, name, value)
