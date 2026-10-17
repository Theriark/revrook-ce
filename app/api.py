"""JSON API, authenticated with a Bearer API token (rate limited per token)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import user_for_api_token
from app.models import ApiToken, AppUser
from app.ratelimit import SlidingWindowLimiter
from app.web import clock_of, session_factory

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


@router.get("/whoami")
async def whoami(user: Annotated[AppUser, Depends(api_user)]) -> dict[str, str]:
    """The account behind the token. It also proves token authentication works."""
    return {"username": user.username}
