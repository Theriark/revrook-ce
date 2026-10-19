"""Extension API version 1: every extension point, the loader and the CE image.

Nothing here needs PostgreSQL. The reference plugin (`tests/ref_plugin.py`) is a no-op
plugin used only by these tests; it is reached through an entry point built here, never
installed. The CE image has no plugin and no name that belongs to a later edition.
"""

import dataclasses
import inspect
import re
import tomllib
import traceback
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import EntryPoint, entry_points
from typing import Any

import pytest
from fastapi import FastAPI

import ref_plugin
from app import ext
from app.db import make_engine
from app.ext import protocols
from app.ext.registry import (
    NAME_PATTERN,
    POINTS,
    ExtensionError,
    ExtensionRegistry,
    load_plugins,
)
from app.main import create_app
from app.settings import Settings
from repo_files import ROOT

NOW = datetime(2026, 10, 17, 12, 0)
UNREACHABLE = "postgresql+asyncpg://revrook:unused@127.0.0.1:1/revrook"
# The frozen surface of version 1: what each point and each data type is made of.
FROZEN_POINTS = {
    "CollectorProvider": {"name", "source_code", "collect"},
    "FrameworkPack": {"name", "framework", "version", "mappings"},
    "QuestionnairePack": {"name", "title", "questions"},
    "ReportTemplate": {"name", "kind", "render"},
    "AuthProvider": {"name", "authenticate"},
    "RetentionPolicy": {"name", "raw_retention_days", "pack_retention_months"},
    "UiExtension": {"name", "nav_items"},
}
FROZEN_FIELDS = {
    "CollectedEvidence": ["source_code", "captured_at", "data"],
    "ControlMapping": ["control_id", "reference", "verified"],
    "Question": ["id", "text", "control_ids", "verified"],
    "RenderedReport": ["filename", "content_type", "body"],
    "ExternalIdentity": ["username", "is_admin"],
    "NavItem": ["label", "path"],
}
FROZEN_PARAMETERS = {
    ("CollectorProvider", "collect"): ["self", "client_id", "now"],
    ("FrameworkPack", "mappings"): ["self"],
    ("QuestionnairePack", "questions"): ["self"],
    ("ReportTemplate", "render"): ["self", "snapshot"],
    ("AuthProvider", "authenticate"): ["self", "headers"],
    ("RetentionPolicy", "raw_retention_days"): ["self", "source_code", "default_days"],
    ("RetentionPolicy", "pack_retention_months"): ["self", "default_months"],
    ("UiExtension", "nav_items"): ["self"],
}
# What a later edition would be named after. None of it belongs in the CE image.
EE_ONLY_NAMES = re.compile(
    r"revrook[-_.]ee|revrook[-_.]enterprise|enterprise edition|ee[-_]only"
    r"|ed25519|licen[cs]e[-_ ]?key|graph\.microsoft\.com|oidc|openid",
    re.IGNORECASE,
)
# What the Dockerfile may copy into the image.
IMAGE_SOURCES = {"alembic.ini", "alembic", "app", "data"}
IMAGE_SUFFIXES = {".py", ".html", ".css", ".json", ".yaml", ".yml", ".ini", ".mako"}


@dataclass(frozen=True)
class FakePoint:
    """An entry point that hands out an object, or fails like a broken import."""

    name: str
    target: Any = None
    error: Exception | None = None

    def load(self) -> Any:
        if self.error is not None:
            raise self.error
        return self.target


def reference_point() -> EntryPoint:
    """A real entry point of the plugin group that names the reference plugin."""
    return EntryPoint(
        name="reference", value="ref_plugin:PLUGIN", group=ext.PLUGIN_ENTRY_POINT_GROUP
    )


class Quiet:
    """A plugin that registers nothing."""

    name = "quiet"
    api_version = ext.EXTENSION_API_VERSION

    def register(self, registry: ExtensionRegistry) -> None:
        return None


# --- the frozen surface ---


def test_the_api_is_frozen_at_version_1() -> None:
    assert ext.EXTENSION_API_VERSION == 1
    assert ext.PLUGIN_ENTRY_POINT_GROUP == "revrook.plugins"
    assert set(POINTS) == {
        "collector",
        "framework",
        "questionnaire",
        "report-template",
        "auth-provider",
        "retention-policy",
        "ui-extension",
    }


