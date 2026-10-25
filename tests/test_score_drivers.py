"""What moves the score on Home (THE-1189): the hundred points of a client split by
cause, the bar that draws it, the stylesheet and the page.

The split tests use the three worked clients of the report tests and small inputs
of the scoring engine; they need no database. The page test needs PostgreSQL
(DATABASE_URL) and is skipped without it, as the other page tests are.
"""

import re
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.checks.library import load_library
from app.checks.model import Status
from app.evidence.service import EvidenceContext
from app.reports.view import build_view
from app.scoring.engine import score_inputs
from app.scoring.model import ControlInput, DomainWeight, ScoreResult
from app.ui.auth import templates
from app.ui.brand import ASSET_FILES, DRIVER_FILES, STATIC_DIR, asset_version
from app.ui.drivers import (
    DRIVERS,
    EVIDENCE_AGE,
    EVIDENCE_TYPE,
    GATE_CAP,
    NOT_CHECKED,
    NOT_PROTECTED,
    PARTLY_MET,
    ScoreDrivers,
    drivers_of,
    portfolio_of,
)
from html_structure import structure_problems
from tools import report_clients
from ui_helpers import seed_client, sign_in

LIBRARY = load_library()
ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app/ui/templates"
HOME = (TEMPLATES / "home.html").read_text(encoding="utf-8")
MACROS = (TEMPLATES / "_drivers.html").read_text(encoding="utf-8")
CSS = (STATIC_DIR / "css/drivers.css").read_text(encoding="utf-8")
VERSION = asset_version(files=DRIVER_FILES)
AS_OF = datetime(2026, 10, 17, 12, tzinfo=UTC)
HUNDRED = Fraction(100)
SEGMENT = re.compile(r'<rect class="rv-drv-([a-z-]+)" x="([0-9.]+)" y="0" width="')


def worked(name: str) -> ScoreDrivers:
    view = build_view(
        report_clients.snapshot_bytes(LIBRARY, name),
        LIBRARY,
        report_clients.context_for(name),
        report_clients.previous_bytes(LIBRARY, name),
    )
    titles = {row.control_id: row.title for row in view.rows}
    split = drivers_of(view.result, titles)
    assert split is not None
    return split


def control(
    control_id: str,
    status: Status,
    *,
    domain: str = "D1",
    weight: int = 1,
    gate: bool = False,
    quality: Fraction = Fraction(1),
    age_days: int | None = 1,
    max_age_days: int | None = 30,
) -> ControlInput:
    evidence = None if age_days is None else AS_OF - timedelta(days=age_days)
    return ControlInput(
        control_id=control_id,
        domain=domain,
        weight=weight,
        gate=gate,
        status=status,
        quality=quality,
        evidence_at=evidence,
        max_age_days=max_age_days,
    )


def scored(*inputs: ControlInput, domains: tuple[str, ...] = ("D1",)) -> ScoreResult:
    weights = tuple(DomainWeight(code, 1) for code in domains)
    return score_inputs(inputs, weights, AS_OF)


# --- the split ----------------------------------------------------------------------


@pytest.mark.parametrize("name", report_clients.NAMES)
def test_earned_and_lost_add_up_to_a_hundred_exactly(name: str) -> None:
    split = worked(name)
    assert split.earned + split.lost == HUNDRED
    assert all(loss.points > 0 for loss in split.losses)
    order = [driver.key for driver in DRIVERS]
    keys = [loss.driver.key for loss in split.losses]
    assert keys == sorted(keys, key=order.index)


def test_a_capped_score_names_the_gate_and_what_it_holds_back() -> None:
    # Client C: a gate control fails, so the score is held at 49.
    split = worked("C")
    assert split.earned == 49
    assert split.cap_control == "PC-ACC-02" and split.cap_limit == 49
    assert split.points_of(GATE_CAP.key) > 0
    assert split.biggest is not None and split.biggest.driver == GATE_CAP
    assert split.top[0].control_id == "PC-ACC-02" and split.top[0].gate
    # Client B has a gate cap of 49 too, but its score is below it: nothing is held.
    b = worked("B")
    assert b.cap_control is None and b.points_of(GATE_CAP.key) == 0
    assert b.earned < 49


def test_the_top_controls_cost_the_most_and_carry_their_titles() -> None:
    split = worked("A")
    assert 0 < len(split.top) <= 3
    points = [item.points for item in split.top]
    assert points == sorted(points, reverse=True)
    assert all(item.title for item in split.top)


