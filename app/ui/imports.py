"""Import evidence: every export of a client in one go, and the public DNS check.

`/imports` takes one or more files for one client. Each file is matched to its
source by its header or its JSON fields (`app.importers.detect`), so nobody picks a
source per file, and each is stored on its own: a file that is refused does not
stop the others. A vendor export with other column names is mapped once in the
profile editor; its saved mapping is recognised here from then on.

`POST /clients/{id}/dns-check` runs the public DNS check of the client's mail
domains from the evidence page, and can keep it running every week as a schedule
of the worker. Only DNS questions about the entered names leave the instance.
"""

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response
from sqlalchemy import or_, select
from starlette.datastructures import FormData, UploadFile

from app.audit import add_audit_event
from app.checks.dnscheck import (
    MAX_DOMAINS,
    MAX_SELECTORS,
    clean_domains,
    clean_selectors,
)
from app.dns_service import look_up_dns, require_client, store_dns_check
from app.evidence.assurance import Assurance
from app.evidence.errors import EvidenceError
from app.evidence.service import NewEvidence, add_evidence
from app.importers.base import FactValue, ImportRejectedError
from app.importers.detect import Candidate, detect
from app.importers.generic import CsvAdapter
from app.importers.microsoft import MicrosoftAdapter
from app.models import AppUser, Client, Fact, ImportProfile, Schedule
from app.sources import DNS_SOURCE, is_shown, source_name
from app.ui.auth import redirect
from app.ui.common import FormError, RowId, guarded, message_of, page
from app.web import clock_of, evidence_context, session_factory
from app.worker.cron import next_run_for
from app.worker.scheduler import DNS_CHECK

router = APIRouter()
PATH = "/imports"
TEMPLATE = "imports.html"
TITLE = "Import evidence"
MAX_FILES = 20
MAX_FORM_FIELDS = 10
MAX_ID_DIGITS = 18
MAX_FILE_NAME = 120
MAX_DNS_FIELD = 4000
# Every Monday at 05:00 UTC: one DNS check a week keeps the 35-day evidence current.
WEEKLY_CRON = "0 5 * * 1"
DNS_SEPARATORS = re.compile(r"[\s,;]+")


@dataclass(frozen=True)
class FileResult:
    """What happened to one file of an import."""

    name: str
    stored: bool
    source: str | None
    message: str
    facts: int = 0
    rejected: int = 0


async def _clients(request: Request) -> list[tuple[int, str]]:
    async with session_factory(request)() as db:
        rows = await db.execute(
            select(Client.id, Client.name)
            .where(Client.archived_at.is_(None))
            .order_by(Client.name, Client.id)
        )
        return [(client_id, name) for client_id, name in rows.all()]


def file_sources(request: Request) -> list[MicrosoftAdapter | CsvAdapter]:
    """The importers a person can feed with a file, in the order of their names."""
    registry = request.app.state.importers
    found: list[MicrosoftAdapter | CsvAdapter] = []
    for code in registry.source_codes():
        importer = registry.get(code)
        if is_shown(code) and isinstance(importer, MicrosoftAdapter | CsvAdapter):
            found.append(importer)
    return sorted(found, key=lambda adapter: source_name(adapter.source_code))


def file_kind(adapter: MicrosoftAdapter | CsvAdapter) -> str:
    """The files an importer reads, in words for the list of the import page."""
    if isinstance(adapter, CsvAdapter):
        return "CSV"
    if adapter.columns:
        return "JSON from Microsoft Graph, or CSV"
    return "JSON from Microsoft Graph"


async def _candidates(request: Request, client_id: int) -> list[Candidate]:
    """Every way of reading a file of this client: each importer as it is, and
    each saved column mapping of the client (or of every client)."""
    adapters = file_sources(request)
    by_code = {adapter.source_code: adapter for adapter in adapters}
    candidates = [Candidate(adapter) for adapter in adapters]
    async with session_factory(request)() as db:
        rows = await db.execute(
            select(ImportProfile.id, ImportProfile.source_code, ImportProfile.mapping)
            .where(
                or_(
                    ImportProfile.client_id == client_id,
                    ImportProfile.client_id.is_(None),
                )
            )
            .order_by(ImportProfile.id.desc())
        )
        for profile_id, code, mapping in rows.all():
            adapter = by_code.get(code)
            if adapter is not None and mapping:
                candidates.append(Candidate(adapter.with_mapping(mapping), profile_id))
    return candidates


def _text(form: FormData, name: str) -> str:
    value = form.get(name)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise FormError(f"The field {name} must be text.")
    return value.strip()


def _client_id(form: FormData) -> int:
    value = _text(form, "client_id")
    if not value:
        raise FormError("Choose a client.")
    if not value.isascii() or not value.isdecimal() or len(value) > MAX_ID_DIGITS:
        raise FormError("The field client_id must be a whole number.")
    return int(value)


