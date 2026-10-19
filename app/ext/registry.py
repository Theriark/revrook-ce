"""The registry of extension API version 1 and the loader of plugins.

A plugin is an installed package that names an object in the entry point group
`revrook.plugins`. The object is a plugin instance, or a class that takes no
arguments. It has a `name`, an `api_version` equal to `EXTENSION_API_VERSION`, and a
`register(registry)` method that hands its extension objects to the registry.

Loading fails closed: a plugin that cannot be imported, speaks another API version,
registers an object that does not implement its point, or repeats a name stops the
start-up with a message that names the plugin. Without a plugin the registry is
empty and the product behaves as the Community Edition.
"""

import re
from collections.abc import Iterable, Sequence
from importlib.metadata import entry_points
from typing import Any, Protocol, runtime_checkable

from app.ext import EXTENSION_API_VERSION, PLUGIN_ENTRY_POINT_GROUP
from app.ext.protocols import (
    AuthProvider,
    CollectorProvider,
    FrameworkPack,
    QuestionnairePack,
    ReportTemplate,
    RetentionPolicy,
    UiExtension,
)

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
POINTS: dict[str, type] = {
    "collector": CollectorProvider,
    "framework": FrameworkPack,
    "questionnaire": QuestionnairePack,
    "report-template": ReportTemplate,
    "auth-provider": AuthProvider,
    "retention-policy": RetentionPolicy,
    "ui-extension": UiExtension,
}


class ExtensionError(Exception):
    """A plugin or an extension object was refused. The message is readable."""


@runtime_checkable
class Plugin(Protocol):
    """What an entry point of the plugin group resolves to."""

    name: str
    api_version: int

    def register(self, registry: "ExtensionRegistry") -> None: ...


class EntryPointLike(Protocol):
    """The part of `importlib.metadata.EntryPoint` the loader uses."""

    @property
    def name(self) -> str: ...

    def load(self) -> Any: ...


class ExtensionRegistry:
    """The extension objects of every loaded plugin, by point."""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {kind: {} for kind in POINTS}
        self.plugins: list[str] = []

    def _add(self, kind: str, item: object) -> None:
        if not isinstance(item, POINTS[kind]):
            raise ExtensionError(f"The object does not implement the {kind} point.")
        name = getattr(item, "name", None)
        if not isinstance(name, str) or NAME_PATTERN.match(name) is None:
            raise ExtensionError(
                f"A {kind} needs a name of lower-case letters, digits and dashes."
            )
        if name in self._items[kind]:
            raise ExtensionError(f"There is already a {kind} named {name}.")
        self._items[kind][name] = item

    def add_collector(self, item: CollectorProvider) -> None:
        self._add("collector", item)

    def add_framework(self, item: FrameworkPack) -> None:
        self._add("framework", item)

    def add_questionnaire(self, item: QuestionnairePack) -> None:
        self._add("questionnaire", item)

    def add_report_template(self, item: ReportTemplate) -> None:
        self._add("report-template", item)

    def add_auth_provider(self, item: AuthProvider) -> None:
        self._add("auth-provider", item)

    def add_retention_policy(self, item: RetentionPolicy) -> None:
        self._add("retention-policy", item)

    def add_ui_extension(self, item: UiExtension) -> None:
        self._add("ui-extension", item)

    def collectors(self) -> tuple[CollectorProvider, ...]:
        return tuple(self._items["collector"].values())

    def frameworks(self) -> tuple[FrameworkPack, ...]:
        return tuple(self._items["framework"].values())

    def questionnaires(self) -> tuple[QuestionnairePack, ...]:
        return tuple(self._items["questionnaire"].values())

    def report_templates(self) -> tuple[ReportTemplate, ...]:
        return tuple(self._items["report-template"].values())

    def auth_providers(self) -> tuple[AuthProvider, ...]:
        return tuple(self._items["auth-provider"].values())

    def retention_policies(self) -> tuple[RetentionPolicy, ...]:
        return tuple(self._items["retention-policy"].values())

    def ui_extensions(self) -> tuple[UiExtension, ...]:
        return tuple(self._items["ui-extension"].values())

    def count(self) -> int:
        """How many extension objects are registered, over every point."""
        return sum(len(items) for items in self._items.values())


def discover_entry_points() -> Sequence[EntryPointLike]:
    """The installed entry points of the plugin group, by name."""
    found = entry_points(group=PLUGIN_ENTRY_POINT_GROUP)
    return sorted(found, key=lambda point: point.name)


def _plugin_of(loaded: object, label: str) -> Plugin:
    plugin = loaded() if isinstance(loaded, type) else loaded
    if not isinstance(plugin, Plugin):
        raise ExtensionError(f"{label} has no name, api_version or register.")
    if type(plugin.api_version) is not int:
        raise ExtensionError(f"{label} has no integer api_version.")
    if plugin.api_version != EXTENSION_API_VERSION:
        raise ExtensionError(
            f"{label} was written for extension API {plugin.api_version}; "
            f"this revrook speaks version {EXTENSION_API_VERSION}."
        )
    name: object = plugin.name
    if not isinstance(name, str) or NAME_PATTERN.match(name) is None:
        raise ExtensionError(
            f"{label} needs a name of lower-case letters, digits and dashes."
        )
    return plugin


def load_plugins(points: Iterable[EntryPointLike] | None = None) -> ExtensionRegistry:
    """Load every plugin into a new registry. Without arguments it reads the group.

    The result is empty when no plugin is installed, which is the case of the
    Community Edition image.
    """
    registry = ExtensionRegistry()
    for point in discover_entry_points() if points is None else points:
        # The failure is raised after the try block, not inside its handlers: the
        # plugin's own error, whose text could hold a secret, is then neither the
        # cause nor the context of the error that reaches the start-up log.
        failure: str | None = None
        try:
            plugin = _plugin_of(point.load(), point.name)
            if plugin.name in registry.plugins:
                raise ExtensionError(f"There is already a plugin named {plugin.name}.")
            plugin.register(registry)
        except ExtensionError as error:
            failure = str(error)
        except Exception as error:
            failure = f"it raised {type(error).__name__}."
        if failure is not None:
            refused = f"The plugin {point.name} was refused: {failure}"
            raise ExtensionError(refused) from None
        registry.plugins.append(plugin.name)
    return registry