def test_each_cause_is_its_own_driver() -> None:
    result = scored(
        control("C1", "fail"),
        control("C2", "partial"),
        control("C3", "unknown", age_days=None),
        control("C4", "pass", quality=Fraction(9, 10)),
        # 45 days old with a maximum of 30: freshness 1 - 15/30 = 1/2.
        control("C5", "pass", age_days=45),
        control("C6", "pass"),
    )
    split = drivers_of(result)
    assert split is not None
    share = HUNDRED / 6
    assert split.points_of(NOT_PROTECTED.key) == share
    assert split.points_of(PARTLY_MET.key) == share / 2
    assert split.points_of(NOT_CHECKED.key) == share
    assert split.points_of(EVIDENCE_TYPE.key) == share / 10
    assert split.points_of(EVIDENCE_AGE.key) == share / 2
    assert split.points_of(GATE_CAP.key) == 0
    assert split.earned + split.lost == HUNDRED
    assert split.earned == result.score


def test_no_evidence_is_a_hundred_points_not_checked() -> None:
    result = scored(control("C1", "unknown", age_days=None), control("C2", "unknown"))
    split = drivers_of(result)
    assert split is not None
    assert split.earned == 0 and split.earned_width == "0.00"
    assert [loss.driver for loss in split.losses] == [NOT_CHECKED]
    assert split.points_of(NOT_CHECKED.key) == HUNDRED
    assert split.label == "0.0 of 100 points earned, 100.0 lost to not checked."


def test_nothing_is_split_when_every_control_is_not_applicable() -> None:
    assert drivers_of(scored(control("C1", "na"), control("C2", "na"))) is None


def test_a_dropped_domain_and_the_weights_follow_the_engine() -> None:
    # D2 is all not applicable, so only D1 counts; inside D1 a weight-3 control
    # costs three times what a weight-1 control does.
    result = scored(
        control("C1", "fail", weight=3),
        control("C2", "fail", weight=1),
        control("C3", "pass", weight=1),
        control("C4", "na", domain="D2"),
        domains=("D1", "D2"),
    )
    split = drivers_of(result)
    assert split is not None
    assert split.points_of(NOT_PROTECTED.key) == HUNDRED * 4 / 5
    assert [item.control_id for item in split.top] == ["C1", "C2"]
    assert split.top[0].points == 3 * split.top[1].points


def test_the_segments_follow_each_other_to_the_end_of_the_bar() -> None:
    split = worked("B")
    end = float(split.earned)
    for loss in split.losses:
        assert abs(float(loss.x) - end) < 0.01
        end += float(loss.width)
    assert abs(end - 100) < 0.05


def test_the_portfolio_is_the_mean_of_the_clients_with_a_split() -> None:
    assert portfolio_of([]) is None and portfolio_of([None]) is None
    splits = [worked(name) for name in report_clients.NAMES]
    mean = portfolio_of([*splits, None])
    assert mean is not None and mean.clients == 3
    assert mean.drivers.earned == sum(item.earned for item in splits) / 3
    assert mean.drivers.earned + mean.drivers.lost == HUNDRED
    for driver in DRIVERS:
        expected = sum(item.points_of(driver.key) for item in splits) / 3
        assert mean.drivers.points_of(driver.key) == expected


# --- the template and the stylesheet ----------------------------------------------


def test_home_replaces_the_ring_cards_with_the_score_bars() -> None:
    rookery = HOME.split('id="rookery"', 1)[1].split("</section>", 1)[0]
    assert 'class="rv-ring"' not in rookery
    assert '<ul class="rv-drivers" id="rookery-list">' in rookery
    # The scene still reads its rooks from the cards, before them on the page.
    assert rookery.index("rookery-scene") < rookery.index('id="drivers-summary"')
    assert 'id="drivers-empty"' in rookery and 'id="drivers-data"' in rookery
    assert "d.bar(mean," in rookery and "d.bar(split," in rookery
    assert "d.legend(drivers)" in rookery
    assert "<caption>" in rookery and 'scope="row"' in rookery
    assert "Import an export" in rookery and "lower bound" in rookery
    assert "data-drawer>{{ split.cap_control }}</a>" in rookery
    # A mean that counts a lower bound says it is one (review of THE-1221).
    assert 'selectattr("insufficient")' in rookery
    assert "so the mean is a lower bound" in rookery
    link = '<link rel="stylesheet" href="/static/css/drivers.css?v='
    assert link + '{{ drivers_version }}">' in HOME


