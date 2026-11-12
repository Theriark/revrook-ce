"""The Account page of the person signed in: name, picture, password and theme.

Reached from the account menu of the top bar (_topbar.html). Each form posts on its
own, so a refused password leaves the name as it was, and comes back to the page
with a short message. Every change is written to the audit trail without its value.
"""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request, Response
from sqlalchemy import select, update
from starlette.datastructures import UploadFile

from app.audit import add_audit_event
from app.auth import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from app.models import AppUser
from app.security import hash_password, verify_password
from app.theme import THEMES
from app.ui.auth import redirect
from app.ui.common import guarded, page, sentence
from app.web import session_factory, set_theme_cookie

router = APIRouter()

MAX_NAME = 80
MAX_AVATAR_BYTES = 512 * 1024
# The picture is recognised by its first bytes, never by the name or the type the
# browser sends: PNG, JPEG and WebP only, so nothing else is ever served back.
AVATAR_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)
DONE = {
    "name": "Your name is saved.",
    "picture": "Your picture is saved.",
    "picture-removed": "Your picture is removed.",
    "password": "Your password is changed.",
    "theme": "Your theme is saved.",
}


def display_name_of(user: AppUser) -> str:
    """The name shown for a person: the one they chose, else the login name."""
    return (user.display_name or "").strip() or user.username


def initial_of(user: AppUser) -> str:
    return display_name_of(user)[:1].upper()


def avatar_type_of(data: bytes) -> str | None:
    """The media type of a picture by its first bytes, or None when it is no picture."""
    for signature, media_type in AVATAR_SIGNATURES:
        if data.startswith(signature):
            return media_type
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def name_problems(name: str) -> list[str]:
    if len(name) > MAX_NAME:
        return [f"The name must be at most {MAX_NAME} characters."]
    if any(ord(char) < 32 for char in name):
        return ["The name must not contain control characters."]
    return []


def password_problems(user: AppUser, new: str, confirm: str) -> list[str]:
    if len(new) < MIN_PASSWORD_LENGTH:
        return [f"The new password must be at least {MIN_PASSWORD_LENGTH} characters."]
    if len(new) > MAX_PASSWORD_LENGTH:
        return [f"The new password must be at most {MAX_PASSWORD_LENGTH} characters."]
    if new.lower() == user.username:
        return ["The new password must not be the same as the username."]
    if new != confirm:
        return ["The two new passwords do not match."]
    return []


def account_page(
    request: Request,
    user: AppUser,
    *,
    done: str = "",
    errors: dict[str, list[str]] | None = None,
    status_code: int = 200,
) -> Response:
    context: dict[str, Any] = {
        "title": "Account",
        "nav": "account",
        "done_message": DONE.get(done, ""),
        "errors": errors or {},
        "min_password": MIN_PASSWORD_LENGTH,
        "max_avatar_kb": MAX_AVATAR_BYTES // 1024,
    }
    return page(request, "account.html", user, context, status_code)


@router.get("/account")
async def account(request: Request, done: str = "") -> Response:
    async def handle(user: AppUser) -> Response:
        return account_page(request, user, done=done)

    return await guarded(request, handle)


@router.post("/account/name")
async def account_name(
    request: Request, display_name: Annotated[str, Form()] = ""
) -> Response:
    async def handle(user: AppUser) -> Response:
        name = " ".join(display_name.split())
        problems = name_problems(name)
        if problems:
            return account_page(
                request, user, errors={"name": problems}, status_code=422
            )
        async with session_factory(request)() as session, session.begin():
            await session.execute(
                update(AppUser)
                .where(AppUser.id == user.id)
                .values(display_name=name or None)
            )
            add_audit_event(
                session,
                "user.profile_changed",
                actor_user_id=user.id,
                target_type="app_user",
                target_id=user.id,
                detail={"field": "display_name"},
            )
        return redirect("/account?done=name")

    return await guarded(request, handle)


