"""The Evidence Explorer (a Development preview): the view model, pure functions.

One client at one moment, read the way its checklist reads it: every control of the
library with the status label the report would give it today, every evidence source
with the state of its newest export, and the links between them. A control is linked
to a source when its rule reads a column of that source's adapter (`field_map` in
data/controls.yaml); a manual-only control reads no export and has no link.

Nothing here touches the database or a clock. `app.ui.explorer` loads the rows and
serves the result twice from the same object: as the tables of the page and as the
JSON the scene draws, so the two can never disagree.

The companies ring (`build_portfolio`) is every active client at once: each client
with its label for every control, as Home reads them. Its page carries the facts
the scene draws (the tables and the card templates), so it has no JSON.
"""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from app.checks.library import Library
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
from app.reports.view import ControlRow
from app.ui.dashboard import ClientPosture
from app.ui.viewmodels import CURRENT, SourceRow, control_sources

MANUAL_ONLY = "Manual evidence (no export)"


@dataclass(frozen=True)
class ExplorerSource:
    """One evidence source of the client: a pillar of the scene, a row of the table."""

    code: str
    name: str
    state: str
    state_text: str
    state_icon: str
    captured_at: str | None
    expires_at: str | None
    exports: int
    controls: tuple[str, ...]


@dataclass(frozen=True)
class ExplorerControl:
    """One control of the library: a tile of the scene, a row of the table."""

    control_id: str
    title: str
    domain: str
    gate: bool
    label: str
    label_text: str
    label_icon: str
    evidence_state: str
    evidence_at: str | None
    sources: tuple[str, ...]


@dataclass(frozen=True)
class ExplorerDomain:
    code: str
    name: str
    controls: int


@dataclass(frozen=True)
class ExplorerCounts:
    protected: int
    needs_attention: int
    not_protected: int
    not_checked: int
    not_applicable: int
    sources: int
    current: int
    to_refresh: int
    links: int


@dataclass(frozen=True)
class ExplorerView:
    """Everything the page and the scene show for one client."""

    client_id: int
    client_name: str
    as_of: str
    ruleset: str
    domains: tuple[ExplorerDomain, ...]
    sources: tuple[ExplorerSource, ...]
    controls: tuple[ExplorerControl, ...]
    counts: ExplorerCounts
    verdict: StatusLabel


def iso(value: datetime | None) -> str | None:
    """A moment as ISO 8601 text, or None."""
    return None if value is None else value.isoformat()


def adapters_of(library: Library) -> dict[str, tuple[str, ...]]:
    """The sources each control reads, by control id (see `control_sources`): the
    adapter columns of `field_map`, and the public DNS check for the mail controls.
    A manual-only control gets an empty tuple."""
    return control_sources(library)


def _label_counts(rows: Sequence[ControlRow]) -> Mapping[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.label.key] = counts.get(row.label.key, 0) + 1
    return counts


def _verdict(counts: Mapping[str, int]) -> StatusLabel:
    if counts.get(NOT_PROTECTED.key):
        return NOT_PROTECTED
    if counts.get(NEEDS_ATTENTION.key):
        return NEEDS_ATTENTION
    if counts.get(PROTECTED.key):
        return PROTECTED
    return NOT_CHECKED


def build_explorer(
    library: Library,
    client_id: int,
    client_name: str,
    as_of: datetime,
    rows: Sequence[ControlRow],
    sources: Sequence[SourceRow],
) -> ExplorerView:
    """The view of one client from its checklist rows and its source rows.

    `rows` are the controls as the report view gives them today; `sources` are the
    rows of the evidence page (every source with an export, and every source a
    control reads even when nothing was imported yet). A link is kept only when
    both ends exist, so the scene never points at a source the tables do not list.
    """
    adapters = adapters_of(library)
    known = {source.code for source in sources}
    feeds: dict[str, list[str]] = {code: [] for code in known}
    controls: list[ExplorerControl] = []
    for row in rows:
        linked = tuple(
            code for code in adapters.get(row.control_id, ()) if code in known
        )
        for code in linked:
            feeds[code].append(row.control_id)
        controls.append(
            ExplorerControl(
                control_id=row.control_id,
                title=row.title,
                domain=row.domain_code,
                gate=row.gate,
                label=row.label.key,
                label_text=row.label.text,
                label_icon=row.label.icon,
                evidence_state=row.evidence_state,
                evidence_at=iso(row.evidence_at),
                sources=linked,
            )
        )
    pillars = tuple(
        ExplorerSource(
            code=source.code,
            name=source.name,
            state=source.state.key,
            state_text=source.state.text,
            state_icon=source.state.icon,
            captured_at=iso(source.captured_at),
            expires_at=iso(source.expires_at),
            exports=source.exports,
            controls=tuple(feeds[source.code]),
        )
        for source in sources
    )
    per_domain = {domain.code: 0 for domain in library.domains}
    for control in controls:
        per_domain[control.domain] = per_domain.get(control.domain, 0) + 1
    domains = tuple(
        ExplorerDomain(domain.code, domain.name, per_domain[domain.code])
        for domain in library.domains
    )
    labels = _label_counts(rows)
    current = sum(1 for source in sources if source.state == CURRENT)
    counts = ExplorerCounts(
        protected=labels.get(PROTECTED.key, 0),
        needs_attention=labels.get(NEEDS_ATTENTION.key, 0),
        not_protected=labels.get(NOT_PROTECTED.key, 0),
        not_checked=labels.get(NOT_CHECKED.key, 0),
        not_applicable=labels.get(NOT_APPLICABLE.key, 0),
        sources=len(sources),
        current=current,
        to_refresh=len(sources) - current,
        links=sum(len(pillar.controls) for pillar in pillars),
    )
    return ExplorerView(
        client_id=client_id,
        client_name=client_name,
        as_of=as_of.isoformat(),
        ruleset=f"{library.ruleset_id} {library.version}",
        domains=domains,
        sources=pillars,
        controls=tuple(controls),
        counts=counts,
        verdict=_verdict(labels),
    )


