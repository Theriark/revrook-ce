"""WCAG 2 contrast of every foreground and background pair in revrook.css.

revrook.css declares a background-color in every rule that sets a text colour,
so each pair is read from the file itself. Body and status text need 4.5 to 1;
text of 24px or larger needs 3 to 1. The Pico CSS variable overrides are checked
as the pairs Pico draws them in.
"""

import re
from pathlib import Path

import pytest

CSS_FILE = Path(__file__).resolve().parent.parent / "app/static/css/revrook.css"
BODY_MINIMUM = 4.5
LARGE_MINIMUM = 3.0
LARGE_TEXT_PX = 24.0
ROOT_FONT_PX = 16.0
HEX = re.compile(r"#[0-9a-fA-F]{6}")
VAR = re.compile(r"var\((--[a-z0-9-]+)\)")

# Pico CSS variable pairs: (text variable, background variable).
PICO_PAIRS = (
    ("--pico-color", "--pico-background-color"),
    ("--pico-h1-color", "--pico-background-color"),
    ("--pico-h2-color", "--pico-background-color"),
    ("--pico-h3-color", "--pico-background-color"),
    ("--pico-muted-color", "--pico-background-color"),
    ("--pico-primary", "--pico-background-color"),
    ("--pico-primary-hover", "--pico-background-color"),
    ("--pico-primary-inverse", "--pico-primary-background"),
    ("--pico-primary-inverse", "--pico-primary-hover-background"),
    ("--pico-form-element-color", "--pico-form-element-background-color"),
    (
        "--pico-form-element-placeholder-color",
        "--pico-form-element-background-color",
    ),
)
# Pico variables that never colour text.
NON_TEXT_PICO_PARTS = ("background", "border", "focus", "underline")

# Reference ratios from the approved brand guide (two decimals).
BRAND_GUIDE_RATIOS = (
    ("--rv-charcoal", "--rv-white", 13.30),
    ("--rv-charcoal", "--rv-stone", 9.16),
    ("--rv-white", "--rv-accent", 5.59),
    ("--rv-accent", "--rv-stone", 3.85),
    ("--rv-gray", "--rv-charcoal", 4.09),
    ("--rv-gray", "--rv-white", 3.25),
    ("--rv-accent", "--rv-charcoal", 2.38),
    ("--rv-gray", "--rv-stone", 2.24),
)
STATUS_TOKENS = (
    "--rv-status-protected",
    "--rv-status-needs-attention",
    "--rv-status-not-protected",
    "--rv-status-not-checked",
)
# Tokens that may only be text on white.
WHITE_ONLY_TOKENS = (*STATUS_TOKENS, "--rv-text-secondary")


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def parse_rules(css: str) -> list[tuple[str, dict[str, str]]]:
    """(selector, declarations) for every rule; the file has no nested blocks."""
    rules = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", strip_comments(css)):
        declarations: dict[str, str] = {}
        for part in body.split(";"):
            if ":" in part:
                name, value = part.split(":", 1)
                declarations[name.strip()] = " ".join(value.split())
        rules.append((" ".join(selector.split()), declarations))
    return rules


def custom_properties(rules: list[tuple[str, dict[str, str]]]) -> dict[str, str]:
    found: dict[str, str] = {}
    for _, declarations in rules:
        for name, value in declarations.items():
            if name.startswith("--"):
                found[name] = value
    return found


def resolve(value: str, variables: dict[str, str]) -> str | None:
    """The #rrggbb colour a value stands for, or None if it is not a colour."""
    for _ in range(10):
        match = VAR.fullmatch(value.strip())
        if match is None:
            break
        value = variables.get(match.group(1), "")
    value = value.strip()
    return value.lower() if HEX.fullmatch(value) else None


