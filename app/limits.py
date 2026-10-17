"""A size cap for uploads, applied before the request body is read."""

import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

UPLOAD_PATH = re.compile(r"^/api/v1/clients/\d+/evidence(/\d+/revisions)?$")
UPLOAD_METHODS = frozenset({"POST", "PUT", "PATCH"})
# Room for the multipart boundaries and the small form fields around the file.
FORM_OVERHEAD_BYTES = 64 * 1024


class UploadSizeLimitMiddleware:
    """Refuses an upload that declares too many bytes, or does not declare its size.

    Starlette would otherwise copy the whole request body to a temporary file
    before the application can look at it. A client that sends no Content-Length
    (chunked transfer) is refused with 411 for the same reason.
    """

    def __init__(self, app: ASGIApp, max_file_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_file_bytes + FORM_OVERHEAD_BYTES

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in UPLOAD_METHODS
            or not UPLOAD_PATH.match(scope["path"])
        ):
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is None:
            refusal = JSONResponse(
                {"detail": "The upload must declare its size (Content-Length)."},
                status_code=411,
            )
        elif not declared.isdigit():
            refusal = JSONResponse(
                {"detail": "The Content-Length header is not valid."}, status_code=400
            )
        elif int(declared) > self.max_body_bytes:
            refusal = JSONResponse(
                {"detail": "The upload is larger than the limit."}, status_code=413
            )
        else:
            await self.app(scope, receive, send)
            return
        await refusal(scope, receive, send)
