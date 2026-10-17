"""The upload size limit: refused before the body is read."""

from typing import Any

import pytest
from starlette.types import Message, Receive, Scope, Send

from app.limits import FORM_OVERHEAD_BYTES, UploadSizeLimitMiddleware

UPLOAD_PATH = "/api/v1/clients/3/evidence"
REVISION_PATH = "/api/v1/clients/3/evidence/9/revisions"
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


@pytest.mark.parametrize("path", [UPLOAD_PATH, REVISION_PATH])
async def test_an_upload_within_the_limit_passes_through(path: str) -> None:
    size = str(LIMIT + FORM_OVERHEAD_BYTES).encode()
    inner, sent = await run(path, [(b"content-length", size)])
    assert inner.called
    assert status_of(sent) == 204


@pytest.mark.parametrize("path", [UPLOAD_PATH, REVISION_PATH])
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
    ],
)
async def test_other_requests_are_not_checked(path: str, method: str) -> None:
    inner, sent = await run(path, [], method=method)
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
