"""Mapping verification (phase 11): unverified rows, the register and the reports.

`revrook verify-mappings` lists the mapping rows nobody has verified, checks every
NIST identifier against the pinned names extract (a consistency check, not a
comparison with the full NIST catalog), and keeps the register of
docs/mapping-verification.md equal to the rows marked verified. A report never
prints an unverified identifier.
"""

import dataclasses
from collections import Counter
from pathlib import Path

import pytest

from app import cli
from app.checks.library import Library, load_library
from app.checks.mappings import (
    MARKERS_MISSING,
    REGISTER_COLUMNS,
    REGISTER_END,
    REGISTER_PATH,
    REGISTER_START,
    RegisterRow,
    RowKey,
    entries,
    parse_register,
    register_problems,
    resolve_nist_rows,
    source_problems,
    unpinned_frameworks,
    unverified,
)
from app.checks.reference import CREDIT_MARK, load_reference_names
from app.reports.render import KINDS
from tools import make_report_golden, report_clients

LIBRARY = load_library()
REFERENCES = load_reference_names()
DOCUMENT = REGISTER_PATH.read_text(encoding="utf-8")
FRAMEWORKS = ("csf", "sp800-171", "cis", "iso27001", "cyber-essentials", "nis2")
# Identifiers long enough and unusual enough to search a report for.
SEARCHABLE = ("csf", "sp800-171", "iso27001")
KEY = RowKey("PC-ACC-02", "csf", "PR.AA-03")
SOURCE = "NIST CSF 2.0, catalog 1.2.0"


def with_verified(library: Library, key: RowKey) -> Library:
    """The library with one mapping row marked verified."""
    controls = []
    for control in library.controls:
        rows = []
        for row in control.mappings:
            if RowKey(control.id, row.framework, row.id) == key:
                rows.append(dataclasses.replace(row, verified=True))
            else:
                rows.append(row)
        controls.append(dataclasses.replace(control, mappings=tuple(rows)))
    return dataclasses.replace(library, controls=tuple(controls))


def line(key: RowKey, date_read: str = "2026-10-19") -> str:
    """One line of the register table."""
    cells = [
        key.control,
        key.framework,
        key.identifier,
        SOURCE,
        date_read,
        "R. Reader",
    ]
    return "| " + " | ".join(cells) + " |"


def register_with(*lines: str) -> str:
    """A document whose register holds the given lines under its header."""
    header = "| " + " | ".join(REGISTER_COLUMNS) + " |"
    rule = "| " + " | ".join("---" for _ in REGISTER_COLUMNS) + " |"
    body = "\n".join([header, rule, *lines])
    return f"text\n{REGISTER_START}\n{body}\n{REGISTER_END}\nmore"


# --- the rows of the control file --------------------------------------------------


def test_the_library_has_rows_in_all_six_frameworks_and_none_is_verified() -> None:
    found = entries(LIBRARY)
    assert {entry.key.framework for entry in found} == set(FRAMEWORKS)
    assert len(found) > 300
    assert unverified(LIBRARY) == found


def test_the_frameworks_without_a_pinned_source_are_named() -> None:
    assert unpinned_frameworks(LIBRARY) == [
        "cis",
        "cyber-essentials",
        "iso27001",
        "nis2",
    ]


def test_every_nist_identifier_is_in_the_pinned_names_extract() -> None:
    found = resolve_nist_rows(LIBRARY, REFERENCES)
    assert [item.framework for item in found] == ["csf", "sp800-171"]
    for item in found:
        assert item.rows > 0
        assert item.unresolved == ()
        assert item.resolved == item.rows


def test_an_identifier_the_pinned_names_extract_lacks_is_reported() -> None:
    csf = REFERENCES["csf"]
    names = {key: name for key, name in csf.names.items() if key != "PR.AA-03"}
    references = {**REFERENCES, "csf": dataclasses.replace(csf, names=names)}
    result = resolve_nist_rows(LIBRARY, references)[0]
    assert result.unresolved
    assert result.resolved < result.rows
    assert all(label.endswith("PR.AA-03") for label in result.unresolved)


def test_the_document_states_the_counts_of_the_control_file() -> None:
    found = entries(LIBRARY)
    counts = Counter(entry.key.framework for entry in found)
    uncertain = sum(1 for entry in found if entry.uncertain)
    named = ", ".join(f"{name} {counts[name]}" for name in FRAMEWORKS)
    text = " ".join(DOCUMENT.split())
    assert f"there are {len(found)} mapping rows: {named}." in text
    assert f"{uncertain} of them are marked uncertain" in text


def test_the_document_names_the_commit_and_version_of_each_pinned_source() -> None:
    assert source_problems(REFERENCES, DOCUMENT) == []
    problems = source_problems(REFERENCES, "no versions are named here")
    assert len(problems) == 4
    assert {problem.split(":")[0] for problem in problems} == {"csf", "sp800-171"}


# --- the register ---------------------------------------------------------------------


def test_the_register_of_the_repository_is_empty_and_agrees_with_the_file() -> None:
    rows, problems = parse_register(DOCUMENT)
    assert rows == []
    assert problems == []
    assert register_problems(LIBRARY, rows) == []


def test_a_register_line_is_read_into_its_cells() -> None:
    rows, problems = parse_register(register_with(line(KEY)))
    assert problems == []
    assert rows == [RegisterRow(KEY, SOURCE, "2026-10-19", "R. Reader")]


