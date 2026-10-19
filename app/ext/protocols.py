"""The seven extension points of extension API version 1, as typing protocols.

Version 1 is frozen: a name, a member or a signature below changes only with a new
`EXTENSION_API_VERSION`. A plugin implements the points it offers and hands each
object to the registry (`app.ext.registry.ExtensionRegistry`) from its `register`
method. The Community Edition ships none; see `docs/extension-api.md`.

Every object has a `name`: lower-case letters, digits and dashes, unique within its
point. Nothing here runs unless a plugin is installed.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class CollectedEvidence:
    """One export a collector gathered for a client: the bytes an importer reads."""

    source_code: str
    captured_at: datetime
    data: bytes


@dataclass(frozen=True)
class ControlMapping:
    """A revrook control tied to a clause of a framework.

    `verified` stays False until a person has checked the mapping: a report must
    never present an unverified mapping as established.
    """

    control_id: str
    reference: str
    verified: bool


@dataclass(frozen=True)
class Question:
    """One question of a questionnaire and the controls that answer it."""

    id: str
    text: str
    control_ids: tuple[str, ...]
    verified: bool


@dataclass(frozen=True)
class RenderedReport:
    """A finished report file."""

    filename: str
    content_type: str
    body: bytes


@dataclass(frozen=True)
class ExternalIdentity:
    """Who an authentication provider says the caller is."""

    username: str
    is_admin: bool


@dataclass(frozen=True)
class NavItem:
    """A link a UI extension adds to the navigation. `path` starts with a slash."""

    label: str
    path: str


@runtime_checkable
class CollectorProvider(Protocol):
    """Gathers evidence for a client from a source the importers do not read."""

    name: str
    source_code: str

    async def collect(
        self, client_id: int, now: datetime
    ) -> Sequence[CollectedEvidence]: ...


@runtime_checkable
class FrameworkPack(Protocol):
    """Maps revrook controls to the clauses of one version of a framework."""

    name: str
    framework: str
    version: str

    def mappings(self) -> Sequence[ControlMapping]: ...


@runtime_checkable
class QuestionnairePack(Protocol):
    """A questionnaire (an insurer's, say) answered from the controls."""

    name: str
    title: str

    def questions(self) -> Sequence[Question]: ...


@runtime_checkable
class ReportTemplate(Protocol):
    """Renders a stored snapshot document as a report of its own `kind`."""

    name: str
    kind: str

    def render(self, snapshot: Mapping[str, Any]) -> RenderedReport: ...


@runtime_checkable
class AuthProvider(Protocol):
    """Identifies a caller from the headers of a request, or says it cannot."""

    name: str

    async def authenticate(
        self, headers: Mapping[str, str]
    ) -> ExternalIdentity | None: ...


@runtime_checkable
class RetentionPolicy(Protocol):
    """Chooses how long files and packs are kept; the arguments are the defaults."""

    name: str

    def raw_retention_days(self, source_code: str, default_days: int) -> int: ...

    def pack_retention_months(self, default_months: int) -> int: ...


@runtime_checkable
class UiExtension(Protocol):
    """Adds links to the navigation."""

    name: str

    def nav_items(self) -> Sequence[NavItem]: ...
