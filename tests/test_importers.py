"""The importer contract, the registry and the reference importer."""

import pytest

from app.importers.base import ImportRejectedError, ParseResult
from app.importers.reference import ReferenceCsvImporter
from app.importers.registry import ImporterRegistry, build_default_registry

MAX_ROWS = 100
HEADER = "user_principal_name,mfa_registered"
SOURCES = [
    "backup-export",
    "conditional-access",
    "device-inventory",
    "directory-roles",
    "entra-registration",
    "exchange-export",
    "intune-devices",
    "leavers-csv",
    "network-export",
    "reference-csv",
    "secure-score",
    "training-csv",
]


def parse(text: str | bytes, max_rows: int = MAX_ROWS) -> ParseResult:
    data = text if isinstance(text, bytes) else text.encode("utf-8")
    return ReferenceCsvImporter().parse(data, max_rows)


def test_a_valid_file_gives_one_fact_per_user_and_a_summary() -> None:
    result = parse(f"{HEADER}\na@example.test,true\nb@example.test,No\n")
    assert [fact.key for fact in result.facts] == [
        "reference.user",
        "reference.user",
        "reference.summary",
    ]
    first, second, summary = result.facts
    assert first.value == {"mfa_registered": True}
    assert first.identifiers == {"user": "a@example.test"}
    assert second.value == {"mfa_registered": False}
    assert summary.value == {"users": 2, "mfa_registered": 1}
    assert summary.identifiers == {}
    assert result.captured_at is None


def test_no_fact_value_holds_the_user_name() -> None:
    result = parse(f"{HEADER}\na@example.test,true\n")
    assert all("a@example.test" not in str(fact.value) for fact in result.facts)


def test_a_byte_order_mark_and_windows_line_ends_are_accepted() -> None:
    text = f"﻿{HEADER}\r\na@example.test,1\r\nb@example.test,0\r\n"
    summary = parse(text.encode("utf-8")).facts[-1]
    assert summary.value == {"users": 2, "mfa_registered": 1}


def test_an_empty_list_of_users_is_a_valid_file() -> None:
    assert parse(HEADER + "\n").facts[-1].value == {"users": 0, "mfa_registered": 0}


@pytest.mark.parametrize(
    ("text", "missing"),
    [
        ("name,flag\na,b\n", "user_principal_name, mfa_registered"),
        ("user_principal_name\na@example.test\n", "mfa_registered"),
        ("mfa_registered\ntrue\n", "user_principal_name"),
        ("", "user_principal_name, mfa_registered"),
    ],
)
def test_a_file_without_the_columns_is_rejected_naming_them(
    text: str, missing: str
) -> None:
    with pytest.raises(ImportRejectedError, match=f"missing the column {missing}"):
        parse(text)


def test_a_row_without_a_user_is_rejected_with_its_number() -> None:
    with pytest.raises(ImportRejectedError, match="Row 2 has no user_principal_name"):
        parse(f"{HEADER}\na@example.test,true\n,true\n")


def test_a_flag_that_is_not_true_or_false_is_rejected_with_the_row() -> None:
    with pytest.raises(ImportRejectedError, match="Row 1: mfa_registered must be"):
        parse(f"{HEADER}\na@example.test,maybe\n")


def test_a_row_with_a_missing_flag_is_rejected() -> None:
    with pytest.raises(ImportRejectedError, match="Row 1: mfa_registered must be"):
        parse(f"{HEADER}\na@example.test\n")


def test_more_rows_than_the_limit_are_rejected() -> None:
    rows = "".join(f"u{number}@example.test,true\n" for number in range(4))
    with pytest.raises(ImportRejectedError, match="more than 3 rows"):
        parse(f"{HEADER}\n{rows}", max_rows=3)
    assert parse(f"{HEADER}\n{rows}", max_rows=4).facts[-1].value["users"] == 4


def test_bytes_that_are_not_utf8_are_rejected() -> None:
    with pytest.raises(ImportRejectedError, match="not UTF-8 text"):
        parse(b"\xff\xfe\x00\x01 binary")


def test_a_field_larger_than_the_csv_limit_is_rejected() -> None:
    huge = "x" * 200_000
    with pytest.raises(ImportRejectedError, match="not a readable CSV"):
        parse(f"{HEADER}\n{huge},true\n")


def test_a_formula_in_a_user_field_is_only_ever_an_identifier() -> None:
    result = parse(f"{HEADER}\n=cmd|' /C calc'!A0,true\n")
    assert result.facts[0].value == {"mfa_registered": True}


def test_the_registry_finds_the_reference_and_the_microsoft_importers() -> None:
    registry = build_default_registry()
    assert registry.source_codes() == SOURCES
    found = registry.get("reference-csv")
    assert found is not None
    assert found.version == "reference-1"
    microsoft = registry.get("entra-registration")
    assert microsoft is not None
    assert microsoft.version == "entra-registration-1"
    assert registry.get("unknown-source") is None


def test_the_registry_refuses_a_second_importer_for_the_same_source() -> None:
    registry = ImporterRegistry()
    registry.register(ReferenceCsvImporter())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(ReferenceCsvImporter())


def test_the_registry_refuses_an_invalid_source_code() -> None:
    class BadImporter:
        source_code = "Not Valid"
        version = "1"

        def parse(self, data: bytes, max_rows: int) -> ParseResult:
            return ParseResult(facts=())

    with pytest.raises(ValueError, match="not a valid source code"):
        ImporterRegistry().register(BadImporter())
