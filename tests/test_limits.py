"""The upload size limit: refused before the body is read."""

from typing import Any

import pytest
from starlette.types import Message, Receive, Scope, Send

from app.limits import FORM_OVERHEAD_BYTES, MAX_BODY_BYTES, UploadSizeLimitMiddleware

UPLOAD_PATH = "/api/v1/clients/3/evidence"
REVISION_PATH = "/api/v1/clients/3/evidence/9/revisions"
EDITOR_PATHS = [
    "/imports/profile-editor/preview",
    "/imports/profile-editor/save",
    "/imports/profile-editor/import",
]
LIMIT = 1000


class Recorder:
    """A stand-in application that records whether it was called."""

    def __init__(self) -> None:
        self.called = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.called = True
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})


async def run(
    path: str, headers: list[tuple[bytes, bytes]], method: str = "POST"
) -> tuple[Recorder, list[Message]]:
    inner = Recorder()
    middleware = UploadSizeLimitMiddleware(inner, max_file_bytes=LIMIT)
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers,
    }
    await middleware(scope, receive, send)
    return inner, sent


def status_of(sent: list[Message]) -> int:
    return int(sent[0]["status"])


@pytest.mark.parametrize("path", [UPLOAD_PATH, REVISION_PATH, *EDITOR_PATHS])
async def test_an_upload_within_the_limit_passes_through(path: str) -> None:
    size = str(LIMIT + FORM_OVERHEAD_BYTES).encode()
    inner, sent = await run(path, [(b"content-length", size)])
    assert inner.called
    assert status_of(sent) == 204


@pytest.mark.parametrize("path", [UPLOAD_PATH, REVISION_PATH, *EDITOR_PATHS])
async def test_an_upload_over_the_limit_is_refused_with_413(path: str) -> None:
    size = str(LIMIT + FORM_OVERHEAD_BYTES + 1).encode()
    inner, sent = await run(path, [(b"content-length", size)])
    assert not inner.called
    assert status_of(sent) == 413


async def test_an_upload_without_a_declared_size_is_refused_with_411() -> None:
    inner, sent = await run(UPLOAD_PATH, [(b"transfer-encoding", b"chunked")])
    assert not inner.called
    assert status_of(sent) == 411


async def test_a_size_that_is_not_a_number_is_refused_with_400() -> None:
    inner, sent = await run(UPLOAD_PATH, [(b"content-length", b"12abc")])
    assert not inner.called
    assert status_of(sent) == 400


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/v1/clients", "POST"),
        ("/api/v1/clients/3/evidence", "GET"),
        ("/api/v1/clients/3/evidence/chain", "GET"),
        ("/api/v1/clients/x/evidence", "POST"),
        ("/login", "POST"),
        ("/imports/profile-editor", "GET"),
        ("/imports/profile-editor/other", "POST"),
    ],
)
async def test_other_requests_are_not_checked(path: str, method: str) -> None:
    inner, sent = await run(path, [], method=method)
    assert inner.called
    assert status_of(sent) == 204


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("path", ["/api/v1/clients", "/login", "/system/export"])
async def test_a_body_over_the_general_limit_is_refused_with_413(
    path: str, method: str
) -> None:
    size = str(MAX_BODY_BYTES + 1).encode()
    inner, sent = await run(path, [(b"content-length", size)], method=method)
    assert not inner.called
    assert status_of(sent) == 413


@pytest.mark.parametrize("method", ["POST", "DELETE"])
async def test_a_body_at_the_general_limit_passes_through(method: str) -> None:
    size = str(MAX_BODY_BYTES).encode()
    inner, sent = await run("/api/v1/clients", [(b"content-length", size)], method)
    assert inner.called
    assert status_of(sent) == 204


async def test_an_upload_route_keeps_its_own_larger_limit() -> None:
    inner = Recorder()
    middleware = UploadSizeLimitMiddleware(inner, 5 * MAX_BODY_BYTES)
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    size = str(2 * MAX_BODY_BYTES).encode()
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": UPLOAD_PATH,
        "headers": [(b"content-length", size)],
    }
    await middleware(scope, receive, send)
    assert inner.called
    assert status_of(sent) == 204


async def test_a_body_sent_in_chunks_is_refused_with_411_on_any_route() -> None:
    inner, sent = await run("/api/v1/clients", [(b"transfer-encoding", b"chunked")])
    assert not inner.called
    assert status_of(sent) == 411


async def test_a_size_that_is_not_a_number_is_refused_with_400_on_any_route() -> None:
    inner, sent = await run("/login", [(b"content-length", b"1e3")])
    assert not inner.called
    assert status_of(sent) == 400


async def test_a_get_is_never_checked_for_its_body() -> None:
    size = str(10 * MAX_BODY_BYTES).encode()
    inner, sent = await run("/clients", [(b"content-length", size)], method="GET")
    assert inner.called
    assert status_of(sent) == 204


async def test_websocket_scopes_pass_through() -> None:
    inner = Recorder()
    middleware = UploadSizeLimitMiddleware(inner, max_file_bytes=LIMIT)

    async def receive() -> Message:
        return {"type": "websocket.connect"}

    async def send(message: Message) -> None:
        return None

    await middleware({"type": "websocket", "path": UPLOAD_PATH}, receive, send)
    assert inner.called
