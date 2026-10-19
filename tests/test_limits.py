"""The upload size limit: refused before the body is read."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
import uvicorn
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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


@pytest.mark.parametrize("length", [b"0", b"5", str(MAX_BODY_BYTES).encode()])
@pytest.mark.parametrize("path", [UPLOAD_PATH, "/api/v1/clients", "/login"])
async def test_a_transfer_encoding_is_refused_with_411_whatever_the_length_says(
    path: str, length: bytes
) -> None:
    headers = [(b"content-length", length), (b"transfer-encoding", b"chunked")]
    inner, sent = await run(path, headers)
    assert not inner.called
    assert status_of(sent) == 411


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
async def test_a_transfer_encoding_is_refused_on_every_method_with_a_body(
    method: str,
) -> None:
    headers = [(b"content-length", b"0"), (b"transfer-encoding", b"chunked")]
    inner, sent = await run("/api/v1/clients", headers, method=method)
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


# --- over a real socket: the HTTP parser decides how a body is framed ---


class BodySpy:
    """A stand-in application that reads the whole body and counts what it got."""

    def __init__(self) -> None:
        self.called = False
        self.bytes_read = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.called = True
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                break
            self.bytes_read += len(message.get("body", b""))
            more = message.get("more_body", False)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})


@contextlib.asynccontextmanager
async def serving(app: ASGIApp) -> AsyncIterator[int]:
    """Serve the application with uvicorn and its h11 parser (the image has no
    httptools) on a free local port, and give the port."""
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=0,
        http="h11",
        ws="none",
        lifespan="off",
        log_level="warning",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(15):
            while not server.started:
                if task.done():
                    task.result()
                await asyncio.sleep(0.01)
        yield int(server.servers[0].sockets[0].getsockname()[1])
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 15)


async def exchange(port: int, head: str, body: bytes = b"") -> bytes:
    """Send one request on a new connection and give everything the server sends."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        request = f"{head}Host: test\r\nConnection: close\r\n\r\n"
        writer.write(request.encode("ascii") + body)
        await writer.drain()
        return await asyncio.wait_for(reader.read(), 15)
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()


CHUNKED_BODY = b"5\r\nhello\r\n0\r\n\r\n"


@pytest.mark.parametrize("length", ["0", "5", str(MAX_BODY_BYTES)])
@pytest.mark.parametrize("path", [UPLOAD_PATH, "/login"])
async def test_a_chunked_body_with_a_content_length_is_refused_over_a_socket(
    path: str, length: str
) -> None:
    # h11 frames this body by Transfer-Encoding and ignores Content-Length, and
    # uvicorn hands both headers on: the size check must not trust the length.
    spy = BodySpy()
    async with serving(UploadSizeLimitMiddleware(spy, max_file_bytes=LIMIT)) as port:
        head = (
            f"POST {path} HTTP/1.1\r\n"
            f"Content-Length: {length}\r\nTransfer-Encoding: chunked\r\n"
        )
        answer = await exchange(port, head, CHUNKED_BODY)
    assert answer.startswith(b"HTTP/1.1 411 "), answer[:80]
    assert not spy.called
    assert spy.bytes_read == 0


async def test_the_socket_harness_lets_a_request_with_a_small_size_through() -> None:
    # The refusals above mean something only if the same server passes a good request
    # and the application behind it can read a body.
    spy = BodySpy()
    async with serving(UploadSizeLimitMiddleware(spy, max_file_bytes=LIMIT)) as port:
        head = "POST /login HTTP/1.1\r\nContent-Length: 5\r\n"
        answer = await exchange(port, head, b"hello")
    assert answer.startswith(b"HTTP/1.1 204 "), answer[:80]
    assert spy.called and spy.bytes_read == 5


async def test_a_chunked_body_without_a_size_is_refused_over_a_socket() -> None:
    spy = BodySpy()
    async with serving(UploadSizeLimitMiddleware(spy, max_file_bytes=LIMIT)) as port:
        head = "POST /login HTTP/1.1\r\nTransfer-Encoding: chunked\r\n"
        answer = await exchange(port, head, CHUNKED_BODY)
    assert answer.startswith(b"HTTP/1.1 411 "), answer[:80]
    assert not spy.called and spy.bytes_read == 0
