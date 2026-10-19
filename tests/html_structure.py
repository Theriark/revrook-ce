"""A structural check of an HTML page with the standard library's html.parser.

axe-core needs a browser and is not in the development lock, and html5lib is not
either, so this check reads the page as the parser of the standard library sees it
and lists what is wrong (docs/testing.md records what it does and does not cover):

- every element that is opened is closed in order, and nothing is closed that was not
  opened (a void element such as <input> needs no end tag);
- a paragraph holds no block element (a browser would close the paragraph early);
- the root element has a lang attribute, there is exactly one h1 and one main;
- every id is used once, and every label, aria reference and htmx target names an id
  that exists;
- every image has an alt attribute;
- every input, select and textarea a person fills in has a label: a <label for>, a
  label around it, or aria-label / aria-labelledby.

It does not check colour contrast (tests/test_brand_contrast.py and
tests/test_report_contrast.py do), the order of headings, focus order or anything a
browser decides when it lays out the page.
"""

from html.parser import HTMLParser

VOID = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }
)
BLOCK = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "details",
        "div",
        "dl",
        "fieldset",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "ul",
    }
)
NOT_FILLED_IN = frozenset({"hidden", "submit", "button", "reset", "image"})
ID_LISTS = ("aria-labelledby", "aria-describedby", "aria-controls")


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.problems: list[str] = []
        self.stack: list[str] = []
        self.ids: list[str] = []
        self.label_for: list[str] = []
        self.references: list[tuple[str, str]] = []
        self.fields: list[tuple[str, str | None, bool]] = []
        self.counts: dict[str, int] = {}
        self.lang: str | None = None
        self.labels_open = 0

    def _element(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value for name, value in attrs}
        self.counts[tag] = self.counts.get(tag, 0) + 1
        if tag in BLOCK and self.stack and self.stack[-1] == "p":
            self.problems.append(f"<{tag}> inside <p>")
        if tag == "html":
            self.lang = values.get("lang") or ""
        element_id = values.get("id")
        if element_id is not None:
            self.ids.append(element_id)
        if tag == "label" and values.get("for"):
            self.label_for.append(str(values["for"]))
        for name in ID_LISTS:
            for target in (values.get(name) or "").split():
                self.references.append((name, target))
        target = values.get("hx-target") or ""
        if target.startswith("#"):
            self.references.append(("hx-target", target[1:]))
        if tag == "img" and "alt" not in values:
            self.problems.append(f"<img src={values.get('src')!r}> has no alt")
        if tag in ("input", "select", "textarea"):
            kind = (values.get("type") or "text").lower()
            if tag != "input" or kind not in NOT_FILLED_IN:
                named = self.labels_open > 0 or bool(
                    values.get("aria-label") or values.get("aria-labelledby")
                )
                self.fields.append(
                    (f"<{tag} name={values.get('name')!r}>", element_id, named)
                )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._element(tag, attrs)
        if tag == "label":
            self.labels_open += 1
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._element(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            self.problems.append(f"</{tag}> closes a void element")
            return
        if tag not in self.stack:
            self.problems.append(f"</{tag}> closes nothing that is open")
            return
        if self.stack[-1] != tag:
            self.problems.append(f"</{tag}> closes <{self.stack[-1]}>")
        while True:
            closed = self.stack.pop()
            if closed == "label":
                self.labels_open -= 1
            if closed == tag:
                return


def structure_problems(html: str) -> list[str]:
    """What is wrong with the structure of a whole page; empty when nothing is."""
    reader = _Reader()
    reader.feed(html)
    reader.close()
    problems = list(reader.problems)
    if reader.stack:
        problems.append(f"left open: {reader.stack}")
    if not reader.lang:
        problems.append("<html> has no lang")
    for tag in ("h1", "main"):
        if reader.counts.get(tag, 0) != 1:
            problems.append(f"{reader.counts.get(tag, 0)} <{tag}> elements, not 1")
    seen: set[str] = set()
    for element_id in reader.ids:
        if element_id in seen:
            problems.append(f"the id {element_id!r} is used twice")
        seen.add(element_id)
    for target in reader.label_for:
        if target not in seen:
            problems.append(f"<label for={target!r}> names no element")
    for name, target in reader.references:
        if target not in seen:
            problems.append(f"{name}={target!r} names no element")
    labelled = set(reader.label_for)
    for field, element_id, named in reader.fields:
        if not named and (element_id is None or element_id not in labelled):
            problems.append(f"{field} has no label")
    return problems