@pytest.mark.parametrize("date_read", ["2026-13-40", "19/10/2026", "", "20261019"])
def test_a_register_line_needs_a_real_date(date_read: str) -> None:
    _, problems = parse_register(register_with(line(KEY, date_read)))
    assert len(problems) == 1
    assert problems[0].startswith(KEY.label())


def test_a_register_line_needs_the_name_of_the_reader() -> None:
    cells = [KEY.control, KEY.framework, KEY.identifier, SOURCE, "2026-10-19", " "]
    _, problems = parse_register(register_with("| " + " | ".join(cells) + " |"))
    assert len(problems) == 1
    assert problems[0].startswith(KEY.label())


def test_a_register_line_with_five_cells_is_a_problem() -> None:
    rows, problems = parse_register(register_with("| a | b | c | d | e |"))
    assert rows == []
    assert problems == ["a register line does not have six cells"]


def test_a_document_without_its_markers_has_no_register() -> None:
    assert parse_register("nothing here") == ([], [MARKERS_MISSING])
    backwards = f"{REGISTER_END}\n{REGISTER_START}"
    assert parse_register(backwards) == ([], [MARKERS_MISSING])


def test_a_verified_row_without_a_register_line_is_a_problem() -> None:
    message = f"{KEY.label()} is marked verified but is not in the register"
    assert register_problems(with_verified(LIBRARY, KEY), []) == [message]


def test_a_register_line_for_an_unverified_row_is_a_problem() -> None:
    rows, _ = parse_register(register_with(line(KEY)))
    message = f"{KEY.label()} is in the register but is not marked verified"
    assert register_problems(LIBRARY, rows) == [message]


def test_a_verified_row_with_its_register_line_is_accepted() -> None:
    rows, _ = parse_register(register_with(line(KEY)))
    assert register_problems(with_verified(LIBRARY, KEY), rows) == []


def test_a_row_written_twice_in_the_register_is_a_problem() -> None:
    rows, _ = parse_register(register_with(line(KEY), line(KEY)))
    message = f"{KEY.label()} is in the register 2 times"
    assert register_problems(with_verified(LIBRARY, KEY), rows) == [message]


# --- the command ----------------------------------------------------------------------


def test_the_command_passes_and_prints_counts_and_source_versions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.verify_mappings_command() == 0
    out = capsys.readouterr().out
    assert f"{len(entries(LIBRARY))} mapping rows are still unverified" in out
    assert "NIST CSF 2.0: " in out and ", 0 verified, " in out
    csf = REFERENCES["csf"]
    assert f"{csf.framework}: " in out
    assert "identifiers are in the pinned names extract" in out
    assert "not a comparison with the full NIST catalog" in out
    assert f"commit {csf.source['commit'][:12]}, catalog version 1.2.0" in out
    unpinned = "no pinned names extract for: cis, cyber-essentials, iso27001, nis2"
    assert unpinned in out


def test_the_command_lists_every_unverified_row_on_request(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.verify_mappings_command(show_rows=True) == 0
    out = capsys.readouterr().out
    assert "PC-ACC-02  csf  PR.AA-03" in out
    assert " [U]" in out
    assert out.count("\nPC-") == len(entries(LIBRARY))


def test_the_strict_command_fails_while_a_row_is_unverified(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.verify_mappings_command(strict=True) == 1
    assert "strict: " in capsys.readouterr().out


def test_the_subcommand_needs_no_settings_and_takes_its_options(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("SECRET_KEY", "FERNET_KEY", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    assert cli.main(["verify-mappings"]) == 0
    assert cli.main(["verify-mappings", "--list"]) == 0
    assert cli.main(["verify-mappings", "--strict"]) == 1
    assert "mapping rows are still unverified" in capsys.readouterr().out


def test_the_command_exits_2_when_the_register_cannot_be_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.verify_mappings_command(register_path=tmp_path / "missing.md") == 2
    assert "missing.md cannot be read" in capsys.readouterr().out


def test_the_command_exits_2_when_the_register_is_not_utf_8_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "register.md"
    path.write_bytes(b"# register\n\xff\xfe\xc3(\n")
    assert cli.verify_mappings_command(register_path=path) == 2
    out = capsys.readouterr().out
    assert "register.md cannot be read" in out
    assert str(tmp_path) not in out
    assert "codec" not in out
    assert "0xff" not in out


def test_the_command_exits_1_when_the_register_and_the_file_disagree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = DOCUMENT.replace(REGISTER_END, line(KEY) + "\n" + REGISTER_END)
    path = tmp_path / "register.md"
    path.write_text(document, encoding="utf-8")
    assert cli.verify_mappings_command(register_path=path) == 1
    out = capsys.readouterr().out
    assert f"{KEY.label()} is in the register but is not marked verified" in out


# --- the reports ----------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("name", tuple(report_clients.NAMES))
def test_a_report_prints_no_unverified_identifier_and_no_credit(
    kind: str, name: str
) -> None:
    html = make_report_golden.golden_html(LIBRARY, kind, name).decode("utf-8")
    assert len(html) > 1000
    assert CREDIT_MARK not in html
    for entry in unverified(LIBRARY):
        if entry.key.framework in SEARCHABLE:
            assert entry.key.identifier not in html, entry.key.label()
