"""The Evidence Explorer (a Development preview): the view model, pure functions.

One client at one moment, read the way its checklist reads it: every control of the
library with the status label the report would give it today, every evidence source
with the state of its newest export, and the links between them. A control is linked
to a source when its rule reads a column of that source's adapter (`field_map` in
data/controls.yaml); a manual-only control reads no export and has no link.

Nothing here touches the database or a clock. `app.ui.explorer` loads the rows and
serves the result twice from the same object: as the tables of the page and as the
JSON the scene draws, so the two can never disagree.
"""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from app.checks.library import Library
from app.reports.status import (
    NEEDS_ATTENTION,
    NOT_APPLICABLE,
    NOT_CHECKED,
    NOT_PROTECTED,
    PROTECTED,
    StatusLabel,
)
from app.reports.view import ControlRow
from app.ui.viewmodels import CURRENT, SourceRow

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
    """The adapters (source codes) each control reads, by control id.

    A field is mapped to an adapter column in `field_map`; a field listed as
    unavailable maps to nothing. A control whose fields map to nothing (the
    manual-only controls) gets an empty tuple.
    """
    found: dict[str, tuple[str, ...]] = {}
    for control in library.controls:
        adapters = {
            library.field_map[field].adapter
            for field in control.fields
            if field in library.field_map
        }
        found[control.id] = tuple(sorted(adapters))
    return found


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
