"""JSON API, authenticated with a Bearer API token (rate limited per token)."""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from starlette.datastructures import FormData, UploadFile

from app.auth import user_for_api_token
from app.clients import create_client
from app.evidence.assurance import Assurance
from app.evidence.chain import verify_chain
from app.evidence.deletion import delete_client
from app.evidence.errors import (
    ClientNotFoundError,
    DuplicateEvidenceError,
    EvidenceError,
    EvidenceStorageError,
    EvidenceTooLargeError,
    ItemNotFoundError,
)
from app.evidence.service import (
    NewEvidence,
    StoredEvidence,
    add_evidence,
    add_revision,
    list_evidence,
)
from app.models import ApiToken, AppUser, Client
from app.ratelimit import SlidingWindowLimiter
from app.web import cipher_of, clock_of, evidence_context, files_of, session_factory

API_RATE_LIMIT = 120
API_RATE_WINDOW_SECONDS = 60.0

router = APIRouter(prefix="/api/v1")


def make_api_limiter() -> SlidingWindowLimiter:
    """120 requests per minute per API token."""
    return SlidingWindowLimiter(API_RATE_LIMIT, API_RATE_WINDOW_SECONDS)


async def api_user(request: Request) -> AppUser:
    """The user behind a valid Bearer token; 401 otherwise, 429 over the limit."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    unauthorised = HTTPException(
        status_code=401,
        detail="A valid API token is required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthorised
    async with session_factory(request)() as session, session.begin():
        found: tuple[AppUser, ApiToken] | None = await user_for_api_token(
            session, token.strip(), clock_of(request)()
        )
    if found is None:
        raise unauthorised
    user, api_token = found
    limiter: SlidingWindowLimiter = request.app.state.api_limiter
    retry_after = limiter.check(str(api_token.id))
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
    return user


CurrentUser = Annotated[AppUser, Depends(api_user)]


@router.get("/whoami")
async def whoami(user: CurrentUser) -> dict[str, str]:
    """The account behind the token. It also proves token authentication works."""
    return {"username": user.username}


def http_error(error: EvidenceError) -> HTTPException:
    """The HTTP answer for an evidence error. The message is already readable."""
    if isinstance(error, ClientNotFoundError | ItemNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, DuplicateEvidenceError):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, EvidenceTooLargeError):
        return HTTPException(status_code=413, detail=str(error))
    if isinstance(error, EvidenceStorageError):
        return HTTPException(status_code=500, detail="The evidence store failed.")
    return HTTPException(status_code=422, detail=str(error))


class ClientCreate(BaseModel):
    name: str


@router.post("/clients", status_code=201)
async def post_client(
    request: Request, body: ClientCreate, user: CurrentUser
) -> dict[str, object]:
    """Create a client. It gets its own random pseudonym key."""
    try:
        async with session_factory(request)() as session, session.begin():
            client = await create_client(
                session, cipher_of(request), body.name, actor_user_id=user.id
            )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return {"id": client.id, "name": client.name}


def _text(form: FormData, name: str) -> str | None:
    value = form.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"The field {name} must be text.")
    return value.strip() or None


def _moment(form: FormData, name: str) -> datetime | None:
    value = _text(form, name)
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"The field {name} must be a date and time such as "
            "2026-10-01T09:00:00Z.",
        ) from None


def _required_moment(form: FormData, name: str) -> datetime:
    value = _moment(form, name)
    if value is None:
        raise HTTPException(status_code=422, detail=f"The field {name} is required.")
    return value


def _day(form: FormData, name: str) -> date | None:
    value = _text(form, name)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"The field {name} must be a date such as 2026-10-01.",
        ) from None


def _assurance(form: FormData, *, required: bool) -> Assurance:
    value = _text(form, "assurance")
    if value is None:
        if required:
            raise HTTPException(
                status_code=422, detail="The field assurance is required."
            )
        return Assurance.AUTOMATIC_EXPORT
    try:
        return Assurance(value)
    except ValueError:
        allowed = ", ".join(level.value for level in Assurance)
        raise HTTPException(
            status_code=422, detail=f"The assurance must be one of: {allowed}."
        ) from None


async def _file_bytes(form: FormData, limit: int) -> bytes | None:
    upload = form.get("file")
    if upload is None:
        return None
    if not isinstance(upload, UploadFile):
        raise HTTPException(status_code=422, detail="The field file must be a file.")
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"The file is larger than the limit of {limit / 1_048_576:g} MB.",
        )
    return data


async def read_evidence_form(
    request: Request, user: AppUser, *, revision: bool
) -> NewEvidence:
    """Read the multipart form of an upload. The file name is never kept."""
    limit: int = request.app.state.settings.import_max_bytes
    form = await request.form(max_files=1, max_fields=10)
    try:
        source_code = _text(form, "source_code")
        if source_code is None and not revision:
            raise HTTPException(
                status_code=422, detail="The field source_code is required."
            )
        return NewEvidence(
            source_code=source_code or "unchanged",
            assurance=_assurance(form, required=revision),
            captured_at=_required_moment(form, "captured_at"),
            data=await _file_bytes(form, limit),
            reviewer=_text(form, "reviewer"),
            reviewed_on=_day(form, "reviewed_on"),
            note=_text(form, "note"),
            expires_at=_moment(form, "expires_at"),
            uploader_id=user.id,
        )
    finally:
        await form.close()


def stored_json(stored: StoredEvidence) -> dict[str, object]:
    return {
        "item_id": stored.item_id,
        "revision": stored.revision_number,
        "sha256": stored.sha256,
        "size_bytes": stored.size_bytes,
        "source_code": stored.source_code,
        "assurance": stored.assurance.value,
        "captured_at": stored.captured_at.isoformat(),
        "expires_at": stored.expires_at.isoformat(),
        "raw_retained": stored.raw_retained,
        "facts": stored.facts,
    }


@router.post("/clients/{client_id}/evidence", status_code=201)
async def post_evidence(
    request: Request, client_id: int, user: CurrentUser
) -> dict[str, object]:
    """Upload one evidence file (multipart: file, source_code, captured_at, ...)."""
    evidence = await read_evidence_form(request, user, revision=False)
    try:
        async with session_factory(request)() as session, session.begin():
            stored = await add_evidence(
                session,
                evidence_context(request),
                client_id,
                evidence,
                clock_of(request)(),
            )
    except EvidenceError as error:
        raise http_error(error) from None
    return stored_json(stored)


@router.post("/clients/{client_id}/evidence/{item_id}/revisions", status_code=201)
async def post_revision(
    request: Request, client_id: int, item_id: int, user: CurrentUser
) -> dict[str, object]:
    """Add a revision to a manual evidence item (same form as an upload)."""
    evidence = await read_evidence_form(request, user, revision=True)
    try:
        async with session_factory(request)() as session, session.begin():
            stored = await add_revision(
                session,
                evidence_context(request),
                client_id,
                item_id,
                evidence,
                clock_of(request)(),
            )
    except EvidenceError as error:
        raise http_error(error) from None
    return stored_json(stored)


@router.get("/clients/{client_id}/evidence")
async def get_evidence(
    request: Request, client_id: int, user: CurrentUser
) -> dict[str, object]:
    """The client's evidence items with their freshness today."""
    try:
        async with session_factory(request)() as session:
            views = await list_evidence(session, client_id, clock_of(request)())
    except EvidenceError as error:
        raise http_error(error) from None
    return {
        "items": [
            {
                "item_id": view.item_id,
                "source_code": view.source_code,
                "assurance": view.assurance.value,
                "assurance_label": view.assurance.label,
                "captured_at": view.captured_at.isoformat(),
                "expires_at": view.expires_at.isoformat() if view.expires_at else None,
                "freshness": view.freshness.value,
                "revisions": view.revisions,
                "files_kept": view.files_kept,
                "sha256": view.sha256,
                "size_bytes": view.size_bytes,
            }
            for view in views
        ]
    }


@router.get("/clients/{client_id}/evidence/chain")
async def get_chain(
    request: Request, client_id: int, user: CurrentUser
) -> dict[str, object]:
    """Verify the hash chain of one client."""
    async with session_factory(request)() as session:
        if await session.get(Client, client_id) is None:
            raise http_error(ClientNotFoundError("There is no client with this id."))
        result = await verify_chain(session, client_id)
    return {
        "client_id": result.client_id,
        "ok": result.ok,
        "records": result.records,
        "head_hash": result.head_hash,
        "failed_record_id": result.failed_record_id,
        "reason": result.reason,
    }


@router.delete("/clients/{client_id}")
async def remove_client(
    request: Request, client_id: int, user: CurrentUser, confirm: str = ""
) -> dict[str, object]:
    """Delete a client and everything of it. `confirm` must be the client name."""
    try:
        report = await delete_client(
            session_factory(request),
            files_of(request),
            client_id,
            confirm_name=confirm,
            actor_user_id=user.id,
            now=clock_of(request)(),
        )
    except EvidenceError as error:
        raise http_error(error) from None
    return {
        "client_id": report.client_id,
        "items": report.items,
        "revisions": report.revisions,
        "facts": report.facts,
        "packs": report.packs,
        "files": report.files,
    }
