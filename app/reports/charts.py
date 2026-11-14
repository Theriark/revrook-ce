"""Inline SVG charts, written here (no chart library).

A chart is a horizontal bar chart (one labelled bar per row on a scale of 0 to 100),
a status bar (one segment per status, as wide as its share of the controls) or the
score dial of the cover. Each carries a title and a description for screen readers,
and its numbers are also printed as text or as a table beside it, so nothing is
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


MIX_HEIGHT = 22
MIX_GAP = 2


def segment_widths(counts: Sequence[int]) -> list[int]:
    """The width of each segment of a status bar: its share of WIDTH less the gaps
    between the segments that are drawn; the last one drawn takes what rounding left.
    """
    drawn = [index for index, count in enumerate(counts) if count > 0]
    widths = [0] * len(counts)
    if not drawn:
        return widths
    room = WIDTH - MIX_GAP * (len(drawn) - 1)
    total = sum(counts)
    for index in drawn[:-1]:
        widths[index] = max(1, counts[index] * room // total)
    widths[drawn[-1]] = room - sum(widths)
    return widths


def status_bar(
    chart_id: str, title: str, description: str, parts: Sequence[tuple[str, int]]
) -> Markup:
    """One bar split by status. `parts` are (status key, controls) in display order;
    the key names the class of the segment (report.css gives it its colour).
    """
    svg = [
        f'<svg class="mix" role="img" viewBox="0 0 {WIDTH} {MIX_HEIGHT}" '
        f'width="{WIDTH}" height="{MIX_HEIGHT}" preserveAspectRatio="none" '
        'xmlns="http://www.w3.org/2000/svg" '
        f'aria-labelledby="{escape(chart_id)}-title {escape(chart_id)}-desc">',
        f'<title id="{escape(chart_id)}-title">{escape(title)}</title>',
        f'<desc id="{escape(chart_id)}-desc">{escape(description)}</desc>',
    ]
    left = 0
    widths = segment_widths([count for _, count in parts])
    for (key, _), width in zip(parts, widths, strict=True):
        if not width:
            continue
        svg.append(
            f'<rect class="mix-{escape(key)}" x="{left}" y="0" '
            f'width="{width}" height="{MIX_HEIGHT}"/>'
        )
        left += width + MIX_GAP
    svg.append("</svg>")
    return Markup("".join(svg))


# Three quarters of a circle of radius 50 round (60, 60), from the lower left over
# the top to the lower right. Its length is given as 1000, so a score is a dash.
DIAL_ARC = "M24.645 95.355A50 50 0 1 1 95.355 95.355"
DIAL_LENGTH = 1000


def dial_dash(value: Fraction) -> int:
    """The part of the arc a score from 0 to 100 fills, out of DIAL_LENGTH."""
    if value <= 0:
        return 0
    return floor(min(value, HUNDRED) * DIAL_LENGTH / HUNDRED)


def score_dial(
    chart_id: str,
    title: str,
    description: str,
    value: Fraction,
    number: str,
    caption: str,
) -> Markup:
    """The dial of the cover: the score as an arc, its number and a caption inside."""
    arc = f'd="{DIAL_ARC}" pathLength="{DIAL_LENGTH}"'
    svg = [
        '<svg class="dial" role="img" viewBox="0 0 120 104" width="180" '
        'height="156" xmlns="http://www.w3.org/2000/svg" '
        f'aria-labelledby="{escape(chart_id)}-title {escape(chart_id)}-desc">',
        f'<title id="{escape(chart_id)}-title">{escape(title)}</title>',
        f'<desc id="{escape(chart_id)}-desc">{escape(description)}</desc>',
        f'<path class="dial-track" {arc}/>',
    ]
    dash = dial_dash(value)
    if dash:
        svg.append(
            f'<path class="dial-value" {arc} stroke-dasharray="{dash} {DIAL_LENGTH}"/>'
        )
    svg.append(
        f'<text class="dial-number" x="60" y="66" text-anchor="middle">'
        f"{escape(number)}</text>"
    )
    svg.append(
        f'<text class="dial-caption" x="60" y="82" text-anchor="middle">'
        f"{escape(caption)}</text>"
    )
    svg.append("</svg>")
    return Markup("".join(svg))