def verdict_text(view: ExplorerView) -> str:
    """The words of the verdict band: the worst thing first, as the report would."""
    counts = view.counts
    if counts.not_protected:
        plural = "s" if counts.not_protected != 1 else ""
        return f"{counts.not_protected} control{plural} not protected"
    if counts.needs_attention:
        plural = "s" if counts.needs_attention != 1 else ""
        verb = "need" if counts.needs_attention != 1 else "needs"
        return f"{counts.needs_attention} control{plural} {verb} attention"
    if counts.protected:
        counted = counts.protected + counts.not_checked
        if counts.not_checked:
            return f"{counts.protected} of {counted} counted controls protected"
        return f"All {counted} counted controls protected"
    return "Nothing has been checked yet"


def source_names(view: ExplorerView) -> dict[str, str]:
    """Source code to its name, for the tables."""
    return {source.code: source.name for source in view.sources}


def explorer_json(view: ExplorerView) -> dict[str, Any]:
    """The view as plain data for the scene (JSON-serialisable)."""
    return asdict(view)


# --- the companies ring: every active client at once ----------------------------------

# The worst status first: what a control tile of the ring shows, and the order of
# the clients on its card. A control that is not applicable everywhere is the last.
WORST_FIRST = (NOT_PROTECTED, NEEDS_ATTENTION, NOT_CHECKED, PROTECTED, NOT_APPLICABLE)


@dataclass(frozen=True)
class PortfolioPair:
    """One client and its label for one control: a link of the ring (none when the
    control is not applicable there), a line of the control card."""

    client_id: int
    client_name: str
    label: StatusLabel


@dataclass(frozen=True)
class PortfolioClient:
    """One client: an office on the inner ring, a row of the Companies table.
    `counts` are its controls per status, in the order of LABELS."""

    posture: ClientPosture
    size: int
    counts: tuple[int, ...]


@dataclass(frozen=True)
class PortfolioControl:
    """One control of the library: a tile on the outer ring, a row of the Controls
    table. `counts` are its clients per status, in the order of LABELS."""

    control_id: str
    title: str
    domain: str
    # The name of its domain, written on the floor of its sector in the scene.
    domain_name: str
    worst: StatusLabel
    counts: tuple[int, ...]
    pairs: tuple[PortfolioPair, ...]


@dataclass(frozen=True)
class PortfolioView:
    """Everything the companies ring and its tables show."""

    as_of: str
    ruleset: str
    labels: tuple[StatusLabel, ...]
    clients: tuple[PortfolioClient, ...]
    controls: tuple[PortfolioControl, ...]
    # The links of the ring per status they can be filtered by (COUNTED_LABELS).
    links: tuple[tuple[StatusLabel, int], ...]


def build_portfolio(
    library: Library,
    clients: Sequence[tuple[ClientPosture, Sequence[ControlRow]]],
    sizes: Mapping[int, int],
    as_of: datetime,
) -> PortfolioView:
    """The companies ring from each client's posture and its control rows (the
    rows Home reads, `app.ui.home.read_clients`). Every control of the library is
    a tile, whether or not a client was read; a tile takes the worst label among
    its clients, and with no client at all it is not checked."""
    per_control: dict[str, list[PortfolioPair]] = {c.id: [] for c in library.controls}
    domain_names = {domain.code: domain.name for domain in library.domains}
    built: list[PortfolioClient] = []
    for posture, rows in clients:
        counts = _label_counts(rows)
        built.append(
            PortfolioClient(
                posture=posture,
                size=sizes.get(posture.client_id, 0),
                counts=tuple(counts.get(label.key, 0) for label in LABELS),
            )
        )
        for row in rows:
            per_control.setdefault(row.control_id, []).append(
                PortfolioPair(posture.client_id, posture.name, row.label)
            )
    controls: list[PortfolioControl] = []
    for control in library.controls:
        pairs = sorted(
            per_control[control.id],
            key=lambda pair: (
                WORST_FIRST.index(pair.label),
                pair.client_name,
                pair.client_id,
            ),
        )
        controls.append(
            PortfolioControl(
                control_id=control.id,
                title=control.title,
                domain=control.domain,
                domain_name=domain_names.get(control.domain, control.domain),
                worst=pairs[0].label if pairs else NOT_CHECKED,
                counts=tuple(
                    sum(1 for pair in pairs if pair.label == label) for label in LABELS
                ),
                pairs=tuple(pairs),
            )
        )
    links = tuple(
        (label, sum(control.counts[LABELS.index(label)] for control in controls))
        for label in COUNTED_LABELS
    )
    return PortfolioView(
        as_of=as_of.isoformat(),
        ruleset=f"{library.ruleset_id} {library.version}",
        labels=LABELS,
        clients=tuple(built),
        controls=tuple(controls),
        links=links,
    )
