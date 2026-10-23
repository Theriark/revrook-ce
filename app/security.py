"""Passwords, API tokens, signed session cookies, CSRF tokens and response headers."""

import functools
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from itsdangerous import BadData, URLSafeTimedSerializer
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SESSION_COOKIE = "revrook_session"
SESSION_MAX_AGE = 12 * 60 * 60
API_TOKEN_PREFIX = "rvk_"
API_TOKEN_PREFIX_SHOWN = 12

# Argon2id with the library defaults (RFC 9106 low-memory profile).
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


@functools.cache
def dummy_password_hash() -> str:
    """A hash nobody knows the password of; unknown users still cost one verify."""
    return hash_password(secrets.token_urlsafe(24))


@dataclass(frozen=True)
class NewApiToken:
    """A freshly generated API token. Show `token` once; store only the hash."""

    token: str
    prefix: str
    token_hash: str


def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_api_token() -> NewApiToken:
    token = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return NewApiToken(
        token=token,
        prefix=token[:API_TOKEN_PREFIX_SHOWN],
        token_hash=hash_api_token(token),
    )


@dataclass(frozen=True)
class SessionData:
    """Content of the signed session cookie: the CSRF token and the user, if any."""

    csrf: str
    user_id: int | None = None


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(expected: str, supplied: str) -> bool:
    return hmac.compare_digest(expected.encode("utf-8"), supplied.encode("utf-8"))


class SessionCodec:
    """Signs and verifies the session cookie with SECRET_KEY (not encrypted)."""

    def __init__(self, secret_key: str) -> None:
        self._serializer = URLSafeTimedSerializer(secret_key, salt="revrook.session.v1")

    def encode(self, data: SessionData) -> str:
        return self._serializer.dumps({"c": data.csrf, "u": data.user_id})

    def decode(self, value: str, max_age: int = SESSION_MAX_AGE) -> SessionData | None:
        """The session, or None when the cookie is forged, damaged or too old."""
        try:
            payload = self._serializer.loads(value, max_age=max_age)
        except BadData:
            return None
        if not isinstance(payload, dict):
            return None
        csrf = payload.get("c")
        user_id = payload.get("u")
        if not isinstance(csrf, str) or not csrf:
            return None
        if user_id is not None and (
            not isinstance(user_id, int) or isinstance(user_id, bool)
        ):
            return None
        return SessionData(csrf=csrf, user_id=user_id)


CONTENT_SECURITY_POLICY = (
    "default-src 'self'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'; object-src 'none'"
)
HSTS_VALUE = "max-age=31536000; includeSubDomains"


NO_TRANSFORM = "no-transform"


def with_no_transform(cache_control: str | None) -> str:
    """A Cache-Control value that also carries `no-transform`, once.

    `no-transform` tells a proxy or CDN in front of revrook not to change the body.
    A report is shown and hashed as it was written; an edge that rewrites its
    e-mail addresses (Cloudflare Email Address Obfuscation) changes both the text and
    the bytes behind the recorded SHA-256.
    """
    if not cache_control:
        return NO_TRANSFORM
    tokens = [token.strip().lower() for token in cache_control.split(",")]
    if NO_TRANSFORM in tokens:
        return cache_control
    return f"{cache_control}, {NO_TRANSFORM}"


class SecurityHeadersMiddleware:
    """Adds the fixed security headers to every HTTP response.

    An HTML response also gets `no-transform` in its Cache-Control (see
    `with_no_transform`), so an edge does not rewrite the page.
    """

    def __init__(self, app: ASGIApp, hsts: bool = False) -> None:
        self.app = app
        self.headers = {
            "Content-Security-Policy": CONTENT_SECURITY_POLICY,
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        }
        if hsts:
            self.headers["Strict-Transport-Security"] = HSTS_VALUE

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self.headers.items():
                    if name == "Content-Security-Policy" and name in headers:
                        # A route may set a policy of its own (the report preview
                        # needs inline styles and forbids everything else).
                        continue
                    headers[name] = value
                if headers.get("content-type", "").lower().startswith("text/html"):
                    headers["Cache-Control"] = with_no_transform(
                        headers.get("cache-control")
                    )
            await send(message)

        await self.app(scope, receive, send_with_headers)
