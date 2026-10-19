"""The evidence integrity page: check the hash chains from the browser."""

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.auth import get_user
from app.evidence.chain import ChainResult, verify_all
from app.models import AppUser, Client
from app.ui.auth import redirect, render
from app.web import current_session, session_factory

router = APIRouter()
INTEGRITY_TITLE = "Evidence integrity"


@dataclass(frozen=True)
class ChainRow:
    """One line of the result table."""

    client_label: str
    ok: bool
    records: int
    head: str
    problem: str


async def _signed_in_user(request: Request) -> AppUser | None:
    session = current_session(request)
    if session.user_id is None:
        return None
    async with session_factory(request)() as db:
        return await get_user(db, session.user_id)


def _row(result: ChainResult, names: dict[int, str]) -> ChainRow:
    label = names.get(result.client_id, f"Deleted client {result.client_id}")
    if result.ok:
        problem = ""
    else:
        problem = f"{result.reason} (record {result.failed_record_id})"
    return ChainRow(label, result.ok, result.records, result.head_hash[:16], problem)


def _context(user: AppUser, rows: list[ChainRow] | None) -> dict[str, Any]:
    failed = 0 if rows is None else sum(1 for row in rows if not row.ok)
    return {
        "title": INTEGRITY_TITLE,
        "nav": "integrity",
        "user": user,
        "rows": rows,
        "failed": failed,
    }


@router.get("/evidence/integrity")
async def integrity_form(request: Request) -> Response:
    user = await _signed_in_user(request)
    if user is None:
        return redirect("/login")
    return render(
        request,
        "evidence_integrity.html",
        _context(user, None),
        current_session(request),
    )


@router.post("/evidence/integrity")
async def integrity_check(request: Request) -> Response:
    """Verify every client's chain. Only reads; the CSRF check still applies."""
    user = await _signed_in_user(request)
    if user is None:
        return redirect("/login")
    async with session_factory(request)() as db:
        results = await verify_all(db)
        named = await db.execute(select(Client.id, Client.name))
        names = {client_id: name for client_id, name in named.all()}
    rows = [_row(result, names) for result in results]
    return render(
        request,
        "evidence_integrity.html",
        _context(user, rows),
        current_session(request),
    )