def _capture_time(form: FormData, now: datetime) -> datetime:
    """When the files were exported; empty is now, and a time without a zone is UTC."""
    value = _text(form, "captured_at")
    if not value:
        return now
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise FormError(
            "The export time must be a date and time such as 2026-10-01T09:00."
        ) from None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _file_name(upload: UploadFile, number: int) -> str:
    """The name of a file for the result list only; it is never stored."""
    name = (upload.filename or "").strip()
    if not name or not name.isprintable():
        return f"File {number}"
    return name[:MAX_FILE_NAME]


def _base_context(request: Request, now: datetime) -> dict[str, Any]:
    limit: int = request.app.state.settings.import_max_bytes
    return {
        "title": TITLE,
        "nav": "imports",
        "clients": [],
        "client_id": None,
        "captured_at": now.strftime("%Y-%m-%dT%H:%M"),
        "max_megabytes": f"{limit / 1_048_576:g}",
        "max_files": MAX_FILES,
        "sources": [
            (adapter.source_code, source_name(adapter.source_code), file_kind(adapter))
            for adapter in file_sources(request)
        ],
        "results": [],
        "errors": [],
    }


def _chosen(request: Request, clients: list[tuple[int, str]]) -> int | None:
    value = request.query_params.get("client_id", "")
    if not value.isascii() or not value.isdecimal() or len(value) > MAX_ID_DIGITS:
        return None
    chosen = int(value)
    return chosen if any(client_id == chosen for client_id, _ in clients) else None


@router.get(PATH)
async def imports_page(request: Request) -> Response:
    async def handle(user: AppUser) -> Response:
        now = clock_of(request)().astimezone(UTC)
        context = _base_context(request, now)
        context["clients"] = await _clients(request)
        context["client_id"] = _chosen(request, context["clients"])
        return page(request, TEMPLATE, user, context)

    return await guarded(request, handle)


async def _store(
    request: Request,
    user: AppUser,
    client_id: int,
    candidate: Candidate,
    data: bytes,
    captured_at: datetime,
) -> tuple[int, int]:
    """Store one file as evidence; the number of facts and of rejected rows."""
    evidence = NewEvidence(
        source_code=candidate.adapter.source_code,
        assurance=Assurance.AUTOMATIC_EXPORT,
        captured_at=captured_at,
        data=data,
        uploader_id=user.id,
        profile_id=candidate.profile_id,
    )
    async with session_factory(request)() as db, db.begin():
        stored = await add_evidence(
            db, evidence_context(request), client_id, evidence, clock_of(request)()
        )
        found = await db.execute(
            select(Fact.value).where(
                Fact.evidence_item_id == stored.item_id,
                Fact.fact_key.like("%.summary"),
            )
        )
        summary: dict[str, FactValue] = found.scalars().first() or {}
    rejected = summary.get("rows_rejected", 0)
    return stored.facts, rejected if isinstance(rejected, int) else 0


async def _import_one(
    request: Request,
    user: AppUser,
    client_id: int,
    candidates: list[Candidate],
    upload: UploadFile,
    number: int,
    captured_at: datetime,
) -> FileResult:
    name = _file_name(upload, number)
    limit: int = request.app.state.settings.import_max_bytes
    data = await upload.read(limit + 1)
    if not data:
        return FileResult(name, False, None, "The file is empty.")
    if len(data) > limit:
        return FileResult(
            name, False, None, f"The file is larger than {limit / 1_048_576:g} MB."
        )
    # Decoding and reading the header of up to 20 MB must not stall the event loop.
    found = await asyncio.to_thread(detect, data, candidates)
    if found.candidate is None:
        return FileResult(name, False, None, found.problem or "")
    source = source_name(found.candidate.adapter.source_code)
    try:
        facts, rejected = await _store(
            request, user, client_id, found.candidate, data, captured_at
        )
    except EvidenceError as error:
        return FileResult(name, False, source, message_of(error))
    except ImportRejectedError as error:
        return FileResult(name, False, source, str(error))
    how = "with its saved column mapping" if found.candidate.profile_id else ""
    message = " ".join(part for part in ("Imported", how) if part) + "."
    return FileResult(name, True, source, message, facts, rejected)