def relative_luminance(colour: str) -> float:
    channels = []
    for start in (1, 3, 5):
        c = int(colour[start : start + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted(
        (relative_luminance(first), relative_luminance(second)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def font_size_px(value: str | None) -> float:
    if value is None:
        return 0.0
    match = re.fullmatch(r"([0-9.]+)(px|rem|em)", value)
    assert match is not None, f"unsupported font-size {value!r}"
    size = float(match.group(1))
    return size if match.group(2) == "px" else size * ROOT_FONT_PX


RULES = parse_rules(CSS_FILE.read_text(encoding="utf-8"))
VARIABLES = custom_properties(RULES)


def token_of(value: str) -> str | None:
    match = VAR.fullmatch(value.strip())
    return match.group(1) if match else None


def text_rules() -> list[tuple[str, dict[str, str]]]:
    return [(selector, decl) for selector, decl in RULES if "color" in decl]


def declared_pairs() -> list[tuple[str, str, str, float]]:
    """(where, foreground value, background value, minimum ratio) of every pair."""
    pairs = []
    for selector, declarations in text_rules():
        large = font_size_px(declarations.get("font-size")) >= LARGE_TEXT_PX
        pairs.append(
            (
                selector,
                declarations["color"],
                declarations["background-color"],
                LARGE_MINIMUM if large else BODY_MINIMUM,
            )
        )
    for text, background in PICO_PAIRS:
        pairs.append(
            (
                f"{text} on {background}",
                f"var({text})",
                f"var({background})",
                BODY_MINIMUM,
            )
        )
    return pairs


def pair_id(pair: tuple[str, str, str, float]) -> str:
    return pair[0]


def test_the_stylesheet_has_text_rules_and_tokens() -> None:
    assert len(text_rules()) >= 10
    for token in ("--rv-charcoal", "--rv-accent", "--rv-stone", "--rv-gray"):
        assert resolve(f"var({token})", VARIABLES) is not None


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("--rv-charcoal", "#2d2f3a"),
        ("--rv-accent", "#4c5bd4"),
        ("--rv-stone", "#d9d6cf"),
        ("--rv-gray", "#8a8f98"),
        ("--rv-white", "#ffffff"),
    ],
)
def test_the_approved_palette_is_unchanged(token: str, expected: str) -> None:
    assert resolve(f"var({token})", VARIABLES) == expected


@pytest.mark.parametrize(("foreground", "background", "expected"), BRAND_GUIDE_RATIOS)
def test_the_formula_reproduces_the_brand_guide_ratios(
    foreground: str, background: str, expected: float
) -> None:
    first = resolve(f"var({foreground})", VARIABLES)
    second = resolve(f"var({background})", VARIABLES)
    assert first is not None and second is not None
    assert round(contrast_ratio(first, second), 2) == expected


def test_every_rule_with_a_text_colour_declares_its_background() -> None:
    missing = [s for s, decl in text_rules() if "background-color" not in decl]
    assert missing == [], f"rules without background-color: {missing}"


@pytest.mark.parametrize("pair", declared_pairs(), ids=pair_id)
def test_every_declared_pair_meets_the_wcag_minimum(
    pair: tuple[str, str, str, float],
) -> None:
    where, foreground, background, minimum = pair
    first = resolve(foreground, VARIABLES)
    second = resolve(background, VARIABLES)
    assert first is not None, f"{where}: {foreground} is not a declared colour"
    assert second is not None, f"{where}: {background} is not a declared colour"
    ratio = contrast_ratio(first, second)
    assert ratio >= minimum, f"{where}: {ratio:.2f} is below {minimum}"


def test_every_pico_text_variable_is_checked() -> None:
    checked = {text for text, _ in PICO_PAIRS} | {bg for _, bg in PICO_PAIRS}
    for name, value in VARIABLES.items():
        if not name.startswith("--pico-") or resolve(value, VARIABLES) is None:
            continue
        if any(part in name for part in NON_TEXT_PICO_PARTS):
            continue
        assert name in checked, f"{name} colours text but has no contrast pair"
    for text, background in PICO_PAIRS:
        assert text in VARIABLES, f"{text} is not overridden in revrook.css"
        assert background in VARIABLES, f"{background} is not overridden"


def test_every_status_colour_and_secondary_text_is_used_and_checked() -> None:
    used = {token_of(decl["color"]) for _, decl in text_rules()}
    for token in WHITE_ONLY_TOKENS:
        assert token in VARIABLES
        assert token in used, f"{token} has no declared text pair"


def test_forbidden_pairs_never_appear() -> None:
    for selector, declarations in text_rules():
        foreground = token_of(declarations["color"])
        background = token_of(declarations["background-color"])
        if foreground == "--rv-gray":
            assert background not in ("--rv-white", "--rv-stone"), selector
        if foreground == "--rv-accent":
            assert background != "--rv-charcoal", selector
        if foreground == "--rv-accent" and background == "--rv-stone":
            assert font_size_px(declarations.get("font-size")) >= LARGE_TEXT_PX
        if foreground in WHITE_ONLY_TOKENS:
            assert background == "--rv-white", selector


def test_the_stylesheet_loads_nothing_external() -> None:
    css = strip_comments(CSS_FILE.read_text(encoding="utf-8"))
    assert "@import" not in css
    assert "url(" not in css
    assert "http" not in css


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [("#000000", "#ffffff", 21.0), ("#ffffff", "#ffffff", 1.0)],
)
def test_contrast_ratio_matches_the_wcag_end_points(
    first: str, second: str, expected: float
) -> None:
    assert contrast_ratio(first, second) == pytest.approx(expected)
