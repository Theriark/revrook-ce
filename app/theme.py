"""The theme of the interface: light, dark, or the one the system prefers; and the
rail, open or folded to its icons.

A person chooses it with the switch in the rail (app/ui/templates/_theme.html),
which posts to /theme (app/ui/site.py). The choice is kept on the user row, so it
follows them to every browser they sign in from, and mirrored in a cookie, so the
sign-in page is drawn in the same theme before anyone is signed in. The page
carries it as data-theme on the root element and the stylesheet does the rest
(docs/design-system.md, Themes).
"""

from fastapi import Request

from app.models import AppUser

THEMES = ("light", "dark", "system")
DEFAULT_THEME = "system"
THEME_COOKIE = "rv_theme"
# A year: the choice is a preference, not a credential.
THEME_COOKIE_MAX_AGE = 365 * 24 * 60 * 60
# What the color-scheme meta says for each theme: form controls and scrollbars
# follow it, and "light dark" lets the system decide.
COLOR_SCHEMES = {"light": "light", "dark": "dark", "system": "light dark"}
# The rail (app/ui/templates/_rail.html): open with its words, or folded to its
# icons from 1024px. A browser preference, kept in a cookie alone.
RAILS = ("expanded", "compact")
DEFAULT_RAIL = "expanded"
RAIL_COOKIE = "rv_rail"


def normalise_theme(value: object) -> str:
    """One of THEMES; anything else (missing, forged, stale) is the default."""
    return value if isinstance(value, str) and value in THEMES else DEFAULT_THEME


def theme_of(request: Request, user: AppUser | None) -> str:
    """The theme a page is drawn in: the user's, or the cookie's when signed out."""
    if user is not None:
        return normalise_theme(user.theme)
    return normalise_theme(request.cookies.get(THEME_COOKIE))


def normalise_rail(value: object) -> str:
    """One of RAILS; anything else (missing, forged, stale) is the open rail."""
    return value if isinstance(value, str) and value in RAILS else DEFAULT_RAIL


def rail_of(request: Request) -> str:
    """The rail a page is drawn with: the one the cookie remembers, else open."""
    return normalise_rail(request.cookies.get(RAIL_COOKIE))


def safe_next(value: str) -> str:
    """A path of this site to come back to after the switch, or the home page.

    Only an absolute path without a scheme or a host is accepted: "//host" and
    "https://host" would send the person elsewhere, a backslash is read as a
    slash by some browsers, and a control character has no place in an address.
    """
    plain = value.isprintable() and "\\" not in value
    if plain and value.startswith("/") and not value.startswith("//"):
        return value
    return "/"
