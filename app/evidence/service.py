"""Adding and listing evidence.

An upload goes through these steps, in one database transaction:

1. validate the input (assurance rules, size, time zone, source);
2. lock the client row, so uploads, chain writes and deletion of one client
   happen one at a time;
3. refuse a file this client already has (same SHA-256);
4. for an automatic export, run the importer (through the saved mapping
   profile when one is named), replace every personal identifier with the
   client's pseudonym, and refuse the upload when a stored value still looks
   like an email address;
5. write the item, its first revision and its facts;
6. append a record to the client's hash chain and one audit event;
7. only then keep the file, when the rules say so (a manual artefact always; a
   raw export only when RAW_RETENTION_DAYS is above zero). Any failure before
   this step rolls the transaction back and leaves no file behind.
"""

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import add_audit_event
from app.clients import pseudonym_key
from app.crypto import FieldCipher
from app.evidence.assurance import Assurance
from app.evidence.chain import append_record, canonical_json, iso_utc
from app.evidence.errors import (
    ClientNotFoundError,
    DuplicateEvidenceError,
    EvidenceRejectedError,
    EvidenceTooLargeError,
    ItemNotFoundError,
    PersonalIdentifierError,
)
from app.evidence.expiry import (
    Freshness,
    default_max_age,
    raw_expires_at,
    stale_after,
    state_of_item,
)
from app.evidence.files import FileStore, sha256_hex, storage_key
from app.evidence.locking import lock_client
from app.importers.base import (
    SOURCE_CODE_PATTERN,
    FactValue,
    ImportRejectedError,
    ParsedFact,
    SourceImporter,
)
from app.importers.registry import ImporterRegistry
from app.models import Client, EvidenceItem, EvidenceRevision, Fact, ImportProfile
from app.pseudonym import Pseudonymiser
from app.settings import Settings

MAX_REVIEWER_LENGTH = 100
MAX_NOTE_LENGTH = 2000
FUTURE_TOLERANCE = timedelta(minutes=5)
EARLIEST_TIME = datetime(2000, 1, 1, tzinfo=UTC)
LATEST_EXPIRY = datetime(2200, 1, 1, tzinfo=UTC)
FACT_BATCH_SIZE = 1000
EMAIL_LIKE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


@dataclass(frozen=True)
class EvidenceContext:
    """What the evidence functions need besides a database session."""

    files: FileStore
    cipher: FieldCipher
    importers: ImporterRegistry
    settings: Settings


@dataclass(frozen=True)
class NewEvidence:
    """One upload. `data` is the file; an attestation has none.

    `profile_id` names a saved column mapping for an automatic export.
    """

    source_code: str
    assurance: Assurance
    captured_at: datetime
    data: bytes | None = None
    reviewer: str | None = None
    reviewed_on: date | None = None
    note: str | None = None
    expires_at: datetime | None = None
    uploader_id: int | None = None
    profile_id: int | None = None


@dataclass(frozen=True)
class StoredEvidence:
    """What was written for one upload."""

    item_id: int
    revision_id: int
    revision_number: int
    sha256: str
    size_bytes: int
    source_code: str
    assurance: Assurance
    captured_at: datetime
    expires_at: datetime
    raw_retained: bool
    facts: int


@dataclass(frozen=True)
class EvidenceView:
    """One item for a list, with its freshness at the time asked."""

    item_id: int
    source_code: str
    assurance: Assurance
    captured_at: datetime
    expires_at: datetime | None
    freshness: Freshness
    revisions: int
    files_kept: int
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class _ParsedExport:
    rows: list[tuple[str, dict[str, FactValue]]]
    captured_at: datetime | None
    importer_version: str