@pytest.mark.parametrize("point", sorted(FROZEN_POINTS))
def test_each_extension_point_has_exactly_its_frozen_members(point: str) -> None:
    protocol = getattr(protocols, point)
    members = set(getattr(protocol, "__annotations__", {})) | {
        name
        for name, value in vars(protocol).items()
        if callable(value) and not name.startswith("_")
    }
    assert members == FROZEN_POINTS[point]


@pytest.mark.parametrize(("point", "method"), sorted(FROZEN_PARAMETERS))
def test_each_extension_method_keeps_its_parameters(point: str, method: str) -> None:
    function = getattr(getattr(protocols, point), method)
    parameters = list(inspect.signature(function).parameters)
    assert parameters == FROZEN_PARAMETERS[point, method]


@pytest.mark.parametrize("name", sorted(FROZEN_FIELDS))
def test_each_extension_data_type_keeps_its_fields(name: str) -> None:
    fields = [field.name for field in dataclasses.fields(getattr(protocols, name))]
    assert fields == FROZEN_FIELDS[name]
    assert getattr(protocols, name).__dataclass_params__.frozen is True


def test_the_plugin_group_is_declared_in_the_package_and_empty() -> None:
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    groups = meta["project"]["entry-points"]
    assert groups[ext.PLUGIN_ENTRY_POINT_GROUP] == {}


# --- the contract of each extension point, shown by the reference plugin ---


@pytest.fixture
def loaded() -> ExtensionRegistry:
    return load_plugins([reference_point()])


def test_the_reference_plugin_registers_every_point(
    loaded: ExtensionRegistry,
) -> None:
    assert loaded.plugins == ["reference"]
    assert loaded.count() == len(POINTS) == 7
    assert [item.name for item in loaded.collectors()] == ["noop-collector"]
    assert [item.name for item in loaded.frameworks()] == ["noop-framework"]
    assert [item.name for item in loaded.questionnaires()] == ["noop-questionnaire"]
    assert [item.name for item in loaded.report_templates()] == ["noop-report"]
    assert [item.name for item in loaded.auth_providers()] == ["noop-auth"]
    assert [item.name for item in loaded.retention_policies()] == ["noop-retention"]
    assert [item.name for item in loaded.ui_extensions()] == ["noop-ui"]


async def test_a_collector_returns_evidence_for_a_client(
    loaded: ExtensionRegistry,
) -> None:
    (collector,) = loaded.collectors()
    assert isinstance(collector, protocols.CollectorProvider)
    found = await collector.collect(1, NOW)
    assert list(found) == []
    one = protocols.CollectedEvidence("noop-source", NOW, b"a,b\n")
    assert one.source_code == collector.source_code


def test_a_framework_pack_maps_controls_and_says_what_is_verified(
    loaded: ExtensionRegistry,
) -> None:
    (pack,) = loaded.frameworks()
    assert isinstance(pack, protocols.FrameworkPack)
    mappings = pack.mappings()
    assert all(isinstance(item, protocols.ControlMapping) for item in mappings)
    assert [item.verified for item in mappings] == [False]
    assert pack.framework and pack.version


def test_a_questionnaire_pack_lists_questions_and_their_controls(
    loaded: ExtensionRegistry,
) -> None:
    (pack,) = loaded.questionnaires()
    assert isinstance(pack, protocols.QuestionnairePack)
    questions = pack.questions()
    assert all(isinstance(item, protocols.Question) for item in questions)
    assert all(isinstance(item.control_ids, tuple) for item in questions)
    assert pack.title


def test_a_report_template_renders_a_snapshot_as_a_file(
    loaded: ExtensionRegistry,
) -> None:
    (template,) = loaded.report_templates()
    assert isinstance(template, protocols.ReportTemplate)
    report = template.render({"client": "Synthetic Client Ltd"})
    assert isinstance(report, protocols.RenderedReport)
    assert report.filename and report.content_type and report.body
    assert template.kind == "noop"


async def test_an_auth_provider_names_a_caller_or_says_it_cannot(
    loaded: ExtensionRegistry,
) -> None:
    (provider,) = loaded.auth_providers()
    assert isinstance(provider, protocols.AuthProvider)
    assert await provider.authenticate({"authorization": "Bearer nothing"}) is None
    identity = protocols.ExternalIdentity("synthetic.user", is_admin=False)
    assert identity.username == "synthetic.user" and identity.is_admin is False


def test_a_retention_policy_answers_with_the_defaults_it_is_given(
    loaded: ExtensionRegistry,
) -> None:
    (policy,) = loaded.retention_policies()
    assert isinstance(policy, protocols.RetentionPolicy)
    assert policy.raw_retention_days("reference-csv", 7) == 7
    assert policy.pack_retention_months(25) == 25


