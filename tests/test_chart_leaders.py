"""The labels at the ends of the score lines and their leaders (THE-1414, F1).

On Development at 768px (THE-1413) the labels of the Home chart were pushed apart
with nothing tying them to their lines: the label of Seed Gaps sat level with the
end of the Seed Tidy line, and the Seed Tidy label sat about 60px above its own
line although nothing crowded it. The whole stack had been lifted by the excess of
its crowded foot. Now a label moves only as far as the labels around it need, and
a label that had to move is tied to the end of its line by a short leader. These
tests render the real chart macro and read the drawing it gives.
"""

import xml.etree.ElementTree as ET
from datetime import timedelta
from fractions import Fraction

from jinja2 import Environment, FileSystemLoader

from app.ui.brand import STATIC_DIR
from app.ui.dashboard import (
    LABEL_GAP,
    LABEL_INSET,
    LEADER_END,
    LEADER_START,
    LINE_STEP,
    NARROW_CHART,
    ReportPoint,
    TrendChart,
    trend_chart,
)
from tools.score_inputs import AS_OF

TEMPLATES = STATIC_DIR.parent / "ui" / "templates"
CSS = (STATIC_DIR / "css/revrook.css").read_text(encoding="utf-8")
ENV = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
MACRO = '{% import "_chart.html" as c %}{{ c.score_chart(chart, "t", "p", "w") }}'
# The four seeded clients of Development and where their lines ended at 0b6372b1.
SEEDED = {
    1: "Design Review Sample Client",
    2: "Seed Gaps Ltd (synthetic)",
    3: "Seed Stale Ltd (synthetic)",
    4: "Seed Tidy Ltd (synthetic)",
}


def history(scores: dict[int, int]) -> list[ReportPoint]:
    """Two reports a client, 40 and 3 days back, the last at `scores`."""
    found = []
    for client_id, score in scores.items():
        for days, value in ((40, score + 5), (3, score)):
            found.append(
                ReportPoint(
                    client_id,
                    AS_OF - timedelta(days=days),
                    Fraction(value),
                    "Good",
                    False,
                    40,
                    5,
                )
            )
    return found


def drawn(chart: TrendChart) -> dict[str, dict]:
    """What the macro draws for each line: its last mark, label and leader."""
    html = str(ENV.from_string(MACRO).render(chart=chart))
    # The one attribute without a value (HTML, not XML) is given one to parse it
    svg = ET.fromstring(html.replace(" data-roving>", ' data-roving="">'))
    found = {}
    for group in svg.iter("g"):
        if group.get("class") != "rv-chart-line":
            continue
        series = group.get("data-series")
        line = next(item for item in chart.lines if str(item.client_id) == series)
        text = group.find("text")
        leaders = [item for item in group.iter("line") if item.get("class")]
        found[line.name] = {
            "line": line,
            "text": text,
            "words": [] if text is None else [span.text for span in text.iter("tspan")],
            "leaders": leaders,
        }
    return found


def middle(line) -> float:
    """The middle of a label: the place of its first line and half of the rest."""
    return float(line.label_y) + (len(line.label) - 1) * LINE_STEP / 2


def test_a_label_far_from_the_crowd_stays_at_the_end_of_its_line() -> None:
    # Three clients crowd the floor; the fourth ends high on the plot.
    chart = trend_chart(history({1: 0, 2: 16, 3: 4, 4: 90}), SEEDED, AS_OF)
    tidy = next(line for line in chart.lines if line.client_id == 4)
    assert abs(middle(tidy) - float(tidy.last_y)) < 0.1
    assert tidy.leader == ()
    # The crowd still keeps its air and stays above the dates of the axis.
    places = sorted(
        (float(line.label_y), float(line.label_y) + (len(line.label) - 1) * LINE_STEP)
        for line in chart.lines
    )
    for (_, bottom), (top, _) in zip(places, places[1:], strict=False):
        assert top - bottom >= LABEL_GAP - 0.05
    assert places[-1][1] <= chart.bottom - LABEL_GAP / 2 + 0.05
    assert places[0][0] >= chart.top + LABEL_GAP / 2 - 0.05


def test_every_label_that_moved_is_tied_to_the_end_of_its_line() -> None:
    # The ends seen on Development at 768px: 192, 163, 185 and 104 units down.
    chart = trend_chart(history({1: 0, 2: 16, 3: 4, 4: 49}), SEEDED, AS_OF)
    lines = drawn(chart)
    moved = 0
    for name, item in lines.items():
        line = item["line"]
        # The whole name, broken between its words, as PR 82 fitted it
        assert " ".join(item["words"]) == name
        if abs(middle(line) - float(line.last_y)) <= 2:
            assert item["leaders"] == [], name
            continue
        moved += 1
        assert len(item["leaders"]) == 1, name
        leader = item["leaders"][0]
        assert leader.get("class") == "rv-chart-leader"
        last = line.marks[-1]
        # From just past the last mark of the line ...
        assert float(leader.get("x1")) == float(last.x) + LEADER_START
        assert float(leader.get("y1")) == float(last.y)
        # ... to just before the words of its label, at their middle.
        label_x = float(item["text"].get("x"))
        assert label_x == chart.right + LABEL_INSET
        assert float(leader.get("x2")) == chart.right + LEADER_END < label_x
        assert abs(float(leader.get("y2")) - middle(line)) < 0.1
    assert moved >= 3
    # The leaders never cross: they reach the labels in the order the lines end.
    ends = sorted(
        (float(item["leaders"][0].get("y1")), float(item["leaders"][0].get("y2")))
        for item in lines.values()
        if item["leaders"]
    )
    assert [y2 for _, y2 in ends] == sorted(y2 for _, y2 in ends)
    # Seed Tidy, the highest line, keeps its label nearer its line than before
    # (it sat 58 units above it when the whole stack was lifted).
    tidy = lines[SEEDED[4]]["line"]
    assert float(tidy.last_y) - middle(tidy) < 32


def test_a_lone_report_starts_its_leader_past_its_ring() -> None:
    names = {1: "Alder Ltd", 2: "Birch Ltd", 3: "Cedar Ltd"}
    lone = [
        ReportPoint(k, AS_OF - timedelta(days=1), Fraction(1), "Poor", False, 40, 5)
        for k in names
    ]
    chart = trend_chart(lone, names, AS_OF)
    tied = [line for line in chart.lines if line.leader]
    assert tied
    for line in tied:
        assert float(line.leader[0]) == float(line.last_x) + 9


def test_the_narrow_drawing_has_no_labels_and_no_leaders() -> None:
    chart = trend_chart(
        history({1: 0, 2: 16, 3: 4, 4: 49}), SEEDED, AS_OF, size=NARROW_CHART
    )
    assert all(line.leader == () for line in chart.lines)
    for item in drawn(chart).values():
        assert item["text"] is None and item["leaders"] == []


def test_the_leader_is_drawn_with_tokens() -> None:
    rule = CSS.split(".rv-chart-line .rv-chart-leader {", 1)[1].split("}", 1)[0]
    assert "stroke: var(--rv-text-secondary);" in rule
    assert "#" not in rule