def _clean_text(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _megabytes(size: int) -> str:
    return f"{size / 1_048_576:g} MB"


def _check_time_zone(moment: datetime, label: str) -> None:
    if moment.tzinfo is None:
        raise EvidenceRejectedError(
            f"The {label} must include a time zone, for example 2026-10-01T09:00:00Z."
        )


def _validate(ctx: EvidenceContext, evidence: NewEvidence, now: datetime) -> None:
    """Check an upload before anything is locked or stored."""
    if not SOURCE_CODE_PATTERN.match(evidence.source_code):
        raise EvidenceRejectedError(
            "The source code must be 2 to 32 characters: lower-case letters, "
            "digits or dashes, starting with a letter."
        )
    _check_time_zone(evidence.captured_at, "capture time")
    if evidence.captured_at > now + FUTURE_TOLERANCE:
        raise EvidenceRejectedError("The capture time is in the future.")
    if evidence.captured_at < EARLIEST_TIME:
        raise EvidenceRejectedError("The capture time is before the year 2000.")
    if evidence.expires_at is not None:
        _check_time_zone(evidence.expires_at, "expiry time")
        if evidence.expires_at <= evidence.captured_at:
            raise EvidenceRejectedError("The expiry must be after the capture time.")
        if evidence.expires_at > LATEST_EXPIRY:
            raise EvidenceRejectedError("The expiry is after the year 2199.")
    if evidence.reviewer is not None and len(evidence.reviewer) > MAX_REVIEWER_LENGTH:
        raise EvidenceRejectedError(
            f"The reviewer name must be at most {MAX_REVIEWER_LENGTH} characters."
        )
    if evidence.note is not None and len(evidence.note) > MAX_NOTE_LENGTH:
        raise EvidenceRejectedError(
            f"The note must be at most {MAX_NOTE_LENGTH} characters."
        )
    for label, text in (("reviewer", evidence.reviewer), ("note", evidence.note)):
        if text is not None and "\x00" in text:
            raise EvidenceRejectedError(f"The {label} must not contain a NUL byte.")
    if evidence.reviewed_on is not None and evidence.reviewed_on > now.date():
        raise EvidenceRejectedError("The review date is in the future.")
    if (
        evidence.profile_id is not None
        and evidence.assurance is not Assurance.AUTOMATIC_EXPORT
    ):
        raise EvidenceRejectedError(
            "A mapping profile applies to an automatic export only."
        )
    if evidence.assurance is Assurance.ATTESTATION:
        if evidence.data is not None:
            raise EvidenceRejectedError("An attestation has no file.")
        if not (evidence.reviewer and evidence.reviewed_on and evidence.note):
            raise EvidenceRejectedError(
                "An attestation needs a reviewer, a review date and a note."
            )
        return
    if not evidence.data:
        raise EvidenceRejectedError("The file is missing or empty.")
    limit = ctx.settings.import_max_bytes
    if len(evidence.data) > limit:
        raise EvidenceTooLargeError(
            f"The file is larger than the limit of {_megabytes(limit)}."
        )
    if evidence.assurance is Assurance.MANUAL_ARTEFACT and not (
        evidence.reviewer and evidence.reviewed_on
    ):
        raise EvidenceRejectedError(
            "A manual artefact needs a reviewer and a review date."
        )


def _check_file_time(moment: datetime, now: datetime) -> None:
    """The capture time an importer found in a file must be plausible."""
    _check_time_zone(moment, "capture time found in the file")
    if moment > now + FUTURE_TOLERANCE:
        raise EvidenceRejectedError(
            "The capture time found in the file is in the future."
        )
    if moment < EARLIEST_TIME:
        raise EvidenceRejectedError(
            "The capture time found in the file is before the year 2000."
        )


def _clean(evidence: NewEvidence) -> NewEvidence:
    return replace(
        evidence,
        reviewer=_clean_text(evidence.reviewer),
        note=_clean_text(evidence.note),
    )


def _content_identity(evidence: NewEvidence) -> tuple[str, int]:
    """The SHA-256 and size that identify the upload.

    A file is identified by its bytes. An attestation has no file, so it is
    identified by its own text, reviewer and dates: the same statement given on
    another day is a new piece of evidence.
    """
    if evidence.data is not None:
        return sha256_hex(evidence.data), len(evidence.data)
    reviewed = evidence.reviewed_on.isoformat() if evidence.reviewed_on else None
    statement = canonical_json(
        {
            "captured_at": iso_utc(evidence.captured_at),
            "note": evidence.note,
            "reviewed_on": reviewed,
            "reviewer": evidence.reviewer,
        }
    ).encode("ascii")
    return sha256_hex(statement), len(statement)


async def _refuse_duplicate_file(
    session: AsyncSession, client_id: int, sha256: str
) -> None:
    result = await session.execute(
        select(EvidenceItem.id, EvidenceRevision.created_at)
        .join(EvidenceRevision, EvidenceRevision.item_id == EvidenceItem.id)
        .where(EvidenceItem.client_id == client_id, EvidenceRevision.sha256 == sha256)
        .limit(1)
    )
    found = result.first()
    if found is not None:
        item_id, added = found
        raise DuplicateEvidenceError(
            "This file was already uploaded for this client on "
            f"{added.date().isoformat()} (evidence item {item_id}). "
            "Nothing was stored. Upload a different file, or add a revision "
            "to that item.",
            item_id,
        )


def _importer_for(ctx: EvidenceContext, source_code: str) -> SourceImporter:
    importer = ctx.importers.get(source_code)
    if importer is None:
        known = ", ".join(ctx.importers.source_codes()) or "none"
        raise EvidenceRejectedError(
            f"There is no importer for the source {source_code}. "
            f"Sources with an importer: {known}."
        )
    return importer


async def _importer_with_profile(
    session: AsyncSession,
    client_id: int,
    evidence: NewEvidence,
    importer: SourceImporter,
) -> SourceImporter:
    """The importer reading through a saved column mapping.

    The profile must be for this source and belong to this client or to no
    client in particular.
    """
    profile = await session.get(ImportProfile, evidence.profile_id)
    if (
        profile is None
        or profile.source_code != evidence.source_code
        or profile.client_id not in (None, client_id)
    ):
        raise EvidenceRejectedError(
            "There is no such mapping profile for this client and source."
        )
    with_mapping = getattr(importer, "with_mapping", None)
    if with_mapping is None:
        raise EvidenceRejectedError(
            f"The source {evidence.source_code} does not read mapping profiles."
        )
    mapped: SourceImporter = with_mapping(profile.mapping)
    return mapped


def _fact_value(fact: ParsedFact, pseudonymise: Pseudonymiser) -> dict[str, FactValue]:
    """The stored value of a fact: identifiers replaced, nothing personal left."""
    value: dict[str, FactValue] = dict(fact.value)
    for name, identifier in fact.identifiers.items():
        if name in value:
            raise EvidenceRejectedError(
                f"The importer gave the field {name} of {fact.key} twice."
            )
        try:
            value[name] = pseudonymise(identifier)
        except ValueError:
            raise EvidenceRejectedError(
                f"The field {name} of {fact.key} is empty."
            ) from None
    for name, item in value.items():
        if isinstance(item, str) and EMAIL_LIKE.search(item):
            raise PersonalIdentifierError(
                f"The field {name} of {fact.key} looks like an email address. "
                "Nothing was stored."
            )
    return value


async def _parse_export(
    importer: SourceImporter,
    data: bytes,
    pseudonymise: Pseudonymiser,
    max_rows: int,
) -> _ParsedExport:
    try:
        parsed = await asyncio.to_thread(importer.parse, data, max_rows)
    except ImportRejectedError as error:
        raise EvidenceRejectedError(str(error)) from error
    rows = [(fact.key, _fact_value(fact, pseudonymise)) for fact in parsed.facts]
    return _ParsedExport(rows, parsed.captured_at, importer.version)


async def _insert_facts(
    session: AsyncSession,
    client_id: int,
    item_id: int,
    captured_at: datetime,
    rows: list[tuple[str, dict[str, FactValue]]],
) -> None:
    for start in range(0, len(rows), FACT_BATCH_SIZE):
        await session.execute(
            insert(Fact),
            [
                {
                    "client_id": client_id,
                    "evidence_item_id": item_id,
                    "fact_key": key,
                    "value": value,
                    "captured_at": captured_at,
                }
                for key, value in rows[start : start + FACT_BATCH_SIZE]
            ],
        )


def _plan_file(
    ctx: EvidenceContext,
    client_id: int,
    evidence: NewEvidence,
    digest: str,
    now: datetime,
) -> tuple[str | None, datetime | None]:
    """Whether the file is kept, under which key and until when.

    Nothing is written here: the file is written last (see `_write_file`).
    """
    if evidence.data is None:
        return None, None
    if evidence.assurance is Assurance.MANUAL_ARTEFACT:
        return storage_key(client_id, digest), None
    keep_until = raw_expires_at(now, ctx.settings.raw_retention_days)
    if keep_until is None:
        return None, None
    return storage_key(client_id, digest), keep_until


async def _write_file(
    ctx: EvidenceContext,
    client_id: int,
    evidence: NewEvidence,
    key: str | None,
) -> None:
    """Write the file that `_plan_file` decided to keep."""
    if key is not None and evidence.data is not None:
        await asyncio.to_thread(ctx.files.put, client_id, evidence.data)


def _chain_payload(stored: StoredEvidence) -> Mapping[str, object]:
    return {
        "item_id": stored.item_id,
        "revision": stored.revision_number,
        "sha256": stored.sha256,
        "size_bytes": stored.size_bytes,
        "source_code": stored.source_code,
        "assurance": stored.assurance.value,
        "captured_at": iso_utc(stored.captured_at),
        "raw_retained": stored.raw_retained,
        "facts": stored.facts,
    }


async def add_evidence(
    session: AsyncSession,
    ctx: EvidenceContext,
    client_id: int,
    evidence: NewEvidence,
    now: datetime,
) -> StoredEvidence:
    """Store a new evidence item with its first revision. See the module text."""
    evidence = _clean(evidence)
    _validate(ctx, evidence, now)
    importer = (
        _importer_for(ctx, evidence.source_code)
        if evidence.assurance is Assurance.AUTOMATIC_EXPORT
        else None
    )
    client = await lock_client(session, client_id)
    digest, size = _content_identity(evidence)
    await _refuse_duplicate_file(session, client_id, digest)

    parsed: _ParsedExport | None = None
    if importer is not None and evidence.data is not None:
        if evidence.profile_id is not None:
            importer = await _importer_with_profile(
                session, client_id, evidence, importer
            )
        pseudonymise = Pseudonymiser(pseudonym_key(ctx.cipher, client))
        parsed = await _parse_export(
            importer, evidence.data, pseudonymise, ctx.settings.import_max_rows
        )
        if parsed.captured_at is not None:
            _check_file_time(parsed.captured_at, now)
    captured_at = (parsed.captured_at if parsed else None) or evidence.captured_at
    expires_at = evidence.expires_at or stale_after(
        captured_at, default_max_age(evidence.assurance)
    )

    item = EvidenceItem(
        client_id=client_id,
        source_code=evidence.source_code,
        captured_at=captured_at,
        imported_at=now,
        sha256=digest,
        size_bytes=size,
        importer_version=parsed.importer_version if parsed else None,
        uploader_id=evidence.uploader_id,
        assurance_level=evidence.assurance.value,
        status=Freshness.CURRENT.value,
        expires_at=expires_at,
    )
    session.add(item)
    await session.flush()
    if parsed is not None:
        await _insert_facts(session, client_id, item.id, captured_at, parsed.rows)
    key, raw_expires = _plan_file(ctx, client_id, evidence, digest, now)
    revision = EvidenceRevision(
        item_id=item.id,
        revision_number=1,
        sha256=digest,
        size_bytes=size,
        storage_key=key,
        note=evidence.note,
        reviewer=evidence.reviewer,
        reviewed_on=evidence.reviewed_on,
        raw_expires_at=raw_expires,
        created_by_id=evidence.uploader_id,
        created_at=now,
    )
    session.add(revision)
    await session.flush()

    stored = StoredEvidence(
        item_id=item.id,
        revision_id=revision.id,
        revision_number=1,
        sha256=digest,
        size_bytes=size,
        source_code=evidence.source_code,
        assurance=evidence.assurance,
        captured_at=captured_at,
        expires_at=expires_at,
        raw_retained=key is not None,
        facts=len(parsed.rows) if parsed else 0,
    )
    await append_record(
        session,
        client_id=client_id,
        event_type="evidence.added",
        payload=_chain_payload(stored),
        now=now,
        evidence_item_id=item.id,
    )
    add_audit_event(
        session,
        "evidence.added",
        actor_user_id=evidence.uploader_id,
        target_type="evidence_item",
        target_id=item.id,
        detail={
            "client_id": client_id,
            "source_code": evidence.source_code,
            "assurance": evidence.assurance.value,
        },
    )
    await session.flush()
    await _write_file(ctx, client_id, evidence, key)
    return stored


async def add_revision(
    session: AsyncSession,
    ctx: EvidenceContext,
    client_id: int,
    item_id: int,
    evidence: NewEvidence,
    now: datetime,
) -> StoredEvidence:
    """Add a revision to a manual item. The earlier revisions stay as they were."""
    await lock_client(session, client_id)
    result = await session.execute(
        select(EvidenceItem)
        .where(EvidenceItem.id == item_id, EvidenceItem.client_id == client_id)
        .with_for_update()
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise ItemNotFoundError("There is no such evidence item for this client.")
    assurance = Assurance(item.assurance_level)
    if assurance is Assurance.AUTOMATIC_EXPORT:
        raise EvidenceRejectedError(
            "An automatic export cannot be revised. Upload the corrected export "
            "as a new item."
        )
    evidence = _clean(replace(evidence, source_code=item.source_code))
    if evidence.assurance is not assurance:
        raise EvidenceRejectedError("A revision keeps the assurance level.")
    _validate(ctx, evidence, now)
    digest, size = _content_identity(evidence)
    await _refuse_duplicate_file(session, client_id, digest)

    latest = (
        await session.execute(
            select(EvidenceRevision.id, EvidenceRevision.revision_number)
            .where(EvidenceRevision.item_id == item_id)
            .order_by(EvidenceRevision.revision_number.desc())
            .limit(1)
        )
    ).one()
    number = latest.revision_number + 1
    expires_at = evidence.expires_at or stale_after(
        evidence.captured_at, default_max_age(assurance)
    )
    key, raw_expires = _plan_file(ctx, client_id, evidence, digest, now)
    revision = EvidenceRevision(
        item_id=item_id,
        revision_number=number,
        supersedes_id=latest.id,
        sha256=digest,
        size_bytes=size,
        storage_key=key,
        note=evidence.note,
        reviewer=evidence.reviewer,
        reviewed_on=evidence.reviewed_on,
        raw_expires_at=raw_expires,
        created_by_id=evidence.uploader_id,
        created_at=now,
    )
    session.add(revision)
    item.sha256 = digest
    item.size_bytes = size
    item.captured_at = evidence.captured_at
    item.expires_at = expires_at
    item.status = Freshness.CURRENT.value
    await session.flush()

    stored = StoredEvidence(
        item_id=item_id,
        revision_id=revision.id,
        revision_number=number,
        sha256=digest,
        size_bytes=size,
        source_code=item.source_code,
        assurance=assurance,
        captured_at=evidence.captured_at,
        expires_at=expires_at,
        raw_retained=key is not None,
        facts=0,
    )
    await append_record(
        session,
        client_id=client_id,
        event_type="evidence.revised",
        payload=_chain_payload(stored),
        now=now,
        evidence_item_id=item_id,
    )
    add_audit_event(
        session,
        "evidence.revised",
        actor_user_id=evidence.uploader_id,
        target_type="evidence_item",
        target_id=item_id,
        detail={"client_id": client_id, "revision": number},
    )
    await session.flush()
    await _write_file(ctx, client_id, evidence, key)
    return stored


async def list_evidence(
    session: AsyncSession, client_id: int, as_of: datetime
) -> list[EvidenceView]:
    """The client's items, newest capture first, with their freshness at as_of."""
    if await session.get(Client, client_id) is None:
        raise ClientNotFoundError("There is no client with this id.")
    counts = (
        select(
            EvidenceRevision.item_id.label("item_id"),
            func.count().label("revisions"),
            func.count(EvidenceRevision.storage_key).label("files_kept"),
        )
        .group_by(EvidenceRevision.item_id)
        .subquery()
    )
    result = await session.execute(
        select(EvidenceItem, counts.c.revisions, counts.c.files_kept)
        .join(counts, counts.c.item_id == EvidenceItem.id)
        .where(EvidenceItem.client_id == client_id)
        .order_by(EvidenceItem.captured_at.desc(), EvidenceItem.id.desc())
    )
    views: list[EvidenceView] = []
    for item, revisions, files_kept in result.all():
        expires_at = item.expires_at
        freshness = (
            state_of_item(item.captured_at, expires_at, as_of)
            if expires_at is not None
            else Freshness.CURRENT
        )
        views.append(
            EvidenceView(
                item_id=item.id,
                source_code=item.source_code,
                assurance=Assurance(item.assurance_level),
                captured_at=item.captured_at,
                expires_at=expires_at,
                freshness=freshness,
                revisions=revisions,
                files_kept=files_kept,
                sha256=item.sha256,
                size_bytes=item.size_bytes,
            )
        )
    return views