def test_a_ui_extension_adds_navigation_links(loaded: ExtensionRegistry) -> None:
    (extension,) = loaded.ui_extensions()
    assert isinstance(extension, protocols.UiExtension)
    items = extension.nav_items()
    assert all(isinstance(item, protocols.NavItem) for item in items)
    assert all(item.path.startswith("/") for item in items)


# --- the registry refuses what does not fit ---


class WrongShape:
    name = "wrong-shape"


class BadName:
    name = "Not A Good Name"
    source_code = "x"

    async def collect(
        self, client_id: int, now: datetime
    ) -> list[protocols.CollectedEvidence]:
        return []


@pytest.mark.parametrize(
    "add",
    [
        "add_collector",
        "add_framework",
        "add_questionnaire",
        "add_report_template",
        "add_auth_provider",
        "add_retention_policy",
        "add_ui_extension",
    ],
)
def test_an_object_that_does_not_implement_the_point_is_refused(add: str) -> None:
    registry = ExtensionRegistry()
    with pytest.raises(ExtensionError, match="does not implement"):
        getattr(registry, add)(WrongShape())
    assert registry.count() == 0


def test_a_name_that_is_not_lower_case_with_dashes_is_refused() -> None:
    registry = ExtensionRegistry()
    with pytest.raises(ExtensionError, match="needs a name"):
        registry.add_collector(BadName())  # type: ignore[arg-type]
    assert NAME_PATTERN.match("good-name-1") is not None
    for bad in ("", "Upper", "1starts-with-digit", "has space", "x" * 41):
        assert NAME_PATTERN.match(bad) is None, bad


def test_two_objects_of_one_point_may_not_share_a_name() -> None:
    registry = ExtensionRegistry()
    first = ref_plugin.NoopCollector()
    registry.add_collector(first)
    with pytest.raises(ExtensionError, match="already a collector named"):
        registry.add_collector(ref_plugin.NoopCollector())
    assert registry.collectors() == (first,)


# --- the loader ---


def test_without_a_plugin_the_registry_is_empty() -> None:
    registry = load_plugins()
    assert registry.plugins == [] and registry.count() == 0
    assert list(entry_points(group=ext.PLUGIN_ENTRY_POINT_GROUP)) == []


def test_a_plugin_instance_and_a_plugin_class_both_load() -> None:
    by_instance = load_plugins([FakePoint("one", Quiet())])
    by_class = load_plugins([FakePoint("two", Quiet)])
    assert by_instance.plugins == by_class.plugins == ["quiet"]


@pytest.mark.parametrize(
    ("point", "reason"),
    [
        (FakePoint("old", type("Old", (Quiet,), {"api_version": 0})), "API 0"),
        (FakePoint("new", type("New", (Quiet,), {"api_version": 2})), "API 2"),
        (FakePoint("text", type("Text", (Quiet,), {"api_version": "1"})), "integer"),
        (FakePoint("flag", type("Flag", (Quiet,), {"api_version": True})), "integer"),
        (FakePoint("bare", object()), "no name"),
        (FakePoint("broken", error=ImportError("no module")), "ImportError"),
        (FakePoint("explodes", type("X", (Quiet,), {"register": None})), "no name"),
    ],
)
def test_a_plugin_that_cannot_be_used_stops_the_load_and_is_named(
    point: FakePoint, reason: str
) -> None:
    with pytest.raises(ExtensionError, match=point.name) as raised:
        load_plugins([point])
    assert reason in str(raised.value)


@pytest.mark.parametrize("bad", ["Bad Name", "", "1start", "x" * 41, "ünï", 5, None])
def test_a_plugin_name_must_match_the_name_pattern(bad: object) -> None:
    plugin = type("Named", (Quiet,), {"name": bad})
    with pytest.raises(ExtensionError, match="odd needs a name") as raised:
        load_plugins([FakePoint("odd", plugin)])
    assert "lower-case letters, digits and dashes" in str(raised.value)


def test_a_plugin_that_registers_a_bad_object_is_refused_by_name() -> None:
    class Greedy(Quiet):
        name = "greedy"

        def register(self, registry: ExtensionRegistry) -> None:
            registry.add_collector(WrongShape())  # type: ignore[arg-type]

    with pytest.raises(ExtensionError, match="greedy was refused"):
        load_plugins([FakePoint("greedy", Greedy())])


