"""Which importer handles which source code."""

from app.importers.base import SOURCE_CODE_PATTERN, SourceImporter
from app.importers.generic import ADAPTERS as GENERIC_ADAPTERS
from app.importers.microsoft import ADAPTERS
from app.importers.reference import ReferenceCsvImporter


class ImporterRegistry:
    """Importers by source code. The web application owns one instance."""

    def __init__(self) -> None:
        self._importers: dict[str, SourceImporter] = {}

    def register(self, importer: SourceImporter) -> None:
        code = importer.source_code
        if not SOURCE_CODE_PATTERN.match(code):
            raise ValueError(f"{code!r} is not a valid source code")
        if code in self._importers:
            raise ValueError(f"an importer for {code!r} is already registered")
        self._importers[code] = importer

    def get(self, source_code: str) -> SourceImporter | None:
        return self._importers.get(source_code)

    def source_codes(self) -> list[str]:
        return sorted(self._importers)


def build_default_registry() -> ImporterRegistry:
    """The importers that ship with this version.

    The reference importer proves the pipeline; phase 3 adds the five Microsoft
    sources and phase 4 the six generic and administrative ones.
    """
    registry = ImporterRegistry()
    registry.register(ReferenceCsvImporter())
    for adapter in ADAPTERS:
        registry.register(adapter)
    for generic in GENERIC_ADAPTERS:
        registry.register(generic)
    return registry