@router.post("/account/picture")
async def account_picture(request: Request) -> Response:
    async def handle(user: AppUser) -> Response:
        form = await request.form(max_files=1, max_fields=4)
        upload = form.get("picture")
        if not isinstance(upload, UploadFile):
            problems = ["Choose a picture first."]
            return account_page(
                request, user, errors={"picture": problems}, status_code=422
            )
        data = await upload.read(MAX_AVATAR_BYTES + 1)
        media_type = avatar_type_of(data)
        problems = []
        if len(data) > MAX_AVATAR_BYTES:
            problems = [f"The picture must be at most {MAX_AVATAR_BYTES // 1024} KB."]
        elif media_type is None:
            problems = ["The picture must be a PNG, JPEG or WebP image."]
        if problems:
            return account_page(
                request, user, errors={"picture": problems}, status_code=422
            )
        async with session_factory(request)() as session, session.begin():
            await session.execute(
                update(AppUser)
                .where(AppUser.id == user.id)
                .values(
                    avatar=data,
                    avatar_type=media_type,
                    avatar_version=AppUser.avatar_version + 1,
                )
            )
            add_audit_event(
                session,
                "user.profile_changed",
                actor_user_id=user.id,
                target_type="app_user",
                target_id=user.id,
                detail={"field": "avatar", "bytes": len(data)},
            )
        return redirect("/account?done=picture")

    return await guarded(request, handle)


@router.post("/account/picture/remove")
async def account_picture_remove(request: Request) -> Response:
    async def handle(user: AppUser) -> Response:
        async with session_factory(request)() as session, session.begin():
            await session.execute(
                update(AppUser)
                .where(AppUser.id == user.id)
                .values(
                    avatar=None,
                    avatar_type=None,
                    avatar_version=AppUser.avatar_version + 1,
                )
            )
            add_audit_event(
                session,
                "user.profile_changed",
                actor_user_id=user.id,
                target_type="app_user",
                target_id=user.id,
                detail={"field": "avatar", "removed": True},
            )
        return redirect("/account?done=picture-removed")

    return await guarded(request, handle)


@router.get("/account/picture/{user_id}")
async def account_picture_file(request: Request, user_id: int) -> Response:
    """A picture by its user id, for any signed-in person."""

    async def handle(user: AppUser) -> Response:
        async with session_factory(request)() as session:
            row = (
                await session.execute(
                    select(AppUser.avatar, AppUser.avatar_type).where(
                        AppUser.id == user_id
                    )
                )
            ).one_or_none()
        if row is None or row.avatar is None or row.avatar_type is None:
            return Response(status_code=404)
        return Response(
            content=row.avatar,
            media_type=row.avatar_type,
            # The address carries the version, so the browser may keep it a long time
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )

    return await guarded(request, handle)


@router.post("/account/password")
async def account_password(
    request: Request,
    current_password: Annotated[str, Form()] = "",
    new_password: Annotated[str, Form()] = "",
    confirm_password: Annotated[str, Form()] = "",
) -> Response:
    async def handle(user: AppUser) -> Response:
        right = len(
            current_password
        ) <= MAX_PASSWORD_LENGTH and await asyncio.to_thread(
            verify_password, user.password_hash, current_password
        )
        problems = (
            password_problems(user, new_password, confirm_password)
            if right
            else ["The current password is not right."]
        )
        if problems:
            return account_page(
                request, user, errors={"password": problems}, status_code=422
            )
        new_hash = await asyncio.to_thread(hash_password, new_password)
        async with session_factory(request)() as session, session.begin():
            await session.execute(
                update(AppUser)
                .where(AppUser.id == user.id)
                .values(password_hash=new_hash)
            )
            add_audit_event(
                session,
                "user.password_changed",
                actor_user_id=user.id,
                target_type="app_user",
                target_id=user.id,
            )
        return redirect("/account?done=password")

    return await guarded(request, handle)


@router.post("/account/theme")
async def account_theme(
    request: Request, theme: Annotated[str, Form()] = ""
) -> Response:
    async def handle(user: AppUser) -> Response:
        if theme not in THEMES:
            message = sentence("the theme must be light, dark or system")
            return account_page(
                request, user, errors={"theme": [message]}, status_code=422
            )
        async with session_factory(request)() as session, session.begin():
            await session.execute(
                update(AppUser).where(AppUser.id == user.id).values(theme=theme)
            )
        response = redirect("/account?done=theme")
        set_theme_cookie(response, request, theme)
        return response

    return await guarded(request, handle)
