"""The chart fragments the chart script swaps in when a range is chosen.

A fragment is the body of one chart card without the shell: the Home trend for a
range of days (`/charts/trend?days=30`) and the score history of one client for a
span (`/clients/{id}/charts/history?span=365`). `app/static/js/charts.js` asks for
it through the vendored htmx when a range button is pressed, so the page keeps its
place; without script the same form posts its range to the page that holds the
chart (`/?days=30`, `/clients/{id}/reports?span=365`), which draws the same chart.

A fragment is not a page a person reads on its own: asked for without the htmx
header, the address redirects to the page that holds the chart with the same range.
Signed out, the answer is the one every page gives (`to_login`: the sign-in page,
or the HX-Redirect to it); a range that is not known is refused with a 422 like a
filter of the checklist. Reads only: no CSRF token is involved.
"""

from typing import Any

from fastapi import APIRouter, Request, Response

from app.evidence.errors import ClientNotFoundError
from app.models import AppUser, Client
from app.ui.auth import redirect, templates
from app.ui.charts import read_days, read_range
from app.ui.common import RowId, guarded, is_htmx
from app.ui.home import trend_context
from app.ui.reports import history_of
from app.web import clock_of, session_factory

router = APIRouter()
TREND_FRAGMENT = "_trend_chart.html"
HISTORY_FRAGMENT = "_history_chart.html"


def fragment(request: Request, name: str, context: dict[str, Any]) -> Response:
    """A template without the shell, never cached."""
    return templates.TemplateResponse(
        request, name, context, headers={"Cache-Control": "no-store"}
    )


@router.get("/charts/trend")
async def trend_fragment(request: Request, days: str = "") -> Response:
    async def handle(user: AppUser) -> Response:
        chosen = read_days(days)
        if not is_htmx(request):
            return redirect(f"/?days={chosen}")
        context = await trend_context(request, clock_of(request)(), chosen)
        return fragment(request, TREND_FRAGMENT, context)

    return await guarded(request, handle)


@router.get("/clients/{client_id}/charts/history")
async def history_fragment(
    request: Request, client_id: RowId, span: str = ""
) -> Response:
    async def handle(user: AppUser) -> Response:
        chosen = read_range(span)
        if not is_htmx(request):
            return redirect(f"/clients/{client_id}/reports?span={chosen}")
        async with session_factory(request)() as session:
            client = await session.get(Client, client_id)
            if client is None:
                raise ClientNotFoundError("There is no client with this id.")
            context = await history_of(
                session, client_id, client.name, clock_of(request)(), chosen
            )
        context.update(client_id=client_id, client_name=client.name)
        return fragment(request, HISTORY_FRAGMENT, context)

    return await guarded(request, handle)
