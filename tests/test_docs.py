"""Documentation checks (phase 11): the set is complete, linked and true to the code.

The documents are part of the product, so they are tested like code. Every page a
self-hoster needs exists and is linked from the README, every link between pages points
at a file and a heading that exist, the configuration page names exactly the settings
of `app/settings.py` with their defaults, the files that a page names exist, the
CHANGELOG keeps its format, the README makes the statements the plan asks for, and the
quick start is run by the compose smoke test. Files only: no database, no network.
"""

import re
from dataclasses import MISSING, fields
from pathlib import Path

import pytest

from app.settings import Settings
from repo_files import ROOT

DOCS = ROOT / "docs"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"
PAGES = sorted([*ROOT.glob("*.md"), *DOCS.glob("*.md")])
PAGE_IDS = [page.relative_to(ROOT).as_posix() for page in PAGES]
REQUIRED = (
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "LICENSE",
    "docs/quick-start.md",
    "docs/install.md",
    "docs/configuration.md",
    "docs/operations.md",
    "docs/upgrade.md",
    "docs/security.md",
    "docs/security-review.md",
    "docs/extension-api.md",
    "docs/licences.md",
    "docs/mapping-verification.md",
    "docs/controls.md",
    "docs/scoring.md",
    "docs/importers.md",
    "docs/release-candidate.md",
)
# The pages written in phase 11, whose references to repository files are checked.
CHECKED = (
    "README.md",
    "CHANGELOG.md",
    "docs/quick-start.md",
    "docs/install.md",
    "docs/configuration.md",
    "docs/upgrade.md",
    "docs/mapping-verification.md",
    "docs/release-candidate.md",
)
STATEMENTS = (
    "community edition",
    "mit licence",
    "uncalibrated design choices",
    "mappings to outside frameworks are unverified unless marked",
    "not a certification",
)
CHANGELOG_KINDS = {"Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"}
FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
CODE_SPAN = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"\[[^\]\n]*\]\(([^)\s]+)\)")
HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*$", re.MULTILINE)
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:")
PATH_REFERENCE = re.compile(
    r"`((?:app|alembic|data|docs|scripts|tests|tools)/[A-Za-z0-9_./-]*[A-Za-z0-9_])`"
)
SETTING_ROW = re.compile(r"^\| `([A-Z][A-Z0-9_]+)` \| ([^|]+) \|", re.MULTILINE)
EDITION_NAMES = re.compile(
    r"revrook[-_.]ee|enterprise edition|ee[-_]only", re.IGNORECASE
)
RELEASED = re.compile(r"^\[\d+\.\d+\.\d+\] - \d{4}-\d{2}-\d{2}$")
TOKEN_OUTPUT = re.compile(r"(echo|printf|fail)\b[^|]*\$\{token\}")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def prose(text: str) -> str:
    """The text without code blocks and code spans, where a link is a link."""
    return CODE_SPAN.sub("", FENCE.sub("", text))


def slug(heading: str) -> str:
    """The anchor that GitHub makes for a heading."""
    text = heading.replace("`", "").strip().lower()
    return re.sub(r"[^\w -]", "", text).replace(" ", "-")


def anchors(path: Path) -> set[str]:
    """The anchors of the headings of a Markdown file."""
    return {slug(heading) for heading in HEADING.findall(FENCE.sub("", read(path)))}


def link_problems(page: Path) -> list[str]:
    """The links of `page` that point at a file or a heading that does not exist."""
    problems: list[str] = []
    for target in LINK.findall(prose(read(page))):
        if SCHEME.match(target):
            continue
        name, _, anchor = target.partition("#")
        destination = (page.parent / name).resolve() if name else page
        if destination.suffix != ".md":
            anchor = ""
        label = f"{page.name}: {target}"
        if not destination.exists():
            problems.append(f"{label} points at a missing file")
        elif anchor and anchor not in anchors(destination):
            problems.append(f"{label} points at a missing heading")
    return problems


def documented_settings() -> dict[str, str]:
    """The variables of the table of docs/configuration.md and their defaults."""
    text = read(DOCS / "configuration.md")
    return {name: cell.strip() for name, cell in SETTING_ROW.findall(text)}


