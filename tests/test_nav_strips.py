"""The navigation strips from 600px to 1023px and on a phone (THE-1414, F2).

On Development at 768px (THE-1413) the main navigation was a strip that scrolled
sideways: its eight links needed 1178px in 767px, and Settings, System and Glossary
sat out of view with no cue, since the edge fell between two links and the fade
had nothing to dim. The client tabs scrolled too, by the 48px kept after the last
tab. Now from 600px to 1023px the main navigation wraps onto a second row and the
client tabs wrap from 600px, and below 600px both strips keep scrolling with a
chevron beside the fade. These tests render the shell and the client tabs, check
that each new rule reaches the markup it is written for, and that the links and
their order (the tab order) are those of the wide rail.
"""

import re
from html.parser import HTMLParser
from types import SimpleNamespace

from app.ui.auth import templates
from app.ui.brand import STATIC_DIR

CSS = (STATIC_DIR / "css/revamp.css").read_text(encoding="utf-8")
PAGE = """{% extends "base.html" %}{% block content %}
{% include "_client_nav.html" %}{% endblock %}"""
MAIN_LINKS = [
    ("/", "Home"),
    ("/clients", "Clients"),
    ("/imports/profile-editor", "Profile editor"),
    ("/evidence/integrity", "Evidence integrity"),
    ("/experiments/evidence-explorer", "Evidence Explorer"),
    ("/settings", "Settings"),
    ("/system", "System"),
    ("/glossary", "Glossary"),
]
SECTION = "Findings of the deployed acceptance of 0b6372b1 (THE-1414)"


class Element:
    def __init__(self, tag: str, attrs: dict[str, str], parent: "Element | None"):
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[Element] = []
        self.text = ""

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


class Tree(HTMLParser):
    VOID = {"input", "img", "link", "meta", "br", "hr", "source"}

    def __init__(self, html: str) -> None:
        super().__init__()
        self.root = Element("#root", {}, None)
        self.at = self.root
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        element = Element(tag, {k: v or "" for k, v in attrs}, self.at)
        self.at.children.append(element)
        if tag not in self.VOID:
            self.at = element

    def handle_endtag(self, tag):
        node = self.at
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.at = node.parent

    def handle_data(self, data):
        node = self.at
        while node is not None:
            node.text += data
            node = node.parent


def compound(part: str, element: Element) -> bool:
    """Whether one compound selector (tag, classes, [attr="value"]) fits."""
    part = re.sub(r"\[[^\]]*\]", "", part)
    tag, *classes = part.split(".")
    if tag and tag != element.tag:
        return False
    return set(classes) <= element.classes


def matches(selector: str, element: Element) -> bool:
    """A selector of compounds joined by descendant and child combinators."""
    parts = selector.replace(">", " > ").split()
    if not compound(parts[-1], element):
        return False
    node, need_child, rest = element, False, parts[:-1]
    while rest:
        token = rest.pop()
        if token == ">":
            need_child = True
            continue
        node = node.parent
        if need_child:
            if node is None or not compound(token, node):
                return False
        else:
            while node is not None and not compound(token, node):
                node = node.parent
            if node is None:
                return False
        need_child = False
    return True


def page() -> Tree:
    html = templates.env.from_string(PAGE).render(
        user=SimpleNamespace(username="revrook-admin"),
        csrf_token="x" * 32,
        title="Overview",
        nav="clients",
        client_id=1,
        client_name="Alder Ltd",
        section="overview",
    )
    return Tree(html)


def new_rules() -> list[tuple[str, str, str]]:
    """(media query, selector, declarations) of every rule of the THE-1414 block."""
    block = CSS.split(SECTION, 1)[1]
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.DOTALL)
    rules = []
    for media, body in re.findall(r"@media ([^{]+)\{(.*?)\n\}", block, re.DOTALL):
        for selectors, declarations in re.findall(r"([^{}]+)\{([^}]*)\}", body):
            for selector in selectors.split(","):
                rules.append((media.strip(), selector.strip(), declarations))
    return rules


def test_every_new_strip_rule_reaches_the_rendered_markup() -> None:
    tree = page()
    everything = list(tree.root.walk())
    rules = new_rules()
    assert len(rules) >= 10
    for media, selector, _ in rules:
        target = re.sub(r"::(before|after)$", "", selector)
        assert any(matches(target, element) for element in everything), (
            media,
            selector,
        )


def test_the_links_and_their_order_stay_those_of_the_rail() -> None:
    tree = page()
    navs = [e for e in tree.root.walk() if e.tag == "nav"]
    main = next(e for e in navs if e.attrs.get("aria-label") == "Main")
    assert main.classes == {"rv-nav"} and "rv-nav-strip" in main.parent.classes
    links = [e for e in main.walk() if e.tag == "a"]
    assert [(a.attrs["href"], a.text.strip()) for a in links] == MAIN_LINKS
    # Each link sits in a list item of a group list, the items the rows wrap
    for link in links:
        assert link.parent.tag == "li" and "rv-nav-list" in link.parent.parent.classes
    current = [a.text.strip() for a in links if a.attrs.get("aria-current") == "page"]
    assert current == ["Clients"]
    # The client tabs: one list of six links in the strip, the current one marked
    tabs = next(e for e in navs if e.attrs.get("aria-label") == "This client")
    assert "rv-tabs-strip" in tabs.parent.classes
    names = [a.text.strip() for a in tabs.walk() if a.tag == "a"]
    assert names == [
        "Overview",
        "Checklist",
        "Evidence and imports",
        "Exceptions",
        "Reports",
        "Export history",
    ]
    # No tab stop is added or taken: no tabindex anywhere in either strip
    for element in [*main.walk(), *tabs.walk()]:
        assert "tabindex" not in element.attrs


def test_from_600_to_1023_the_main_navigation_wraps_and_never_scrolls() -> None:
    rules = new_rules()
    band = "(min-width: 600px) and (max-width: 1023px)"
    found = {selector: body for media, selector, body in rules if media == band}
    nav = found[".rv-app .rv-header .rv-nav"]
    assert "display: block;" in nav and "overflow-x: visible;" in nav
    assert "display: inline;" in found[".rv-app .rv-header .rv-nav-list"]
    item = found[".rv-app .rv-header .rv-nav li"]
    assert "display: inline-block;" in item and "margin: 0 4px 4px 0;" in item
    # Nothing scrolls, so no fade and no space kept for it
    assert "display: none;" in found[".rv-app .rv-nav-strip::after"]
    assert "display: none;" in found[".rv-app .rv-header .rv-nav::after"]


def test_the_client_tabs_wrap_from_600px_and_a_phone_gets_a_chevron() -> None:
    rules = new_rules()
    wide = {s: b for m, s, b in rules if m == "(min-width: 600px)"}
    assert "flex-wrap: wrap;" in wide[".rv-tabs-strip > nav > ul"]
    assert "overflow-x: visible;" in wide[".rv-tabs-strip > nav"]
    assert "display: none;" in wide[".rv-tabs-strip > nav > ul::after"]
    phone = {s: b for m, s, b in rules if m == "(max-width: 599px)"}
    for strip in (".rv-nav-strip", ".rv-tabs-strip"):
        chevron = phone[f"{strip}::before"]
        assert 'content: "";' in chevron and "pointer-events: none;" in chevron
        assert "border-top: 2px solid;" in chevron and "rotate(45deg)" in chevron
        # It goes with the fade once the last link is in view (revrook.js)
        assert "display: none;" in phone[f'{strip}[data-scroll-end="true"]::before']
    # Tokens only: no colour literal in the block
    block = CSS.split(SECTION, 1)[1]
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b|rgb\(", block)
