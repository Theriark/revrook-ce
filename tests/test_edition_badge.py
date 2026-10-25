"""The edition badge beside the wordmark in the bar (THE-1133, REV-280).

Seen in the live acceptance on Development at 768px: the brand column beside the
user block was 228px, the lockup shrank and the "Community Edition" badge lay
over "rook" of the wordmark. The rule is in app/static/css/revrook-retest.css.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "app/static/css/revrook.css").read_text(encoding="utf-8")
FOLLOW_UP = (ROOT / "app/static/css/revrook-retest.css").read_text(encoding="utf-8")
BASE = (ROOT / "app/ui/templates/base.html").read_text(encoding="utf-8")
# Tile 40, gap 10, wordmark 88 at 24px, gap 12 and the badge 149 (measured on
# Development at 768px and 1000px).
LOCKUP_AND_BADGE_PX = 299


def bar_block() -> str:
    found = re.findall(
        r"@media \(max-width: 1023px\) \{(.*?)\n\}\n", FOLLOW_UP, re.DOTALL
    )
    blocks = [block for block in found if "container: rv-brand" in block]
    assert len(blocks) == 1
    return blocks[0]


def test_the_badge_and_the_lockup_share_the_brand_link_in_the_bar() -> None:
    brand = BASE[BASE.index('<header class="rv-header" id="rail">') :]
    brand = brand[: brand.index("</a>")]
    assert "b.lockup(brand_files)" in brand
    assert '<span class="rv-edition">Community Edition</span>' in brand


def test_the_lockup_keeps_its_width_and_the_brand_column_is_measured() -> None:
    block = bar_block()
    brand = r"\.rv-app \.rv-header \.rv-brand \{[^}]*"
    assert re.search(brand + r"container: rv-brand / inline-size;", block)
    assert re.search(r"\.rv-app \.rv-header \.rv-lockup \{[^}]*flex: none;", block)


def test_the_badge_hides_where_the_column_cannot_hold_both() -> None:
    narrow = re.search(
        r"@container rv-brand \(max-width: (\d+)px\) \{\s*"
        r"\.rv-app \.rv-edition \{([^}]*)\}",
        bar_block(),
    )
    assert narrow is not None and "display: none;" in narrow.group(2)
    assert int(narrow.group(1)) >= LOCKUP_AND_BADGE_PX


def test_the_rail_and_the_phone_rules_are_unchanged() -> None:
    # Below 600px revrook.css hides the badge outright; from 1024px the rail
    # stacks it under the lockup, so the container exists only in the bar.
    phone = re.search(
        r"@media \(max-width: 599px\) \{\n  \.rv-app \.rv-edition \{([^}]*)\}", CSS
    )
    assert phone is not None and "display: none" in phone.group(1)
    outside = FOLLOW_UP.replace(bar_block(), "")
    assert "container:" not in outside and "@container" not in outside
