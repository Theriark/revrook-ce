"""Saved column mappings (import profiles).

A profile tells one source adapter which column of a vendor's file holds which
column of the contract, for files whose header does not use the names the
adapter knows. It belongs to one client, applies to one source, and is read when
an upload names it (`profile_id`). Phase 4 adds the editor with its preview; this
module is the part that stores a mapping safely.
"""

from collections.abc import Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import add_audit_event
from app.evidence.errors import ClientNotFoundError, EvidenceRejectedError
from app.importers.framework import Column
from app.importers.registry import ImporterRegistry
from app.models import Client, ImportProfile

MAX_NAME_LENGTH = 100
MAX_HEADER_LENGTH = 100
MAX_MAPPING_ENTRIES = 100


def _clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned or len(cleaned) > MAX_NAME_LENGTH:
        raise EvidenceRejectedError(
            f"The profile name must be 1 to {MAX_NAME_LENGTH} characters."
        )
    if not cleaned.isprintable():
        raise EvidenceRejectedError("The profile name must be printable text.")
    return cleaned


def _clean_mapping(
    mapping: Mapping[str, str], columns: Sequence[Column]
) -> dict[str, str]:
    """The mapping with its headers trimmed, or the reason it cannot be saved."""
    if not mapping:
        raise EvidenceRejectedError("The mapping must name at least one column.")
    if len(mapping) > MAX_MAPPING_ENTRIES:
        raise EvidenceRejectedError(
            f"The mapping may name at most {MAX_MAPPING_ENTRIES} columns."
        )
    allowed = {column.key for column in columns}
    cleaned: dict[str, str] = {}
    for header, target in mapping.items():
        name = header.strip()
        if not name or len(name) > MAX_HEADER_LENGTH or not name.isprintable():
            raise EvidenceRejectedError(
                f"A file column name must be 1 to {MAX_HEADER_LENGTH} printable "
                "characters."
            )
        if target not in allowed:
            known = ", ".join(sorted(allowed))
            raise EvidenceRejectedError(
                f"The mapping points a file column to {target!r}, which this source "
                f"does not have. Its columns are: {known}."
            )
        cleaned[name] = target
    if len(set(cleaned.values())) != len(cleaned):
        raise EvidenceRejectedError(
            "Two file columns are mapped to the same column of the source."
        )
    return cleaned


async def save_profile(
    session: AsyncSession,
    registry: ImporterRegistry,
    client_id: int,
    *,
    name: str,
    source_code: str,
    mapping: Mapping[str, str],
    actor_user_id: int | None,
) -> ImportProfile:
    """Store a mapping for one client and source. The caller commits."""
    importer = registry.get(source_code)
    if importer is None:
        raise EvidenceRejectedError(
            f"There is no importer for the source {source_code}."
        )
    columns: Sequence[Column] = getattr(importer, "columns", ())
    if not columns or not hasattr(importer, "with_mapping"):
        raise EvidenceRejectedError(
            f"The source {source_code} does not read CSV files, so it has no "
            "column mapping."
        )
    cleaned_name = _clean_name(name)
    cleaned_mapping = _clean_mapping(mapping, columns)
    if await session.get(Client, client_id) is None:
        raise ClientNotFoundError("There is no client with this id.")
    profile = ImportProfile(
        client_id=client_id,
        name=cleaned_name,
        source_code=source_code,
        mapping=cleaned_mapping,
    )
    session.add(profile)
    await session.flush()
    add_audit_event(
        session,
        "import_profile.created",
        actor_user_id=actor_user_id,
        target_type="import_profile",
        target_id=profile.id,
        detail={"client_id": client_id, "source_code": source_code},
    )
    return profile
