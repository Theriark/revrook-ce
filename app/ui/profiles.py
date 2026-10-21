"""The mapping profile editor: map a vendor file, preview 20 rows, save, import.

The MSP picks a client, a source and a vendor export whose column names differ
from the contract, chooses a file column for each column of the source, and
sees the first 20 rows the way the importer reads them (app/importers/preview.py).
It then saves the choices as a mapping profile and imports the file with it,
through the same functions the API uses (save_profile, add_evidence).

The forms post with htmx so the chosen file stays in the page between steps;
without JavaScript every button posts the whole page. The file is only read: it
is kept, as for any upload, only when it is imported and the retention rules say
so. Nothing of its content is logged.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response
from sqlalchemy import or_, select
from starlette.datastructures import FormData, UploadFile

from app.auth import get_user
from app.checks.library import Control, Library
from app.clients import pseudonym_key
from app.evidence.assurance import Assurance
from app.evidence.errors import (
    DuplicateEvidenceError,
    EvidenceError,
    EvidenceStorageError,
    EvidenceTooLargeError,
)
from app.evidence.service import NewEvidence, add_evidence
from app.importers.base import FactValue, ImportRejectedError
from app.importers.generic import CsvAdapter
from app.importers.preview import Preview, build_preview, editor_adapters
from app.importers.profiles import save_profile
from app.models import AppUser, Client, Fact, ImportProfile
from app.pseudonym import Pseudonymiser
from app.ui.auth import redirect, render
from app.web import (
    cipher_of,
    clock_of,
    current_session,
    evidence_context,
    session_factory,
)

router = APIRouter()
EDITOR_TITLE = "Profile editor"
EDITOR_PATH = "/imports/profile-editor"
PAGE_TEMPLATE = "profile_editor.html"
RESULT_TEMPLATE = "_profile_editor_result.html"
MAP_PREFIX = "map-"
MAX_FORM_FIELDS = 100
MAX_ID_DIGITS = 18
STORE_FAILED = "The evidence store failed. Nothing was stored."


class FormError(Exception):
    """A field of the editor form is missing or not valid."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def _is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


async def _signed_in_user(request: Request) -> AppUser | None:
    session = current_session(request)
    if session.user_id is None:
        return None
    async with session_factory(request)() as db:
        return await get_user(db, session.user_id)


def _to_login(request: Request) -> Response:
    if _is_htmx(request):
        return Response(status_code=200, headers={"HX-Redirect": "/login"})
    return redirect("/login")


def _status_of(error: EvidenceError) -> int:
    if isinstance(error, DuplicateEvidenceError):
        return 409
    if isinstance(error, EvidenceTooLargeError):
        return 413
    if isinstance(error, EvidenceStorageError):
        return 500
    return 422


def _message_of(error: EvidenceError) -> str:
    if isinstance(error, EvidenceStorageError):
        return STORE_FAILED
    return str(error)


def _text(form: FormData, name: str) -> str:
    value = form.get(name)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise FormError(f"The field {name} must be text.")
    return value.strip()


def _whole_number(form: FormData, name: str, missing: str) -> int:
    value = _text(form, name)
    if not value:
        raise FormError(missing)
    if not value.isascii() or not value.isdecimal() or len(value) > MAX_ID_DIGITS:
        raise FormError(f"The field {name} must be a whole number.")
    return int(value)


def _capture_time(form: FormData) -> datetime:
    """The capture time given with an import; a time without a zone is UTC."""
    value = _text(form, "captured_at")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise FormError(
            "The capture time must be a date and time such as 2026-10-01T09:00."
        ) from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment


async def _file_bytes(form: FormData, limit: int) -> bytes:
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise FormError("Choose a file to read.")
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise FormError(
            f"The file is larger than the limit of {limit / 1_048_576:g} MB.", 413
        )
    if not data:
        raise FormError("Choose a file to read.")
    return data


def _chosen(form: FormData) -> dict[str, str]:
    """The editor's choices: column key to file column (an empty choice is none)."""
    chosen: dict[str, str] = {}
    for name, value in form.multi_items():
        if name.startswith(MAP_PREFIX) and isinstance(value, str) and value.strip():
            chosen[name.removeprefix(MAP_PREFIX)] = value
    return chosen