def test_a_plugin_that_raises_while_registering_is_refused_by_name() -> None:
    class Failing(Quiet):
        name = "failing"

        def register(self, registry: ExtensionRegistry) -> None:
            raise RuntimeError("the password is hunter2")

    with pytest.raises(ExtensionError, match="failing was refused") as raised:
        load_plugins([FakePoint("failing", Failing())])
    # The reason names the class of the error and never repeats its text.
    assert "RuntimeError" in str(raised.value)
    assert_no_trace_of(raised.value, "hunter2")


def assert_no_trace_of(error: BaseException, text: str) -> None:
    """The text is in neither the message nor any error chained to it, as a log
    would print the whole chain."""
    assert error.__cause__ is None and error.__context__ is None
    seen: BaseException | None = error
    while seen is not None:
        assert text not in str(seen) and text not in repr(seen)
        seen = seen.__cause__ or seen.__context__


@pytest.mark.parametrize(
    "secret_error", [ImportError("token=hunter2"), RuntimeError("token=hunter2")]
)
def test_a_plugin_error_never_reaches_the_log_through_the_chain(
    secret_error: Exception,
) -> None:
    class Failing(Quiet):
        name = "failing"

        def register(self, registry: ExtensionRegistry) -> None:
            raise secret_error

    with pytest.raises(ExtensionError) as register_failed:
        load_plugins([FakePoint("failing", Failing())])
    with pytest.raises(ExtensionError) as import_failed:
        load_plugins([FakePoint("broken", error=secret_error)])
    for raised in (register_failed.value, import_failed.value):
        assert_no_trace_of(raised, "hunter2")
        # What a start-up log prints for the error, chain included.
        assert "hunter2" not in "".join(traceback.format_exception(raised))


def test_a_plugin_error_without_a_chain_still_names_the_plugin() -> None:
    with pytest.raises(ExtensionError, match="The plugin broken was refused") as raised:
        load_plugins([FakePoint("broken", error=ImportError("token=hunter2"))])
    assert str(raised.value).endswith("it raised ImportError.")
    assert raised.value.__suppress_context__ is True


def test_two_plugins_may_not_share_a_name() -> None:
    with pytest.raises(ExtensionError, match="already a plugin named quiet"):
        load_plugins([FakePoint("a", Quiet()), FakePoint("b", Quiet())])


def test_the_reference_plugin_loads_through_a_real_entry_point() -> None:
    registry = load_plugins([reference_point()])
    assert registry.plugins == ["reference"]


def test_the_application_holds_the_registry_and_stops_when_a_plugin_fails(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    app: FastAPI = create_app(settings, engine=make_engine(UNREACHABLE))
    assert isinstance(app.state.extensions, ExtensionRegistry)
    assert app.state.extensions.count() == 0
    given = load_plugins([reference_point()])
    with_plugin = create_app(
        settings, engine=make_engine(UNREACHABLE), extensions=given
    )
    assert with_plugin.state.extensions is given

    def refuse() -> ExtensionRegistry:
        raise ExtensionError("The plugin broken was refused: synthetic.")

    monkeypatch.setattr("app.main.load_plugins", refuse)
    with pytest.raises(ExtensionError, match="broken"):
        create_app(settings, engine=make_engine(UNREACHABLE))


# --- the CE image ---


def copied_sources() -> set[str]:
    """What the Dockerfile copies from the repository into the image."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    pattern = re.compile(r"^COPY (?!--)(\S+) \S+$", re.MULTILINE)
    return set(pattern.findall(dockerfile))


def test_the_image_copies_only_the_application_its_migrations_and_its_data() -> None:
    assert copied_sources() == IMAGE_SOURCES | {"requirements.txt"}


def test_the_image_holds_no_name_that_belongs_to_a_later_edition() -> None:
    hits = []
    checked = 0
    for source in sorted(copied_sources() & IMAGE_SOURCES):
        base = ROOT / source
        files = [base] if base.is_file() else sorted(base.rglob("*"))
        for path in files:
            if not path.is_file() or path.suffix not in IMAGE_SUFFIXES:
                continue
            if "vendor" in path.parts:
                continue
            checked += 1
            found = EE_ONLY_NAMES.search(path.read_text(encoding="utf-8"))
            if found:
                hits.append(f"{path.relative_to(ROOT).as_posix()}: {found.group(0)}")
    assert checked > 100
    assert hits == []


def test_the_image_has_no_plugin_entry_point_of_its_own() -> None:
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert meta["project"]["entry-points"] == {ext.PLUGIN_ENTRY_POINT_GROUP: {}}
    assert list(entry_points(group=ext.PLUGIN_ENTRY_POINT_GROUP)) == []