def test_the_bar_is_an_image_told_in_words_never_by_colour_alone() -> None:
    assert 'role="img" aria-label="{{ label }}"' in MACROS
    assert 'preserveAspectRatio="none"' in MACROS
    assert '<rect class="rv-drv-{{ loss.driver.key }}"' in MACROS
    assert 'aria-hidden="true" focusable="false"' in MACROS
    assert "<style" not in MACROS and " style=" not in MACROS


def test_the_legend_keeps_each_name_and_its_words_together_at_the_top() -> None:
    # An item of the legend is a grid as tall as its row. Without align-content its
    # two rows shared the spare height, and a one-line description sat 9px lower
    # than a two-line one beside it at 1440px (THE-1189 acceptance D6).
    plain = re.sub(r"/\*.*?\*/", "", CSS, flags=re.DOTALL)
    item = re.search(r"\n\.rv-drv-legend li \{([^}]*)\}", plain)
    assert item is not None
    assert "display: grid;" in item.group(1)
    assert "align-content: start;" in item.group(1)


def test_the_stylesheet_has_its_own_version_and_uses_tokens_only() -> None:
    assert templates.env.globals["drivers_version"] == VERSION
    assert not set(DRIVER_FILES) & set(ASSET_FILES)
    plain = re.sub(r"/\*.*?\*/", "", CSS, flags=re.DOTALL)
    assert "#" not in plain
    for forbidden in ("url(", "@import", "http", "animation", "transition"):
        assert forbidden not in plain, forbidden
    for driver in ("earned", *(item.key for item in DRIVERS)):
        assert f".rv-drv-{driver}" in CSS, driver
    assert '.rv-driver[data-selected="true"]' in CSS


@pytest.mark.parametrize("theme", ("light", "dark"))
def test_every_text_rule_of_the_drivers_reaches_its_contrast(theme: str) -> None:
    from test_brand_contrast import THEMES, contrast_ratio, parse_rules, resolve

    variables = THEMES[theme]
    checked = 0
    for selector, declarations in parse_rules(CSS):
        if "color" not in declarations:
            continue
        assert "background-color" in declarations, selector
        text = resolve(declarations["color"], variables)
        background = resolve(declarations["background-color"], variables)
        assert text and background, selector
        ratio = contrast_ratio(text, background)
        assert ratio >= 4.5, f"{selector} ({theme}): {ratio:.2f}"
        checked += 1
    assert checked >= 8


# --- the page (PostgreSQL) ----------------------------------------------------------


async def test_home_draws_the_split_of_a_client_with_evidence(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    page = await ui_browser.get("/")
    html = page.text
    assert page.status_code == 200 and structure_problems(html) == []
    assert f'href="/static/css/drivers.css?v={VERSION}"' in html
    assert 'id="drivers-summary"' in html and 'id="drivers-empty"' not in html
    assert "The client with evidence scores <strong>" in html
    card = html.split(f'data-client="{client_id}"', 1)[1].split("</li>", 1)[0]
    # The summary calls the score a lower bound exactly when the card does.
    summary = html.split('id="drivers-summary"', 1)[1].split("</p>", 1)[0]
    thin = 'data-insufficient="true"' in card.split(">", 1)[0]
    assert ("so this is a lower bound" in summary) == thin
    assert 'class="rv-drv-bar rv-drv-bar-row"' in card
    label = re.search(r'role="img" aria-label="([^"]+)"', card)
    assert label is not None and label.group(1).startswith("Synthetic Client Ltd: ")
    assert " of 100 points earned" in label.group(1)
    assert " lost to " in label.group(1)
    # The track under the bar matches the pattern too; the first part drawn on it
    # is what the client earns.
    segments = [part for part in SEGMENT.findall(card) if part[0] != "track"]
    assert segments and segments[0][0] == "earned"
    assert f'href="/clients/{client_id}/controls/' in card


async def test_home_says_so_when_no_client_has_evidence(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    added = await ui_browser.post(
        "/clients", data={"csrf_token": csrf, "name": "Empty Client Ltd"}
    )
    assert added.status_code == 303
    page = await ui_browser.get("/")
    html = page.text
    assert page.status_code == 200 and structure_problems(html) == []
    assert 'id="drivers-empty"' in html and 'id="drivers-summary"' not in html
    assert 'id="drivers-data"' not in html
    card = html.split('data-name="Empty Client Ltd"', 1)[1].split("</li>", 1)[0]
    assert "rv-drv-bar" not in card
    assert "No evidence yet" in card and "Import an export" in card