def _adapter(sources: list[CsvAdapter], code: str) -> CsvAdapter:
    for adapter in sources:
        if adapter.source_code == code:
            return adapter
    raise FormError("Choose one of the listed sources.")


async def _clients(request: Request) -> list[tuple[int, str]]:
    async with session_factory(request)() as db:
        rows = await db.execute(
            select(Client.id, Client.name)
            .where(Client.archived_at.is_(None))
            .order_by(Client.name, Client.id)
        )
        return [(client_id, name) for client_id, name in rows.all()]


async def _client(request: Request, client_id: int) -> Client:
    async with session_factory(request)() as db:
        client = await db.get(Client, client_id)
    if client is None:
        raise FormError("There is no client with this id.")
    return client


async def _profiles(
    request: Request, client_id: int, source_code: str
) -> list[tuple[int, str]]:
    """The saved profiles an import of this client and source may use."""
    async with session_factory(request)() as db:
        rows = await db.execute(
            select(ImportProfile.id, ImportProfile.name)
            .where(
                ImportProfile.source_code == source_code,
                or_(
                    ImportProfile.client_id == client_id,
                    ImportProfile.client_id.is_(None),
                ),
            )
            .order_by(ImportProfile.id.desc())
        )
        return [(profile_id, name) for profile_id, name in rows.all()]


def _display(value: FactValue) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def controls_reading(library: Library, source_code: str) -> tuple[Control, ...]:
    """The controls that read the source of an importer, in the order of the library.

    A control names the fields its rule reads, and the field map of the library
    says which importer carries each one (the sources of a control are the letter
    codes of the report, H for the leavers file, not importer codes). An import
    changes only these controls; the result card names them so that a checklist
    with most of its controls still unchecked after one import is no surprise.
    """
    return tuple(
        item for item in library.controls if _reads(library, item, source_code)
    )


def _reads(library: Library, control: Control, source_code: str) -> bool:
    for field_id in control.fields:
        target = library.field_map.get(field_id)
        if target is not None and target.adapter == source_code:
            return True
    return False


def _chosen_client(request: Request, clients: list[tuple[int, str]]) -> int | None:
    """The client the page was opened for (`?client_id=`), when it is one of the
    listed clients; otherwise none, and the first client stays chosen."""
    value = request.query_params.get("client_id", "")
    if not value.isascii() or not value.isdecimal() or len(value) > MAX_ID_DIGITS:
        return None
    chosen = int(value)
    return chosen if any(client_id == chosen for client_id, _ in clients) else None


async def _base_context(request: Request, user: AppUser) -> dict[str, Any]:
    sources = editor_adapters(request.app.state.importers)
    now = clock_of(request)().astimezone(UTC)
    limit: int = request.app.state.settings.import_max_bytes
    return {
        "title": EDITOR_TITLE,
        "nav": "profile-editor",
        "user": user,
        "clients": await _clients(request),
        "sources": [(adapter.source_code, adapter.label) for adapter in sources],
        "client_id": None,
        "source_code": "",
        "name": "",
        "captured_at": now.strftime("%Y-%m-%dT%H:%M"),
        "max_megabytes": f"{limit / 1_048_576:g}",
        "preview": None,
        "profiles": [],
        "profile_id": None,
        "errors": [],
        "saved": None,
        "imported": None,
    }


def _respond(request: Request, context: dict[str, Any], status: int) -> Response:
    """The result part for htmx, the whole page otherwise."""
    name = RESULT_TEMPLATE if _is_htmx(request) else PAGE_TEMPLATE
    return render(request, name, context, current_session(request), status)


@router.get(EDITOR_PATH)
async def editor_page(request: Request) -> Response:
    user = await _signed_in_user(request)
    if user is None:
        return redirect("/login")
    context = await _base_context(request, user)
    context["client_id"] = _chosen_client(request, context["clients"])
    return render(request, PAGE_TEMPLATE, context, current_session(request))


