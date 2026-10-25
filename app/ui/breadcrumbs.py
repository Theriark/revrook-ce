"""The breadcrumb of the top bar (templates/_topbar.html): where a page sits.

The trail is made from what every page already puts in its context: `nav` (the
place in the rail), and on the pages of one client `client_id`, `client_name` and
`section` (the tab). A page deeper than its tab names itself with `crumb_leaf`
(the control page, a made report). Every step but the last is a link; the last is
the page itself, with no link. A path is kept without its leading slash: the
template writes the slash, so every link in a template is visibly same-origin. A
pure function, so a template rendered without a request (the tests) draws the
same trail.
"""

from dataclasses import dataclass

HOME = "Home"
# The places of the rail (templates/_nav.html) with their words and their address.
PLACES = {
    "home": ("Home", ""),
    "clients": ("Clients", "clients"),
    "profile-editor": ("Profile editor", "imports/profile-editor"),
    "integrity": ("Evidence integrity", "evidence/integrity"),
    "explorer": ("Evidence Explorer", "experiments/evidence-explorer"),
    "settings": ("Settings", "settings"),
    "system": ("System", "system"),
    "glossary": ("Glossary", "glossary"),
}
# The tabs of one client (templates/_client_nav.html): the words and the path
# after /clients/<id>. The overview is the client's own page.
SECTIONS = {
    "overview": ("Overview", ""),
    "checklist": ("Checklist", "/checklist"),
    "evidence": ("Evidence and imports", "/evidence"),
    "exceptions": ("Exceptions", "/exceptions"),
    "reports": ("Reports", "/reports"),
    "exports": ("Export history", "/exports"),
}


@dataclass(frozen=True)
class Crumb:
    """One step of the trail; `path` is None for the page itself (Home is "")."""

    text: str
    path: str | None = None


def _closed(steps: list[Crumb]) -> list[Crumb]:
    """The trail with its last step as the page itself (no link)."""
    if not steps:
        return [Crumb(HOME)]
    return [*steps[:-1], Crumb(steps[-1].text)]


def breadcrumb_trail(
    nav: str = "",
    title: str = "",
    client_id: int | None = None,
    client_name: str = "",
    section: str = "",
    leaf: str = "",
) -> list[Crumb]:
    """The breadcrumb of a page, from Home to the page itself.

    Home alone on the home page; Home, then the place of the rail; on a page of
    one client, Home, Clients, the client, its tab and, deeper, the leaf. A page
    outside the rail (a refusal) is Home, then its title.
    """
    steps = [Crumb(HOME, "")]
    if nav == "home":
        return _closed(steps)
    if nav in PLACES:
        text, path = PLACES[nav]
        steps.append(Crumb(text, path))
    elif title:
        steps.append(Crumb(title))
    if nav == "clients" and client_id is not None and client_name:
        base = f"clients/{client_id}"
        steps.append(Crumb(client_name, base))
        if section in SECTIONS and section != "overview":
            text, path = SECTIONS[section]
            steps.append(Crumb(text, base + path))
        if leaf:
            steps.append(Crumb(leaf))
    return _closed(steps)
