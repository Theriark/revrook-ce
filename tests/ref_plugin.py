"""The no-op reference plugin of extension API version 1. Tests only.

It implements every extension point and does nothing: it shows the shape a plugin has
and gives the contract tests something to load. It is not installed, not packaged and
not part of the image; the tests reach it through an entry point they build themselves.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from app.ext import EXTENSION_API_VERSION
from app.ext.protocols import (
    CollectedEvidence,
    ControlMapping,
    ExternalIdentity,
    NavItem,
    Question,
    RenderedReport,
)
from app.ext.registry import ExtensionRegistry


class NoopCollector:
    name = "noop-collector"
    source_code = "noop-source"

    async def collect(
        self, client_id: int, now: datetime
    ) -> Sequence[CollectedEvidence]:
        return []


class NoopFramework:
    name = "noop-framework"
    framework = "Noop Framework"
    version = "1.0"

    def mappings(self) -> Sequence[ControlMapping]:
        return [ControlMapping("PC-ACC-01", "NOOP-1", verified=False)]


class NoopQuestionnaire:
    name = "noop-questionnaire"
    title = "A questionnaire that asks nothing"

    def questions(self) -> Sequence[Question]:
        return [Question("q1", "Is this a test?", ("PC-ACC-01",), verified=False)]


class NoopReportTemplate:
    name = "noop-report"
    kind = "noop"

    def render(self, snapshot: Mapping[str, Any]) -> RenderedReport:
        return RenderedReport("noop.txt", "text/plain", b"nothing to report")


class NoopAuthProvider:
    name = "noop-auth"

    async def authenticate(self, headers: Mapping[str, str]) -> ExternalIdentity | None:
        return None


class NoopRetentionPolicy:
    name = "noop-retention"

    def raw_retention_days(self, source_code: str, default_days: int) -> int:
        return default_days

    def pack_retention_months(self, default_months: int) -> int:
        return default_months


class NoopUiExtension:
    name = "noop-ui"

    def nav_items(self) -> Sequence[NavItem]:
        return [NavItem("Noop", "/noop")]


class ReferencePlugin:
    name = "reference"
    api_version = EXTENSION_API_VERSION

    def register(self, registry: ExtensionRegistry) -> None:
        registry.add_collector(NoopCollector())
        registry.add_framework(NoopFramework())
        registry.add_questionnaire(NoopQuestionnaire())
        registry.add_report_template(NoopReportTemplate())
        registry.add_auth_provider(NoopAuthProvider())
        registry.add_retention_policy(NoopRetentionPolicy())
        registry.add_ui_extension(NoopUiExtension())


PLUGIN = ReferencePlugin()