@router.post(PATH)
async def imports_post(request: Request) -> Response:
    async def handle(user: AppUser) -> Response:
        now = clock_of(request)().astimezone(UTC)
        context = _base_context(request, now)
        context["clients"] = await _clients(request)
        form = await request.form(max_files=MAX_FILES, max_fields=MAX_FORM_FIELDS)
        try:
            client_id = _client_id(form)
            context["client_id"] = client_id
            if not any(client_id == known for known, _ in context["clients"]):
                raise FormError("There is no client with this id.", 404)
            captured_at = _capture_time(form, now)
            context["captured_at"] = captured_at.strftime("%Y-%m-%dT%H:%M")
            uploads = [
                item for item in form.getlist("files") if isinstance(item, UploadFile)
            ]
            if not uploads:
                raise FormError("Choose at least one file to import.")
            candidates = await _candidates(request, client_id)
            results = [
                await _import_one(
                    request, user, client_id, candidates, upload, number, captured_at
                )
                for number, upload in enumerate(uploads, start=1)
            ]
        except FormError as error:
            context["errors"] = [str(error)]
            return page(request, TEMPLATE, user, context, error.status_code)
        finally:
            await form.close()
        context["results"] = results
        context["stored"] = sum(1 for item in results if item.stored)
        status = 200 if context["stored"] else 422
        return page(request, TEMPLATE, user, context, status)

    return await guarded(request, handle)


# --- the public DNS check, from the evidence page of a client ---------------------


def _names(form: FormData, field: str, most: int, what: str) -> list[str]:
    value = _text(form, field)
    if len(value) > MAX_DNS_FIELD:
        raise FormError(f"The list of {what} is too long.")
    names = [name for name in DNS_SEPARATORS.split(value) if name]
    if len(names) > most:
        raise FormError(f"Enter at most {most} {what}.")
    return names


async def dns_schedule(request: Request, client_id: int) -> Schedule | None:
    """The weekly DNS check of a client, if there is one."""
    async with session_factory(request)() as db:
        found = await db.execute(
            select(Schedule)
            .where(Schedule.kind == DNS_CHECK, Schedule.client_id == client_id)
            .order_by(Schedule.id)
            .limit(1)
        )
        return found.scalar_one_or_none()


async def _keep_weekly(
    request: Request,
    user: AppUser,
    client_id: int,
    config: dict[str, list[str]],
    weekly: bool,
    now: datetime,
) -> None:
    """Create, update or switch off the weekly DNS check of the client."""
    async with session_factory(request)() as db, db.begin():
        found = await db.execute(
            select(Schedule)
            .where(Schedule.kind == DNS_CHECK, Schedule.client_id == client_id)
            .order_by(Schedule.id)
            .limit(1)
            .with_for_update()
        )
        row = found.scalar_one_or_none()
        if row is None and not weekly:
            return
        if row is None:
            row = Schedule(
                name=f"{DNS_CHECK}-client-{client_id}",
                kind=DNS_CHECK,
                cron=WEEKLY_CRON,
                client_id=client_id,
                next_run_at=next_run_for(WEEKLY_CRON, now),
                config=config,
            )
            db.add(row)
            await db.flush()
            action = "schedule.created"
        else:
            row.enabled = weekly
            if weekly:
                row.config = config
                row.next_run_at = next_run_for(row.cron, now)
            action = "schedule.updated"
        add_audit_event(
            db,
            action,
            actor_user_id=user.id,
            target_type="schedule",
            target_id=row.id,
            detail={"kind": DNS_CHECK, "client_id": client_id, "enabled": weekly},
        )


@router.post("/clients/{client_id}/dns-check")
async def dns_check_post(request: Request, client_id: RowId) -> Response:
    async def handle(user: AppUser) -> Response:
        form = await request.form(max_files=0, max_fields=MAX_FORM_FIELDS)
        try:
            domains = _names(form, "domains", MAX_DOMAINS, "mail domains")
            selectors = _names(form, "selectors", MAX_SELECTORS, "DKIM selectors")
            weekly = _text(form, "weekly") == "on"
        finally:
            await form.close()
        if not domains:
            raise FormError("Enter at least one mail domain, such as example.com.")
        try:
            config = {
                "domains": list(clean_domains(domains)),
                "selectors": list(clean_selectors(selectors)),
                "providers": [],
            }
        except ValueError as error:
            raise FormError(str(error)) from None
        now = clock_of(request)()
        async with session_factory(request)() as db:
            await require_client(db, client_id)
        # No database connection is held while the DNS answers (as in the API).
        check = await look_up_dns(
            request.app.state.dns_resolver,
            config["domains"],
            config["selectors"],
            now=now,
        )
        async with session_factory(request)() as db, db.begin():
            await store_dns_check(
                db,
                evidence_context(request),
                client_id,
                check,
                now=now,
                actor_user_id=user.id,
            )
        await _keep_weekly(request, user, client_id, config, weekly, now)
        done = "dns-weekly" if weekly else "dns"
        return redirect(f"/clients/{client_id}/evidence?done={done}#{DNS_SOURCE}")

    return await guarded(request, handle)
