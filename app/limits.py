"""Size caps for request bodies, applied before the body is read, and the id bounds.

Starlette would copy a whole upload to a temporary file before the application can
look at it, so a body is refused by its declared size first.

* An upload route (evidence files, the profile editor) takes a file of at most
  IMPORT_MAX_BYTES plus FORM_OVERHEAD_BYTES. It must declare its size (411).
* Every other POST, PUT, PATCH and DELETE takes at most MAX_BODY_BYTES (1 MiB), which
  is far more than a JSON body or a form of this application needs. Over it is 413.
  A body sent in chunks (any Transfer-Encoding, whatever Content-Length says) is 411;
  a request that sends no body passes.
"""

import re
from typing import Annotated

from fastapi import Path
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# The largest value of a database key (a signed 64-bit integer). Past it the
# database refuses the value, so a route that takes an id bounds it first.
MAX_ID = 9_223_372_036_854_775_807
RowId = Annotated[int, Path(ge=1, le=MAX_ID)]

UPLOAD_PATH = re.compile(
    r"^(/api/v1/clients/\d+/evidence(/\d+/revisions)?"
    r"|/imports/profile-editor/(preview|save|import))$"
)
UPLOAD_METHODS = frozenset({"POST", "PUT", "PATCH"})
BODY_METHODS = UPLOAD_METHODS | {"DELETE"}
# Room for the multipart boundaries and the small form fields around the file.
FORM_OVERHEAD_BYTES = 64 * 1024
# The most any request that is not an upload may send.
MAX_BODY_BYTES = 1024 * 1024


class UploadSizeLimitMiddleware:
    """Refuses a body that declares too many bytes, or does not declare its size.

    An upload may be as large as the import limit; any other body is capped at
    `max_body_bytes`. A client that sends an upload without Content-Length, or any
    request with a Transfer-Encoding header (a chunked body, with or without a
    Content-Length next to it), is refused with 411 for the same reason. A request
    that carries neither header has no body.
    """

    def __init__(
        self,
        app: ASGIApp,
        max_file_bytes: int,
        max_body_bytes: int = MAX_BODY_BYTES,
    ) -> None:
        self.app = app
        self.upload_limit = max_file_bytes + FORM_OVERHEAD_BYTES
        self.body_limit = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in BODY_METHODS:
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        upload = (
            scope["method"] in UPLOAD_METHODS
            and UPLOAD_PATH.match(scope["path"]) is not None
        )
        declared = headers.get(b"content-length")
        limit = self.upload_limit if upload else self.body_limit
        # A server frames a body by Transfer-Encoding before Content-Length (h11 does),
        # so a request that carries both can send any number of bytes whatever the
        # declared size says. Any Transfer-Encoding is refused for that reason.
        if b"transfer-encoding" in headers or (declared is None and upload):
            refusal = JSONResponse(
                {"detail": "The request must declare its size (Content-Length)."},
                status_code=411,
            )
        elif declared is None:
            await self.app(scope, receive, send)
            return
        elif not declared.isdigit():
            refusal = JSONResponse(
                {"detail": "The Content-Length header is not valid."}, status_code=400
            )
        elif int(declared) > limit:
            what = "upload" if upload else "request body"
            refusal = JSONResponse(
                {"detail": f"The {what} is larger than the limit."}, status_code=413
            )
        else:
            await self.app(scope, receive, send)
            return
        await refusal(scope, receive, send)
