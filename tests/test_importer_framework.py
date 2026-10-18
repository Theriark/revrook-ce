"""The importer framework: text, CSV, JSON, values, rejects and limits."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.importers import framework
from app.importers.base import ImportRejectedError, ParsedFact
from app.importers.framework import (
    Column,
    Flags,
    MissingStructureError,
    Rejects,
    RowError,
    as_row,
    choice,
    column_key,
    decode_text,
    iso,
    json_capture_time,
    json_records,
    json_rows,
    load_json,
    number_text,
    open_csv,
    optional_choice,
    parse_bool,
    parse_moment,
    parse_number,
    prefix_choice,
    read_count,
    read_flag,
    read_header,
    read_required_time,
    read_rows,
    read_text,
    read_time,
    require_fields,
    resolve_columns,
    safe_text,
    slug,
    summary_fact,
)

SPEC = (
    Column("name", "User name", required=True, aliases=("login",)),
    Column("flag", "Is Admin", required=True),
    Column("note", "Note"),
)
MAX_ROWS = 100


def csv_text(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def rows_of(text: str, max_rows: int = MAX_ROWS) -> list[tuple[int, dict[str, str]]]:
    return list(open_csv(text, SPEC, max_rows).rows())


# --- text ------------------------------------------------------------------


def test_utf8_with_and_without_a_byte_order_mark_is_read() -> None:
    assert decode_text("héllo".encode()) == "héllo"
    assert decode_text(b"\xef\xbb\xbfhello") == "hello"


def test_utf16_with_a_byte_order_mark_is_read() -> None:
    assert decode_text("héllo".encode("utf-16")) == "héllo"
    assert decode_text(b"\xfe\xff" + "héllo".encode("utf-16-be")) == "héllo"


def test_another_encoding_goes_through_charset_detection() -> None:
    legacy = ("name;café;naïve;über;señor\n" * 40).encode("cp1252")
    assert decode_text(legacy).startswith("name;")


@pytest.mark.parametrize(
    "data",
    [
        b"\x00\x01\x02\xff" * 50,
        b"a\x00b",
        bytes(range(256)) * 4,
        "a\x00b".encode("utf-16"),
    ],
)
def test_binary_data_is_not_readable_text(data: bytes) -> None:
    with pytest.raises(ImportRejectedError, match="not readable text"):
        decode_text(data)


def test_column_names_compare_without_case_spaces_and_the_loc_suffix() -> None:
    assert column_key("User principal name") == "userprincipalname"
    assert column_key(" userPrincipalName ") == "userprincipalname"
    assert column_key("DeviceName_loc") == "devicename"
    assert column_key("OS_LOC") == "os"
    assert slug(None) == ""
    assert slug("Ab-1 !") == "ab1"


# --- CSV ---------------------------------------------------------------------


def test_columns_are_found_by_name_alias_and_case() -> None:
    header = ["LOGIN", " is admin ", "Other", "Note_loc"]
    found = resolve_columns(header, SPEC)
    assert found == {"name": 0, "flag": 1, "note": 3}


def test_a_saved_mapping_wins_over_name_matching() -> None:
    header = ["Vendor user", "Admin?", "login"]
    mapping = {"Vendor user": "name", "Admin?": "flag", "login": "note"}
    found = resolve_columns(header, SPEC, mapping)
    assert found == {"name": 0, "flag": 1, "note": 2}


def test_a_column_found_twice_rejects_the_file() -> None:
    with pytest.raises(ImportRejectedError, match="the column User name twice"):
        resolve_columns(["User name", "login", "Is Admin"], SPEC)
    with pytest.raises(ImportRejectedError, match="the column Is Admin twice"):
        resolve_columns(["Is Admin", "x"], SPEC, {"x": "flag"})


def test_rows_are_numbered_from_one_and_blank_lines_are_skipped() -> None:
    text = "\n\nUser name,Is Admin,Note\n\na,true,first\n,,\nb,false,second\n"
    assert rows_of(text) == [
        (1, {"name": "a", "flag": "true", "note": "first"}),
        (2, {"name": "b", "flag": "false", "note": "second"}),
    ]


def test_a_short_row_lacks_the_keys_it_has_no_cell_for() -> None:
    assert rows_of(csv_text("User name,Is Admin,Note", "a,true")) == [
        (1, {"name": "a", "flag": "true"})
    ]


def test_a_byte_order_mark_and_windows_line_ends_are_accepted() -> None:
    raw = "﻿User name,Is Admin\r\na,true\r\nb,false\r\n".encode()
    rows = rows_of(decode_text(raw))
    assert [row["name"] for _, row in rows] == ["a", "b"]


def test_a_file_that_lacks_required_columns_is_rejected_naming_them() -> None:
    with pytest.raises(MissingStructureError, match="missing the column Is Admin."):
        open_csv("User name,Note\na,b\n", SPEC, MAX_ROWS)
    with pytest.raises(MissingStructureError, match="column User name, Is Admin."):
        open_csv("x,y\n1,2\n", SPEC, MAX_ROWS)


def test_an_empty_file_has_no_header() -> None:
    for text in ("", "\n\n", ",,\n"):
        with pytest.raises(ImportRejectedError, match="The file is empty"):
            open_csv(text, SPEC, MAX_ROWS)


def test_more_rows_than_the_limit_are_rejected() -> None:
    lines = ["User name,Is Admin"] + [f"u{n},true" for n in range(4)]
    with pytest.raises(ImportRejectedError, match="more than 3 rows"):
        rows_of(csv_text(*lines), max_rows=3)
    assert len(rows_of(csv_text(*lines), max_rows=4)) == 4


def test_a_field_larger_than_the_csv_limit_is_rejected() -> None:
    huge = "x" * 200_000
    with pytest.raises(ImportRejectedError, match="not a readable CSV"):
        rows_of(csv_text("User name,Is Admin", f"{huge},true"))
    with pytest.raises(ImportRejectedError, match="not a readable CSV"):
        read_header(f"{huge},b\n")
    with pytest.raises(ImportRejectedError, match="not a readable CSV"):
        open_csv(f"{huge},b\n", SPEC, MAX_ROWS)


def test_the_header_of_a_text_can_be_read_alone() -> None:
    assert read_header("\nA,B,C\n1,2,3\n") == ["A", "B", "C"]


# --- JSON --------------------------------------------------------------------


def test_json_numbers_with_a_fraction_are_exact_decimals() -> None:
    root = load_json(b'{"score": 48.5, "count": 3}', MAX_ROWS)
    assert root == {"score": Decimal("48.5"), "count": 3}


@pytest.mark.parametrize("text", ["{not json", "", "NaN", '{"a": Infinity}'])
def test_text_that_is_not_json_is_rejected(text: str) -> None:
    with pytest.raises(ImportRejectedError, match="not valid JSON|not readable"):
        load_json(text.encode(), MAX_ROWS)


def test_json_nested_too_deep_is_rejected() -> None:
    ok = "[" * 12 + "]" * 12
    assert load_json(ok.encode(), MAX_ROWS) is not None
    too_deep = "[" * 13 + "]" * 13
    with pytest.raises(ImportRejectedError, match="nested deeper than 12"):
        load_json(too_deep.encode(), MAX_ROWS)


def test_json_nested_far_beyond_the_parser_limit_is_rejected() -> None:
    hostile = "[" * 200_000 + "]" * 200_000
    with pytest.raises(ImportRejectedError, match="nested deeper than 12"):
        load_json(hostile.encode(), MAX_ROWS)


def test_a_json_list_longer_than_the_row_limit_is_rejected() -> None:
    data = json.dumps({"value": [1, 2, 3, 4]}).encode()
    with pytest.raises(ImportRejectedError, match="more than 3 items"):
        load_json(data, 3)
    assert load_json(data, 4) == {"value": [1, 2, 3, 4]}


def test_a_json_file_over_the_size_limit_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(framework, "MAX_JSON_BYTES", 10)
    with pytest.raises(ImportRejectedError, match="JSON file is larger than"):
        load_json(b'{"value": [1, 2, 3]}', MAX_ROWS)


def test_the_records_of_a_graph_answer() -> None:
    assert json_records([1, 2]) == [1, 2]
    assert json_records({"value": [1]}) == [1]
    assert json_records({"currentScore": 1}) == [{"currentScore": 1}]
    with pytest.raises(ImportRejectedError, match="JSON object or a list"):
        json_records(3)


def test_the_first_record_must_have_every_field() -> None:
    require_fields([], ["a"])
    require_fields([{"a": 1, "b": 2}], ["a", "b"])
    with pytest.raises(MissingStructureError, match="missing the field b, c."):
        require_fields([{"a": 1}], ["a", "b", "c"])
    with pytest.raises(MissingStructureError, match="missing the field a."):
        require_fields(["not an object"], ["a"])


def test_json_records_become_rows_keyed_like_a_csv_row() -> None:
    rows = list(json_rows([{"x": 1, "y": 2}, "text"], {"first": "x", "third": "z"}))
    assert rows[0] == (1, {"first": 1, "third": None})
    number, problem = rows[1]
    assert number == 2
    assert isinstance(problem, RowError)


def test_the_capture_time_of_a_json_file_is_the_capturedat_field() -> None:
    assert json_capture_time({"value": []}) == (None, False)
    assert json_capture_time([]) == (None, False)
    moment = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
    assert json_capture_time({"capturedAt": "2026-10-16T08:00:00Z"}) == (moment, False)
    assert json_capture_time({"capturedAt": "2026-10-16T08:00:00"}) == (moment, True)
    with pytest.raises(ImportRejectedError, match="capturedAt is not a date"):
        json_capture_time({"capturedAt": "yesterday"})


# --- values ------------------------------------------------------------------


def test_times_are_utc_and_flag_a_missing_time_zone() -> None:
    moment = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
    assert parse_moment("2026-10-16T08:00:00Z") == (moment, False)
    assert parse_moment("2026-10-16T10:00:00+02:00") == (moment, False)
    assert parse_moment(" 2026-10-16T08:00:00 ") == (moment, True)
    assert parse_moment("2026-10-16") == (datetime(2026, 10, 16, tzinfo=UTC), True)


@pytest.mark.parametrize(
    "value",
    [
        None,
        5,
        "",
        "yesterday",
        "1999-12-31T23:59:59Z",
        "2100-01-01T00:00:00Z",
        "0001-01-01T00:00:00+05:00",
    ],
)
def test_a_value_that_is_not_a_plausible_time_is_refused(value: object) -> None:
    with pytest.raises(ValueError, match="not a"):
        parse_moment(value)


def test_flags_are_true_false_yes_no_or_one_zero() -> None:
    for word in ("true", "TRUE", " yes ", "1", True):
        assert parse_bool(word) is True
    for word in ("false", "No", "0", False):
        assert parse_bool(word) is False
    for bad in ("maybe", "", None, 1, 2.5):
        with pytest.raises(ValueError, match="not a flag"):
            parse_bool(bad)


def test_numbers_are_exact_non_negative_and_finite() -> None:
    assert parse_number(3) == Decimal(3)
    assert parse_number(Decimal("48.5")) == Decimal("48.5")
    assert parse_number(" 7.25 ") == Decimal("7.25")
    for bad in (True, -1, "-0.5", "NaN", "Infinity", "1e12", "abc", None, [1]):
        with pytest.raises(ValueError, match="not a"):
            parse_number(bad)


def test_numbers_are_stored_as_exact_text() -> None:
    assert number_text(Decimal("48.50")) == "48.5"
    assert number_text(Decimal("100")) == "100"
    assert number_text(Decimal("1E+2")) == "100"
    assert number_text(Decimal("0.0")) == "0"
    assert number_text(Decimal("0")) == "0"


def test_kept_text_is_printable_short_and_never_a_formula() -> None:
    assert safe_text("Admin MFA") == "Admin MFA"
    assert safe_text("=cmd|' /C calc'!A0") == "'=cmd|' /C calc'!A0"
    assert safe_text("+1 -2 @x").startswith("'+")
    assert safe_text("-5").startswith("'-")
    assert safe_text("@home").startswith("'@")
    assert safe_text("a\tb\x00c\nd") == "abcd"
    assert safe_text("x" * 500) == "x" * 100
    assert safe_text("x" * 500, 10) == "x" * 10
    assert safe_text(None) == ""
    assert safe_text(12) == ""


def test_words_outside_a_vocabulary_become_other() -> None:
    vocabulary = {"compliant": "ok", "ingraceperiod": "grace"}
    assert choice("Compliant", vocabulary) == "ok"
    assert choice("in-grace-period", vocabulary) == "grace"
    assert choice("=cmd", vocabulary) == "other"
    assert choice(None, vocabulary) == "other"
    assert optional_choice(None, vocabulary) is None
    assert optional_choice("  ", vocabulary) is None
    assert optional_choice("compliant", vocabulary) == "ok"
    assert optional_choice("junk", vocabulary) == "other"
    prefixes = (("windows", "windows"), ("ios", "ios"))
    assert prefix_choice("iOS/iPadOS", prefixes) == "ios"
    assert prefix_choice("Windows 11", prefixes) == "windows"
    assert prefix_choice("Plan 9", prefixes) == "other"


def test_a_record_value_is_read_as_text_flag_count_or_time() -> None:
    raw: dict[str, object] = {
        "text": "  hello ",
        "blank": "  ",
        "number": 4,
        "yes": "Yes",
        "bad": "maybe",
        "count": "12",
        "when": "2026-10-16T08:00:00",
    }
    assert read_text(raw, "text") == "hello"
    assert read_text(raw, "blank") is None
    assert read_text(raw, "number") is None
    assert read_text(raw, "missing") is None
    assert read_flag(raw, "yes", "Flag") is True
    assert read_flag(raw, "missing", "Flag") is None
    with pytest.raises(RowError, match="Flag is empty"):
        read_flag(raw, "blank", "Flag", required=True)
    with pytest.raises(RowError, match="Flag must be true or false"):
        read_flag(raw, "bad", "Flag")
    assert read_count(raw, "count", "Count") == 12
    assert read_count(raw, "number", "Count") == 4
    assert read_count(raw, "missing", "Count") is None
    for bad in ("bad", "-3", "1.5"):
        with pytest.raises(RowError, match="Count must be a whole number"):
            read_count({"c": bad}, "c", "Count")
    for bad_number in (True, -1):
        with pytest.raises(RowError, match="Count must be a whole number"):
            read_count({"c": bad_number}, "c", "Count")
    flags = Flags()
    moment = read_time(raw, "when", "When", flags)
    assert moment == datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
    assert flags.assumed_utc is True
    assert read_time(raw, "missing", "When", flags) is None
    with pytest.raises(RowError, match="When is empty"):
        read_time(raw, "blank", "When", flags, required=True)
    with pytest.raises(RowError, match="When must be an ISO 8601"):
        read_time(raw, "bad", "When", flags)
    assert read_required_time(raw, "when", "When", flags) == moment
    assert iso(moment) == "2026-10-16T08:00:00+00:00"
    assert iso(None) is None


def test_a_time_with_a_zone_does_not_set_the_assumed_flag() -> None:
    flags = Flags()
    read_time({"t": "2026-10-16T08:00:00Z"}, "t", "T", flags)
    assert flags.assumed_utc is False


# --- rejects and the summary ----------------------------------------------------


def test_as_row_returns_a_row_or_raises_its_problem() -> None:
    assert as_row({"a": 1}) == {"a": 1}
    with pytest.raises(RowError, match="broken"):
        as_row(RowError("broken"))


def test_rejects_count_every_row_and_record_the_first_fifty() -> None:
    rejects = Rejects("demo")
    for number in range(1, 61):
        rejects.add(number, RowError(f"Column {number} is empty"))
    assert rejects.count == 60
    assert len(rejects.facts) == 50
    assert rejects.first == "Row 1: Column 1 is empty."
    first = rejects.facts[0]
    assert first.key == "demo.reject"
    assert first.value == {"row": 1, "reason": "Column 1 is empty"}


def test_a_file_with_no_readable_row_is_rejected_with_the_first_reason() -> None:
    rejects = Rejects("demo")
    rejects.require_usable(0)
    rejects.require_usable(3)
    rejects.add(2, RowError("Flag is empty"))
    rejects.require_usable(1)
    with pytest.raises(ImportRejectedError, match="No row .* Row 2: Flag is empty."):
        rejects.require_usable(0)


def read_one(raw: object, flags: Flags) -> ParsedFact:
    assert isinstance(raw, dict)
    name = read_text(raw, "name")
    if name is None:
        raise RowError("User name is empty")
    return ParsedFact("demo.row", {"admin": read_flag(raw, "flag", "Is Admin")})


def test_rows_that_cannot_be_read_are_rejected_one_by_one() -> None:
    table = open_csv(
        csv_text("User name,Is Admin", "a,true", ",true", "c,maybe", "d,no"),
        SPEC,
        MAX_ROWS,
    )
    flags = Flags()
    rejects = Rejects("demo")
    facts = read_rows(table.rows(), read_one, flags, rejects)
    assert [fact.value["admin"] for fact in facts] == [True, False]
    assert rejects.count == 2
    assert [fact.value["row"] for fact in rejects.facts] == [2, 3]


def test_rows_of_which_none_can_be_read_reject_the_file() -> None:
    table = open_csv(csv_text("User name,Is Admin", ",true"), SPEC, MAX_ROWS)
    with pytest.raises(ImportRejectedError, match="No row of the file could be read"):
        read_rows(table.rows(), read_one, Flags(), Rejects("demo"))


def test_the_summary_carries_the_counts_and_the_flags() -> None:
    rejects = Rejects("demo")
    rejects.add(1, RowError("x is empty"))
    flags = Flags(assumed_utc=True)
    in_file = summary_fact("demo", {"rows": 4}, rejects, flags, capture_in_file=True)
    assert in_file.key == "demo.summary"
    assert in_file.value == {
        "rows": 4,
        "rows_rejected": 1,
        "capture_time_source": "file",
        "timezone_assumed_utc": True,
    }
    upload = summary_fact("demo", {}, Rejects("demo"), Flags(), capture_in_file=False)
    assert upload.value["capture_time_source"] == "upload"
    assert upload.value["timezone_assumed_utc"] is False