def default_cell(default: object) -> str:
    """How docs/configuration.md writes a default: required, unset or the value."""
    if default is MISSING:
        return "required"
    if default is None:
        return "unset"
    return f"`{default}`"


# --- the set and its links ------------------------------------------------------------


def test_every_page_a_self_hoster_needs_exists() -> None:
    assert [name for name in REQUIRED if not (ROOT / name).is_file()] == []


def test_the_readme_links_every_page_of_the_docs_folder() -> None:
    targets = LINK.findall(prose(read(README)))
    linked = {Path(target.partition("#")[0]).name for target in targets}
    assert {page.name for page in DOCS.glob("*.md")} - linked == set()


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_every_link_between_pages_points_at_something_that_exists(page: Path) -> None:
    assert link_problems(page) == []


def test_the_link_checker_finds_a_missing_file_and_a_missing_heading(
    tmp_path: Path,
) -> None:
    page = tmp_path / "a.md"
    page.write_text(
        "# Real heading\n\n"
        "[ok](a.md#real-heading) [web](https://example.com/x) [m](mailto:a@b.c)\n"
        "[no file](b.md) [no heading](a.md#nothing)\n"
        "`[in a span](c.md)`\n\n"
        "```\n[in a block](d.md)\n```\n",
        encoding="utf-8",
    )
    assert link_problems(page) == [
        "a.md: b.md points at a missing file",
        "a.md: a.md#nothing points at a missing heading",
    ]


@pytest.mark.parametrize("name", CHECKED)
def test_the_files_a_page_names_exist(name: str) -> None:
    text = read(ROOT / name)
    missing = [
        path for path in PATH_REFERENCE.findall(text) if not (ROOT / path).exists()
    ]
    assert missing == []


# --- the configuration page -----------------------------------------------------------


def test_the_configuration_page_names_every_setting_with_its_default() -> None:
    expected = {
        item.name.upper(): default_cell(item.default) for item in fields(Settings)
    }
    assert documented_settings() == expected


def test_every_documented_setting_is_read_from_the_environment() -> None:
    source = read(ROOT / "app" / "settings.py")
    unread = [name for name in documented_settings() if f'"{name}"' not in source]
    assert unread == []


# --- the statements and the CHANGELOG -------------------------------------------------


def test_the_readme_makes_the_statements_the_plan_asks_for() -> None:
    text = " ".join(read(README).lower().split())
    assert [statement for statement in STATEMENTS if statement not in text] == []


@pytest.mark.parametrize("name", CHECKED)
def test_no_page_names_a_later_edition(name: str) -> None:
    assert EDITION_NAMES.search(read(ROOT / name)) is None


def test_the_changelog_follows_keep_a_changelog() -> None:
    text = read(CHANGELOG)
    assert text.startswith("# Changelog\n")
    assert "Keep a Changelog" in text
    versions = re.findall(r"^## (.+)$", text, re.MULTILINE)
    assert versions[0] == "[Unreleased]"
    assert all(RELEASED.match(version) for version in versions[1:])
    kinds = re.findall(r"^### (.+)$", text, re.MULTILINE)
    assert kinds
    assert set(kinds) <= CHANGELOG_KINDS


# --- the quick start ------------------------------------------------------------------


def test_the_compose_smoke_test_runs_the_quick_start() -> None:
    runner = read(ROOT / "tests" / "e2e" / "run.sh")
    flow = read(ROOT / "scripts" / "e2e" / "phase_11.sh")
    assert "scripts/e2e/phase_11.sh" in runner
    assert "scripts/demo.sh" in flow
    assert "LIMIT_SECONDS=600" in flow
    assert "bash scripts/demo.sh" in read(DOCS / "quick-start.md")


def test_the_demo_script_never_prints_its_token() -> None:
    script = read(ROOT / "scripts" / "demo.sh")
    shown = [line for line in script.splitlines() if TOKEN_OUTPUT.search(line)]
    assert shown == []
    assert "${token}" in script