async def _save(
    request: Request,
    context: dict[str, Any],
    form: FormData,
    preview: Preview,
    user: AppUser,
) -> None:
    if preview.problem is not None:
        raise FormError(f"The profile was not saved. {preview.problem}")
    async with session_factory(request)() as db, db.begin():
        profile = await save_profile(
            db,
            request.app.state.importers,
            context["client_id"],
            name=_text(form, "name"),
            source_code=context["source_code"],
            mapping=preview.mapping(),
            actor_user_id=user.id,
        )
    context["saved"] = {"id": profile.id, "name": profile.name}
    context["profile_id"] = profile.id


async def _import(
    request: Request,
    context: dict[str, Any],
    form: FormData,
    data: bytes,
    user: AppUser,
) -> None:
    profile_id = _whole_number(
        form, "profile_id", "Choose a saved profile to import with."
    )
    context["profile_id"] = profile_id
    evidence = NewEvidence(
        source_code=context["source_code"],
        assurance=Assurance.AUTOMATIC_EXPORT,
        captured_at=_capture_time(form),
        data=data,
        uploader_id=user.id,
        profile_id=profile_id,
    )
    async with session_factory(request)() as db, db.begin():
        stored = await add_evidence(
            db,
            evidence_context(request),
            context["client_id"],
            evidence,
            clock_of(request)(),
        )
        found = await db.execute(
            select(Fact.value).where(
                Fact.evidence_item_id == stored.item_id,
                Fact.fact_key.like("%.summary"),
            )
        )
        summary: dict[str, FactValue] = found.scalars().first() or {}
    library: Library = request.app.state.library
    context["imported"] = {
        "item_id": stored.item_id,
        "profile_id": profile_id,
        "facts": stored.facts,
        "summary": [(key, _display(value)) for key, value in summary.items()],
        "controls": [
            (item.id, item.title)
            for item in controls_reading(library, context["source_code"])
        ],
        "control_total": len(library.controls),
    }


async def _handle(request: Request, action: str) -> Response:
    """Preview, save or import: each reads the form and shows the preview again."""
    user = await _signed_in_user(request)
    if user is None:
        return _to_login(request)
    context = await _base_context(request, user)
    status = 200
    form = await request.form(max_files=1, max_fields=MAX_FORM_FIELDS)
    try:
        context["source_code"] = _text(form, "source_code")
        context["name"] = _text(form, "name")
        if _text(form, "captured_at"):
            context["captured_at"] = _text(form, "captured_at")
        client_id = _whole_number(form, "client_id", "Choose a client.")
        context["client_id"] = client_id
        sources = editor_adapters(request.app.state.importers)
        adapter = _adapter(sources, context["source_code"])
        client = await _client(request, client_id)
        limit: int = request.app.state.settings.import_max_bytes
        data = await _file_bytes(form, limit)
        if action == "import":
            # The import reads the file itself; the preview would only repeat that
            # work, so it is not built for this action.
            await _import(request, context, form, data, user)
            status = 201
        else:
            pseudonymise = Pseudonymiser(pseudonym_key(cipher_of(request), client))
            max_rows: int = request.app.state.settings.import_max_rows
            # Decoding and tokenising up to 20 MB must not stall the event loop.
            preview = await asyncio.to_thread(
                build_preview, adapter, data, _chosen(form), pseudonymise, max_rows
            )
            context["preview"] = preview
            if action == "save":
                await _save(request, context, form, preview, user)
                status = 201
    except FormError as error:
        context["errors"] = [str(error)]
        status = error.status_code
    except ImportRejectedError as error:
        context["errors"] = [str(error)]
        status = 422
    except EvidenceError as error:
        context["errors"] = [_message_of(error)]
        status = _status_of(error)
    finally:
        await form.close()
    if context["client_id"] is not None and context["source_code"]:
        context["profiles"] = await _profiles(
            request, context["client_id"], context["source_code"]
        )
    return _respond(request, context, status)


@router.post(f"{EDITOR_PATH}/preview")
async def editor_preview(request: Request) -> Response:
    return await _handle(request, "preview")


@router.post(f"{EDITOR_PATH}/save")
async def editor_save(request: Request) -> Response:
    return await _handle(request, "save")


@router.post(f"{EDITOR_PATH}/import")
async def editor_import(request: Request) -> Response:
    return await _handle(request, "import")
