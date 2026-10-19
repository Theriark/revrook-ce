"""Inline SVG charts, written here (no chart library).

A chart is a horizontal bar chart: one labelled bar per row on a scale of 0 to 100.
It carries a title and a description for screen readers, and every chart is followed
in the report by a table of the same numbers (the data-table fallback), so nothing is
shown only as a picture. Sizes are whole numbers computed from exact fractions, so a
chart is the same bytes every time.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from math import floor

from markupsafe import Markup, escape

WIDTH = 640
LABEL_WIDTH = 230
TRACK_WIDTH = 300
ROW_HEIGHT = 30
BAR_HEIGHT = 16
TOP = 8
HUNDRED = Fraction(100)


@dataclass(frozen=True)
class Bar:
    """One row: a label, a value from 0 to 100 (None: no bar), the text beside it."""

    label: str
    value: Fraction | None
    text: str


def bar_width(value: Fraction | None) -> int:
    """The width in pixels of a bar on the track (0 for no value, capped at 100)."""
    if value is None or value <= 0:
        return 0
    return floor(min(value, HUNDRED) * TRACK_WIDTH / HUNDRED)


def bar_chart(
    chart_id: str, title: str, description: str, bars: Sequence[Bar]
) -> Markup:
    """The SVG of a bar chart. `chart_id` is unique within the report."""
    height = TOP * 2 + ROW_HEIGHT * len(bars)
    parts = [
        f'<svg class="chart" role="img" viewBox="0 0 {WIDTH} {height}" '
        f'width="{WIDTH}" height="{height}" xmlns="http://www.w3.org/2000/svg" '
        f'aria-labelledby="{escape(chart_id)}-title {escape(chart_id)}-desc">',
        f'<title id="{escape(chart_id)}-title">{escape(title)}</title>',
        f'<desc id="{escape(chart_id)}-desc">{escape(description)}</desc>',
    ]
    for index, bar in enumerate(bars):
        top = TOP + index * ROW_HEIGHT
        text_y = top + BAR_HEIGHT - 3
        track_x = LABEL_WIDTH
        parts.append(
            f'<text class="chart-label" x="0" y="{text_y}">{escape(bar.label)}</text>'
        )
        parts.append(
            f'<rect class="chart-track" x="{track_x}" y="{top}" '
            f'width="{TRACK_WIDTH}" height="{BAR_HEIGHT}"/>'
        )
        width = bar_width(bar.value)
        if width:
            parts.append(
                f'<rect class="chart-bar" x="{track_x}" y="{top}" '
                f'width="{width}" height="{BAR_HEIGHT}"/>'
            )
        value_x = track_x + TRACK_WIDTH + 10
        parts.append(
            f'<text class="chart-value" x="{value_x}" y="{text_y}">'
            f"{escape(bar.text)}</text>"
        )
    parts.append("</svg>")
    return Markup("".join(parts))
