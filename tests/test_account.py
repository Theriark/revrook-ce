"""The Account page (app/ui/account.py) and the account menu of the top bar: the
display name, the picture, the password and the theme of the person signed in."""

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.models import AppUser, AuditEvent
from app.ui.account import avatar_type_of
from helpers import PASSWORD, create_admin, csrf_from, login

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64


def test_a_picture_is_known_by_its_first_bytes() -> None:
    assert avatar_type_of(PNG) == "image/png"
    assert avatar_type_of(JPEG) == "image/jpeg"
    assert avatar_type_of(WEBP) == "image/webp"
    assert avatar_type_of(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None
    assert avatar_type_of(b"GIF89a" + b"\x00" * 16) is None


async def signed_in(browser: httpx.AsyncClient, engine: AsyncEngine) -> str:
    await create_admin(engine)
    assert (await login(browser)).status_code == 303
    page = await browser.get("/account")
    assert page.status_code == 200
    return csrf_from(page.text)


async def user_row(engine: AsyncEngine) -> AppUser:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        found = await session.execute(select(AppUser))
        return found.scalars().one()


async def test_the_top_bar_has_the_account_menu_and_the_theme_switch(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await signed_in(ui_browser, db_engine)
    home = (await ui_browser.get("/")).text
    assert '<details class="rv-account" id="account-menu">' in home
    assert 'href="/account"' in home and 'action="/logout"' in home
    assert 'class="rv-theme-toggle"' in home
    # The account and the theme left the rail, and no page carries the footer
    assert 'class="rv-user"' not in home and "rv-footer" not in home


async def test_the_display_name_is_saved_and_shown(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    csrf = await signed_in(ui_browser, db_engine)
    saved = await ui_browser.post(
        "/account/name", data={"csrf_token": csrf, "display_name": "  Sam   Synthetic "}
    )
    assert (
        saved.status_code == 303 and saved.headers["location"] == "/account?done=name"
    )
    assert (await user_row(db_engine)).display_name == "Sam Synthetic"
    home = (await ui_browser.get("/")).text
    assert '<span class="rv-account-name">Sam Synthetic</span>' in home
    too_long = await ui_browser.post(
        "/account/name", data={"csrf_token": csrf, "display_name": "x" * 81}
    )
    assert too_long.status_code == 422 and "at most 80 characters" in too_long.text
    cleared = await ui_browser.post(
        "/account/name", data={"csrf_token": csrf, "display_name": ""}
    )
    assert cleared.status_code == 303
    assert (await user_row(db_engine)).display_name is None


async def test_a_picture_is_stored_served_and_removed(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    csrf = await signed_in(ui_browser, db_engine)
    refused = await ui_browser.post(
        "/account/picture",
        data={"csrf_token": csrf},
        files={"picture": ("a.svg", b"<svg/>", "image/png")},
    )
    assert refused.status_code == 422 and "PNG, JPEG or WebP" in refused.text
    stored = await ui_browser.post(
        "/account/picture",
        data={"csrf_token": csrf},
        files={"picture": ("me.png", PNG, "image/png")},
    )
    assert stored.status_code == 303
    user = await user_row(db_engine)
    assert user.avatar_type == "image/png" and user.avatar_version == 1
    served = await ui_browser.get(f"/account/picture/{user.id}")
    assert served.status_code == 200 and served.content == PNG
    assert served.headers["content-type"] == "image/png"
    home = (await ui_browser.get("/")).text
    assert f'src="/account/picture/{user.id}?v=1"' in home
    removed = await ui_browser.post(
        "/account/picture/remove", data={"csrf_token": csrf}
    )
    assert removed.status_code == 303
    assert (await ui_browser.get(f"/account/picture/{user.id}")).status_code == 404


async def test_the_password_changes_only_with_the_current_one(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    csrf = await signed_in(ui_browser, db_engine)
    new = "a new synthetic passphrase"
    wrong = await ui_browser.post(
        "/account/password",
        data={
            "csrf_token": csrf,
            "current_password": "not the password",
            "new_password": new,
            "confirm_password": new,
        },
    )
    assert wrong.status_code == 422 and "current password is not right" in wrong.text
    mismatch = await ui_browser.post(
        "/account/password",
        data={
            "csrf_token": csrf,
            "current_password": PASSWORD,
            "new_password": new,
            "confirm_password": new + "!",
        },
    )
    assert mismatch.status_code == 422 and "do not match" in mismatch.text
    changed = await ui_browser.post(
        "/account/password",
        data={
            "csrf_token": csrf,
            "current_password": PASSWORD,
            "new_password": new,
            "confirm_password": new,
        },
    )
    assert changed.status_code == 303
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        actions = (await session.execute(select(AuditEvent.action))).scalars().all()
    assert "user.password_changed" in actions
    await ui_browser.post("/logout", data={"csrf_token": csrf})
    assert (await login(ui_browser, PASSWORD)).status_code != 303
    assert (await login(ui_browser, new)).status_code == 303


async def test_the_theme_is_chosen_on_the_account_page(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    csrf = await signed_in(ui_browser, db_engine)
    saved = await ui_browser.post(
        "/account/theme", data={"csrf_token": csrf, "theme": "dark"}
    )
    assert saved.status_code == 303
    assert (await user_row(db_engine)).theme == "dark"
    page = (await ui_browser.get("/account")).text
    assert '<html lang="en" data-theme="dark">' in page
    refused = await ui_browser.post(
        "/account/theme", data={"csrf_token": csrf, "theme": "purple"}
    )
    assert refused.status_code == 422
