"""The Evidence Explorer preview (Development only): one client's evidence sources
and the controls they feed, drawn as a scene and listed as tables.

The page reads a client exactly as its checklist does (`load_live`, `view_of`) and as
its evidence page does (`list_evidence`, `source_rows`), then hands both to the view
model of `app.ui.explorer_view`. The same object is rendered as the tables of the page
and served as JSON at `/experiments/evidence-explorer/data` for the scene script. Both
routes are read-only and need a signed-in user; nothing is stored. The scene itself is
optional: without script, without WebGL 2 or after a lost graphics context the tables
are the page.
"""

import hashlib
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evidence.errors import EvidenceError
from app.evidence.service import list_evidence
from app.limits import MAX_ID
from app.models import AppUser, Client
from app.posture import load_live, view_of
from app.reports.view import ReportContext, ReportError
from app.ui.brand import STATIC_DIR
from app.ui.clients import needed_sources
from app.ui.common import FormError, guarded, last_quarter, library_of, page
from app.ui.explorer_view import (
    ExplorerView,
    build_explorer,
    explorer_json,
    source_names,
    verdict_text,
)
from app.ui.viewmodels import source_rows
from app.web import clock_of, session_factory

router = APIRouter()
# The JSON of the scene has its own router: it is not a page (no title, no shell),
# so the tests that walk every page of `router` do not walk it.
data_router = APIRouter()
PATH = "/experiments/evidence-explorer"
DATA_PATH = PATH + "/data"
TITLE = "Evidence Explorer"
NAV = "explorer"
TEMPLATE = "evidence_explorer.html"
# The stylesheet and the scene script of the preview, under app/static. They are not
# in the shell (app/ui/brand.py, ASSET_FILES): the page links them itself with their
# own digest as the `v` query, for the same reason the shell does.
EXPLORER_ASSETS = ("css/evidence-explorer.css", "js/evidence-explorer.js")
NO_CLIENTS = "There are no clients yet."
NOT_A_NUMBER = "The client id must be a whole number."
NO_SUCH_CLIENT = "There is no such client."


def explorer_version(static_dir: Any = STATIC_DIR) -> str:
    """A 12-character digest of EXPLORER_ASSETS, the `v` query of their links."""
    digest = hashlib.sha256()
    for name in EXPLORER_ASSETS:
        path = static_dir / name
        digest.update(name.encode("utf-8"))
        digest.update(path.read_bytes() if path.is_file() else b"")
    return digest.hexdigest()[:12]


# Read once at start-up: the files of the image do not change while it runs.
EXPLORER_VERSION = explorer_version()


async def active_clients(session: AsyncSession) -> list[tuple[int, str]]:
    """Every client that is not archived, by name."""
    found = await session.execute(
        select(Client.id, Client.name)
        .where(Client.archived_at.is_(None))
        .order_by(Client.name, Client.id)
    )
    return [(client_id, name) for client_id, name in found.all()]


def chosen_client(request: Request, clients: list[tuple[int, str]]) -> int:
    """The client of `?client_id=`, or the first by name when none is asked for.

    A value that is not a whole number is refused with 422; a number that is not an
    active client with 404. `clients` is not empty here.
    """
    value = request.query_params.get("client_id", "").strip()
    if not value:
        return clients[0][0]
    if not value.isdigit() or int(value) < 1 or int(value) > MAX_ID:
        raise FormError(NOT_A_NUMBER)
    chosen = int(value)
    if not any(client_id == chosen for client_id, _ in clients):
        raise FormError(NO_SUCH_CLIENT, 404)
    return chosen


async def load_explorer(
    request: Request, user: AppUser, client_id: int
) -> ExplorerView:
    """The view of one client today: its checks and its evidence, read once."""
    library = library_of(request)
    now = clock_of(request)()
    async with session_factory(request)() as session:
        live = await load_live(session, library, client_id, now)
        evidence = await list_evidence(session, client_id, now)
    start, end = last_quarter(now.date())
    context = ReportContext(
        msp_name="",
        client_name=live.name,
        period_start=start,
        period_end=end,
        prepared_by=user.username,
        generated_on=now.date(),
    )
    rows = view_of(live, library, context).rows
    sources = source_rows(evidence, needed_sources(request))
    return build_explorer(library, client_id, live.name, now, rows, sources)


def page_context(
    clients: list[tuple[int, str]], view: ExplorerView | None
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "title": TITLE,
        "nav": NAV,
        "clients": clients,
        "view": view,
        "explorer_version": EXPLORER_VERSION,
        "data_url": None,
        "verdict": "",
        "names": {},
    }
    if view is not None:
        context["data_url"] = f"{DATA_PATH}?client_id={view.client_id}"
        context["verdict"] = verdict_text(view)
        context["names"] = source_names(view)
    return context


@router.get(PATH)
async def explorer_page(request: Request) -> Response:
    async def handle(user: AppUser) -> Response:
        async with session_factory(request)() as session:
            clients = await active_clients(session)
        if not clients:
            return page(request, TEMPLATE, user, page_context(clients, None))
        client_id = chosen_client(request, clients)
        view = await load_explorer(request, user, client_id)
        return page(request, TEMPLATE, user, page_context(clients, view))

    return await guarded(request, handle)


def refused(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(
        {"detail": detail},
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


@data_router.get(DATA_PATH)
async def explorer_data(request: Request) -> Response:
    """The view model as JSON for the scene; the same facts as the page's tables.

    A refusal is JSON too (the scene script reads `detail`), where a page would be
    the problem page. Someone who is not signed in is still sent to the sign-in
    page, as for every page: the script treats an answer that is not JSON as a
    session that ended.
    """

    async def handle(user: AppUser) -> Response:
        async with session_factory(request)() as session:
            clients = await active_clients(session)
        if not clients:
            return refused(404, NO_CLIENTS)
        try:
            client_id = chosen_client(request, clients)
            view = await load_explorer(request, user, client_id)
        except FormError as error:
            return refused(error.status_code, str(error))
        except (EvidenceError, ReportError) as error:
            return refused(422, str(error))
        return JSONResponse(explorer_json(view), headers={"Cache-Control": "no-store"})

    return await guarded(request, handle)
