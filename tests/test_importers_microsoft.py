"""The five Microsoft adapters, from synthetic fixtures (no database needed)."""

import json
from typing import Any

import pytest

from app.importers import framework
from app.importers.base import ImportRejectedError, ParsedFact, ParseResult
from app.importers.microsoft import (
    ADAPTERS,
    ConditionalAccessAdapter,
    DirectoryRolesAdapter,
    EntraRegistrationAdapter,
    IntuneDevicesAdapter,
    SecureScoreAdapter,
    clean_version,
    count_methods,
    detect_source,
    sniff,
)
from tools import make_fixtures
from tools.make_fixtures import (
    CAPTURED_AT,
    DEVICE_NAME_PREFIX,
    DOMAIN,
    POLICY_NAMES,
    SENSITIVE_VALUES,
    Fixture,
    to_json,
)

MAX_ROWS = 1000
EVERY = [*make_fixtures.main_fixtures(), *make_fixtures.variant_fixtures()]
BY_CODE = {adapter.source_code: adapter for adapter in ADAPTERS}
ENTRA_JSON = make_fixtures.entra_registration_json()
ENTRA_CSV = make_fixtures.entra_registration_csv()
SCORE_JSON = make_fixtures.secure_score_json()
INTUNE_CSV = make_fixtures.intune_devices_csv()
INTUNE_JSON = make_fixtures.intune_devices_json()
CA_JSON = make_fixtures.conditional_access_json()
ROLES_JSON = make_fixtures.directory_roles_json()
ROLES_CSV = make_fixtures.directory_roles_csv()
CSV_FIXTURES = [ENTRA_CSV, INTUNE_CSV, ROLES_CSV]
WRONG_FILE = r"missing the (column|field) |must be a JSON file"
GOOD_TIME = "2026-10-16T08:00:00Z"


def parse(code: str, data: bytes, max_rows: int = MAX_ROWS) -> ParseResult:
    return BY_CODE[code].parse(data, max_rows)


def summary_of(result: ParseResult) -> dict[str, Any]:
    return dict(result.facts[-1].value)


def facts_with(result: ParseResult, suffix: str) -> list[ParsedFact]:
    return [fact for fact in result.facts if fact.key.endswith(suffix)]


def with_records(fixture: Fixture, change: Any) -> bytes:
    """The fixture's JSON after `change(records)` has edited its list of records."""
    root = json.loads(fixture.data)
    change(root["value"])
    return to_json(root)


def reasons(result: ParseResult) -> list[str]:
    return [str(fact.value["reason"]) for fact in facts_with(result, ".reject")]


def fixture_id(fixture: Fixture) -> str:
    return fixture.file_name


def wrong_pairs() -> list[Any]:
    pairs = []
    for adapter in ADAPTERS:
        for fixture in EVERY:
            if fixture.facts > 1 and adapter.source_code != fixture.source_code:
                name = f"{adapter.source_code}-{fixture.file_name}"
                pairs.append(pytest.param(adapter.source_code, fixture, id=name))
    return pairs


# --- every fixture ---------------------------------------------------------------


@pytest.mark.parametrize("fixture", EVERY, ids=fixture_id)
def test_each_fixture_gives_the_expected_counts_and_flags(fixture: Fixture) -> None:
    result = parse(fixture.source_code, fixture.data)
    assert len(result.facts) == fixture.facts
    assert dict(result.facts[-1].value) == fixture.expected
    if fixture.expected["capture_time_source"] == "file":
        assert result.captured_at == CAPTURED_AT
    else:
        assert result.captured_at is None


@pytest.mark.parametrize("fixture", EVERY, ids=fixture_id)
def test_nothing_personal_or_sensitive_is_ever_a_fact_value(fixture: Fixture) -> None:
    result = parse(fixture.source_code, fixture.data)
    stored = json.dumps([dict(fact.value) for fact in result.facts])
    forbidden = (*SENSITIVE_VALUES, *POLICY_NAMES, DEVICE_NAME_PREFIX, DOMAIN)
    for text in (*forbidden, "Fixture ", "@"):
        assert text not in stored
    for fact in result.facts:
        for identifier in fact.identifiers.values():
            assert identifier not in SENSITIVE_VALUES
            assert not identifier.startswith(DEVICE_NAME_PREFIX)


def test_identifiers_are_named_in_the_fact_never_in_its_value() -> None:
    entra = parse("entra-registration", ENTRA_JSON.data)
    users = {fact.identifiers["user"] for fact in facts_with(entra, ".user")}
    assert users == {f"user{number:02d}@{DOMAIN}" for number in range(1, 13)}
    intune = parse("intune-devices", INTUNE_CSV.data)
    devices = facts_with(intune, ".device")
    assert all("device" in fact.identifiers for fact in devices)
    assert sum("user" in fact.identifiers for fact in devices) == 13
    roles = parse("directory-roles", ROLES_JSON.data)
    for fact in facts_with(roles, ".assignment"):
        assert set(fact.identifiers) == {"user"}


def test_the_same_seed_gives_the_same_files_and_another_seed_other_ids() -> None:
    first = [fixture.data for fixture in make_fixtures.main_fixtures()]
    assert first == [fixture.data for fixture in make_fixtures.main_fixtures()]
    other = [fixture.data for fixture in make_fixtures.main_fixtures(seed=1)]
    assert first != other


# --- one source is never mistaken for another ---------------------------------------


@pytest.mark.parametrize(("code", "fixture"), wrong_pairs())
def test_a_file_of_another_source_is_rejected_naming_what_is_missing(
    code: str, fixture: Fixture
) -> None:
    with pytest.raises(ImportRejectedError, match=WRONG_FILE):
        parse(code, fixture.data)


@pytest.mark.parametrize("fixture", EVERY, ids=fixture_id)
def test_header_detection_finds_exactly_the_right_source(fixture: Fixture) -> None:
    # The empty policy list has no first record, so nothing can be said about it.
    empty = fixture.file_name == "conditional-access-empty.json"
    assert detect_source(fixture.data) == (None if empty else fixture.source_code)


def test_the_message_says_which_source_the_file_looks_like() -> None:
    with pytest.raises(ImportRejectedError) as wrong:
        parse("intune-devices", ENTRA_JSON.data)
    message = str(wrong.value)
    assert "missing the field complianceState, operatingSystem" in message
    assert "This looks like an Entra authentication-methods" in message
    assert "(source entra-registration)" in message
    with pytest.raises(ImportRejectedError) as csv_as_json:
        parse("conditional-access", INTUNE_CSV.data)
    message = str(csv_as_json.value)
    assert "must be a JSON file saved from Microsoft Graph" in message
    assert "(source intune-devices)" in message


def test_a_file_that_fits_two_sources_is_not_guessed() -> None:
    both = (
        "User principal name,MFA Capable,Passwordless Capable,Methods registered,"
        "Last Updated Time,Role\n"
        f"a@{DOMAIN},true,false,,{GOOD_TIME},Global Administrator\n"
    )
    assert detect_source(both.encode()) is None
    with pytest.raises(ImportRejectedError) as missing:
        parse("secure-score", both.encode())
    assert "missing the column Date, Score." in str(missing.value)
    assert "This looks like" not in str(missing.value)


@pytest.mark.parametrize(
    "data",
    [
        b"\x00\x01binary",
        b"123\n",
        b"Name,Value\nx,1\n",
        b'{"unknown": 1}',
        b'{"value": []}',
        b"[]",
        b"[1, 2]",
        b'{"value": 5}',
        b"[" * 40 + b"]" * 40,
        b"Date,Score,Date\n1,2,3\n",
    ],
)
def test_a_file_that_fits_no_source_is_not_detected(data: bytes) -> None:
    assert detect_source(data) is None


def test_a_quick_look_reads_the_header_or_the_first_record() -> None:
    assert sniff(b"A,B\n1,2\n") is not None
    looked = sniff(ENTRA_JSON.data)
    assert looked is not None
    assert looked.record is not None
    assert "userPrincipalName" in looked.record
    assert sniff(b"[1, 2]") is not None
    assert sniff(b"\x00") is None


def test_a_hint_is_left_out_when_the_quick_look_fails() -> None:
    data = json.dumps([0] * 200_001).encode()
    with pytest.raises(ImportRejectedError) as missing:
        parse("secure-score", data, max_rows=1_000_000)
    assert "missing the field currentScore" in str(missing.value)
    assert "This looks like" not in str(missing.value)


# --- hostile files, for every source ------------------------------------------------


@pytest.mark.parametrize("fixture", [ENTRA_JSON, SCORE_JSON, CA_JSON, ROLES_JSON])
def test_json_nested_too_deep_is_rejected_by_every_json_adapter(
    fixture: Fixture,
) -> None:
    deep = b'{"value": ' + b"[" * 30 + b"]" * 30 + b"}"
    with pytest.raises(ImportRejectedError, match="nested deeper than 12"):
        parse(fixture.source_code, deep)
    hostile = b"[" * 100_000 + b"]" * 100_000
    with pytest.raises(ImportRejectedError, match="nested deeper than 12"):
        parse(fixture.source_code, hostile)


@pytest.mark.parametrize("fixture", CSV_FIXTURES, ids=fixture_id)
def test_a_csv_field_larger_than_the_limit_is_rejected(fixture: Fixture) -> None:
    header, first = fixture.data.decode().split("\n")[:2]
    huge = "x" * 200_000
    data = f"{header}\n{huge},{first}\n".encode()
    with pytest.raises(ImportRejectedError, match="not a readable CSV"):
        parse(fixture.source_code, data)


@pytest.mark.parametrize("fixture", [ENTRA_JSON, SCORE_JSON, INTUNE_JSON])
def test_a_json_list_longer_than_the_row_limit_is_rejected(fixture: Fixture) -> None:
    with pytest.raises(ImportRejectedError, match="more than 5 items"):
        parse(fixture.source_code, fixture.data, max_rows=5)


@pytest.mark.parametrize("fixture", [ENTRA_CSV, INTUNE_CSV], ids=fixture_id)
def test_more_csv_rows_than_the_limit_are_rejected(fixture: Fixture) -> None:
    with pytest.raises(ImportRejectedError, match="more than 4 rows"):
        parse(fixture.source_code, fixture.data, max_rows=4)


@pytest.mark.parametrize("fixture", CSV_FIXTURES, ids=fixture_id)
def test_a_byte_order_mark_with_windows_line_ends_gives_the_same_facts(
    fixture: Fixture,
) -> None:
    crlf = b"\xef\xbb\xbf" + fixture.data.replace(b"\n", b"\r\n")
    result = parse(fixture.source_code, crlf)
    assert dict(result.facts[-1].value) == fixture.expected
    utf16 = fixture.data.decode().encode("utf-16")
    result = parse(fixture.source_code, utf16)
    assert dict(result.facts[-1].value) == fixture.expected


def test_a_file_that_is_not_text_or_not_json_is_rejected() -> None:
    for code in BY_CODE:
        with pytest.raises(ImportRejectedError, match="not readable text"):
            parse(code, b"\x00\x01\x02 binary \xff")
        with pytest.raises(ImportRejectedError, match="not valid JSON"):
            parse(code, b'{"value": [')
        with pytest.raises(ImportRejectedError, match="not valid JSON"):
            parse(code, b'{"value": [NaN]}')


def test_a_json_file_over_the_size_limit_is_rejected_by_the_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(framework, "MAX_JSON_BYTES", 50)
    with pytest.raises(ImportRejectedError, match="JSON file is larger than"):
        parse("entra-registration", ENTRA_JSON.data)


# --- Entra authentication-methods registration --------------------------------------


def test_entra_rejects_rows_one_by_one_with_the_column_named() -> None:
    def spoil(users: list[Any]) -> None:
        users[3]["isMfaCapable"] = "maybe"
        users[4]["userPrincipalName"] = " "
        users[5]["lastUpdatedDateTime"] = "last week"
        users[6]["isMfaRegistered"] = "perhaps"
        users.append("not an object")

    result = parse("entra-registration", with_records(ENTRA_JSON, spoil))
    summary = summary_of(result)
    assert (summary["users"], summary["rows_rejected"]) == (8, 5)
    assert reasons(result) == [
        "MFA Capable must be true or false",
        "User principal name is empty",
        "Last Updated Time must be an ISO 8601 date and time",
        "MFA Registered must be true or false",
        "The record is not an object",
    ]
    rejected = facts_with(result, ".reject")
    assert [fact.value["row"] for fact in rejected] == [4, 5, 6, 7, 13]


def test_entra_rejects_a_file_in_which_no_row_can_be_read() -> None:
    def spoil(users: list[Any]) -> None:
        for user in users:
            user["isMfaCapable"] = None

    data = with_records(ENTRA_JSON, spoil)
    with pytest.raises(ImportRejectedError, match="No row .* MFA Capable is empty."):
        parse("entra-registration", data)


def test_entra_accepts_an_empty_list_of_users() -> None:
    result = parse("entra-registration", to_json({"value": []}))
    summary = summary_of(result)
    assert summary["users"] == 0
    assert summary["mfa_registered_known"] is False
    assert summary["report_updated_at"] is None
    assert summary["capture_time_source"] == "upload"
    assert result.captured_at is None


def test_entra_json_without_the_graph_wrapper_is_accepted() -> None:
    users = json.loads(ENTRA_JSON.data)["value"]
    for data in (to_json(users), to_json({"value": users, "capturedAt": None})):
        result = parse("entra-registration", data)
        assert summary_of(result)["users"] == 12
        assert result.captured_at is None


def test_entra_reads_the_capture_time_from_the_file_or_flags_its_absence() -> None:
    root = json.loads(ENTRA_JSON.data)
    naive = {**root, "capturedAt": "2026-10-16T08:00:00"}
    result = parse("entra-registration", to_json(naive))
    assert result.captured_at == CAPTURED_AT
    assert summary_of(result)["timezone_assumed_utc"] is True
    del root["capturedAt"]
    result = parse("entra-registration", to_json(root))
    assert result.captured_at is None
    assert summary_of(result)["capture_time_source"] == "upload"
    root["capturedAt"] = "last Tuesday"
    with pytest.raises(ImportRejectedError, match="capturedAt is not a date"):
        parse("entra-registration", to_json(root))


def test_entra_csv_without_a_time_zone_is_assumed_utc_and_flagged() -> None:
    text = ENTRA_CSV.data.decode().replace("Z\n", "\n")
    result = parse("entra-registration", text.encode())
    assert summary_of(result)["timezone_assumed_utc"] is True
    assert summary_of(result)["users"] == 12


def test_entra_csv_with_a_bad_time_rejects_that_row_only() -> None:
    broken = ENTRA_CSV.data.decode().replace("2026-10-16T03:00:00Z", "soon", 1)
    result = parse("entra-registration", broken.encode())
    assert summary_of(result)["rows_rejected"] == 1
    assert reasons(result) == ["Last Updated Time must be an ISO 8601 date and time"]


def test_entra_csv_columns_may_be_renamed_by_a_saved_mapping() -> None:
    vendor = (
        "UPN,MFA,Passwordless,Methods,Updated\n"
        f"a@{DOMAIN},yes,no,Authenticator;Phone,{GOOD_TIME}\n"
        f"b@{DOMAIN},no,no,None,2026-10-16T09:00:00Z\n"
    )
    with pytest.raises(ImportRejectedError, match="missing the column User principal"):
        EntraRegistrationAdapter().parse(vendor.encode(), MAX_ROWS)
    mapping = {
        "UPN": "upn",
        "MFA": "mfa_capable",
        "Passwordless": "passwordless_capable",
        "Methods": "methods",
        "Updated": "updated",
    }
    adapter = EntraRegistrationAdapter().with_mapping(mapping)
    assert isinstance(adapter, EntraRegistrationAdapter)
    result = adapter.parse(vendor.encode(), MAX_ROWS)
    users = facts_with(result, ".user")
    assert [fact.value["methods"] for fact in users] == [2, 0]
    assert [fact.value["mfa_capable"] for fact in users] == [True, False]
    assert summary_of(result)["mfa_capable"] == 1
    assert summary_of(result)["report_updated_at"] == "2026-10-16T09:00:00+00:00"


def test_entra_csv_with_extra_columns_keeps_only_what_it_needs() -> None:
    lines = ENTRA_CSV.data.decode().splitlines()
    wider = [lines[0] + ",Display name,Is Admin,User type,MFA Registered"]
    for number, line in enumerate(lines[1:], start=1):
        guest = "guest" if number == 12 else "member"
        extra = f"Someone {number},{number <= 2},{guest},{number != 5}"
        wider.append(f"{line},{extra}")
    result = parse("entra-registration", ("\n".join(wider) + "\n").encode())
    summary = summary_of(result)
    assert (summary["admins"], summary["guests"]) == (2, 1)
    assert summary["mfa_registered"] == 11
    assert summary["mfa_registered_known"] is True
    assert "Someone" not in json.dumps([dict(f.value) for f in result.facts])


def test_methods_are_counted_from_a_list_or_a_text() -> None:
    assert count_methods(["a", "b", "", "none"]) == 2
    assert count_methods("a; b,c|d") == 4
    assert count_methods("None") == 0
    assert count_methods("") == 0
    assert count_methods(None) is None
    assert count_methods(5) is None


def test_entra_neutralises_formulas_and_unknown_words() -> None:
    def spoil(users: list[Any]) -> None:
        users[0]["userPrincipalName"] = "=cmd|' /C calc'!A0"
        users[0]["userType"] = "=HYPERLINK(1)"
        users[0]["methodsRegistered"] = ["=1+1", "@sum"]

    result = parse("entra-registration", with_records(ENTRA_JSON, spoil))
    first = facts_with(result, ".user")[0]
    assert first.value["user_type"] == "other"
    assert first.value["methods"] == 2
    assert first.identifiers["user"] == "=cmd|' /C calc'!A0"
    assert "=" not in json.dumps(dict(first.value))


# --- Microsoft Secure Score ---------------------------------------------------------


def test_secure_score_keeps_the_newest_reading_and_its_controls() -> None:
    result = parse("secure-score", SCORE_JSON.data)
    controls = facts_with(result, ".control")
    assert len(controls) == 12
    assert controls[0].value == {
        "name": "AdminMFAV2",
        "category": "Identity",
        "score": "10",
    }
    summary = summary_of(result)
    assert summary["current_score"] == "48.5"
    assert summary["entries"] == 3
    assert result.captured_at == CAPTURED_AT


def test_secure_score_accepts_a_single_reading_or_a_bare_list() -> None:
    readings = json.loads(SCORE_JSON.data)["value"]
    for data in (to_json(readings[1]), to_json(readings[1:])):
        result = parse("secure-score", data)
        assert summary_of(result)["current_score"] == "44"
        assert len(facts_with(result, ".control")) == 3


def test_secure_score_csv_needs_a_score_column_and_a_date_column() -> None:
    text = (
        "Date,Score,Max score\n"
        "2026-10-01,40,100\n"
        "2026-10-15T08:00:00Z,45.50,100\n"
        "2026-10-05T08:00:00Z,41,\n"
    )
    result = parse("secure-score", text.encode())
    summary = summary_of(result)
    assert summary["current_score"] == "45.5"
    assert summary["max_score"] == "100"
    assert summary["entries"] == 3
    assert summary["timezone_assumed_utc"] is True
    assert summary["controls"] == 0
    assert summary["licensed_users"] is None
    assert result.captured_at is not None
    assert result.captured_at.isoformat() == "2026-10-15T08:00:00+00:00"
    renamed = f"Created,Current score\n{GOOD_TIME},7\n"
    assert summary_of(parse("secure-score", renamed.encode()))["max_score"] is None
    with pytest.raises(ImportRejectedError, match="missing the column Score."):
        parse("secure-score", b"Date,Points\n2026-10-01,3\n")


def test_secure_score_rejects_readings_and_controls_one_by_one() -> None:
    def spoil(readings: list[Any]) -> None:
        readings[1]["currentScore"] = "plenty"
        readings[2]["maxScore"] = "lots"
        readings[2]["createdDateTime"] = "sometime"
        readings[0]["controlScores"] += [
            {"controlName": "", "score": 1},
            "not an object",
            {"controlName": "Broken", "score": "abc"},
            {"controlName": "=cmd|' /C calc'!A0", "score": 2.5},
            {"controlName": "NoCategory", "controlCategory": "  ", "score": 0},
        ]
        readings.append({"currentScore": 1, "maxScore": 5, "licensedUserCount": "x"})

    result = parse("secure-score", with_records(SCORE_JSON, spoil))
    summary = summary_of(result)
    assert summary["entries"] == 1
    assert summary["controls"] == 14
    assert summary["rows_rejected"] == 6
    assert reasons(result) == [
        "Score must be a number",
        "Date must be an ISO 8601 date and time",
        "Date is empty",
        "controlName of a controlScores entry is empty",
        "A controlScores entry is not an object",
        "score of a controlScores entry must be a number",
    ]
    controls = facts_with(result, ".control")
    assert controls[-2].value["name"] == "'=cmd|' /C calc'!A0"
    assert controls[-2].value["score"] == "2.5"
    assert controls[-1].value["category"] is None


def test_secure_score_rejects_a_bad_maximum_and_bad_counts() -> None:
    def spoil(readings: list[Any]) -> None:
        del readings[1:]
        readings.append({**readings[0], "maxScore": "lots"})
        readings.append({**readings[0], "licensedUserCount": "many"})

    result = parse("secure-score", with_records(SCORE_JSON, spoil))
    assert reasons(result) == [
        "Max score must be a number",
        "licensedUserCount must be a whole number",
    ]


def test_secure_score_reads_the_optional_counts_and_lists_defensively() -> None:
    def odd(readings: list[Any]) -> None:
        del readings[1:]
        readings[0]["enabledServices"] = "Exchange"
        readings[0]["controlScores"] = "none"
        readings[0]["maxScore"] = ""
        readings[0]["licensedUserCount"] = None

    summary = summary_of(parse("secure-score", with_records(SCORE_JSON, odd)))
    assert summary["services"] is None
    assert summary["controls"] == 0
    assert summary["max_score"] is None
    assert summary["licensed_users"] is None


def test_secure_score_with_no_reading_is_valid_and_has_no_capture_time() -> None:
    for data in (to_json({"value": []}), b"Date,Score\n"):
        result = parse("secure-score", data)
        assert summary_of(result) == {
            "entries": 0,
            "rows_rejected": 0,
            "capture_time_source": "upload",
            "timezone_assumed_utc": False,
        }
        assert result.captured_at is None


def test_secure_score_with_no_readable_reading_is_rejected() -> None:
    reading = {"currentScore": "x", "maxScore": 1, "createdDateTime": "x"}
    with pytest.raises(ImportRejectedError, match="No row .* could be read"):
        parse("secure-score", to_json({"value": [reading]}))


# --- Intune devices -----------------------------------------------------------------


def intune_csv(*rows: str, header: str | None = None) -> bytes:
    head = header or "DeviceId,complianceState,OS,LastContact"
    return ("\n".join([head, *rows]) + "\n").encode()


def test_intune_rejects_rows_one_by_one() -> None:
    data = intune_csv(
        f"d1,compliant,Windows,{GOOD_TIME}",
        f",compliant,Windows,{GOOD_TIME}",
        f"d3,,Windows,{GOOD_TIME}",
        f"d4,compliant,,{GOOD_TIME}",
        "d5,compliant,Windows,",
        "d6,compliant,Windows,yesterday",
    )
    result = parse("intune-devices", data)
    assert summary_of(result)["devices"] == 1
    assert reasons(result) == [
        "DeviceId is empty",
        "ComplianceState is empty",
        "OS is empty",
        "LastContact is empty",
        "LastContact must be an ISO 8601 date and time",
    ]


def test_intune_csv_with_nothing_readable_is_rejected() -> None:
    data = intune_csv(f",compliant,Windows,{GOOD_TIME}")
    with pytest.raises(ImportRejectedError, match="No row .* DeviceId is empty."):
        parse("intune-devices", data)


def test_intune_localised_column_names_are_understood() -> None:
    header = "DeviceId_loc,ComplianceState_loc,OS_loc,LastContact_loc"
    data = intune_csv(f"d1,compliant,Windows,{GOOD_TIME}", header=header)
    assert summary_of(parse("intune-devices", data))["compliant"] == 1


def test_intune_says_whether_sensitive_columns_were_present() -> None:
    clean = intune_csv(f"d1,compliant,Windows,{GOOD_TIME}")
    summary = summary_of(parse("intune-devices", clean))
    assert summary["sensitive_fields_dropped"] is False
    header = "DeviceId,complianceState,OS,LastContact,Phone number"
    phone = intune_csv(f"d1,compliant,Windows,{GOOD_TIME},+1", header=header)
    summary = summary_of(parse("intune-devices", phone))
    assert summary["sensitive_fields_dropped"] is True
    graph = to_json({"value": [{"id": "1", "complianceState": "compliant"}]})
    with pytest.raises(ImportRejectedError, match="missing the field operatingSystem"):
        parse("intune-devices", graph)


def test_intune_keeps_only_words_from_fixed_lists_and_clean_versions() -> None:
    columns = ["DeviceId", "complianceState", "OS", "LastContact", "OSVersion"]
    header = ",".join([*columns, "managementAgent", "ownerType"])
    padding = "y" * 80
    hostile = f"d1,=cmd,=cmd|calc,{GOOD_TIME},=1+1,=HYPERLINK(x) {padding},=x"
    normal = f"d2,Compliant,iOS/iPadOS,{GOOD_TIME},17.5.1,mdm,Personal"
    data = intune_csv(hostile, normal, header=header)
    first, second = facts_with(parse("intune-devices", data), ".device")
    assert first.value["compliance"] == "other"
    assert first.value["os"] == "other"
    assert first.value["os_version"] is None
    assert first.value["owner"] == "other"
    management = first.value["management"]
    assert isinstance(management, str)
    assert len(management) == 40
    assert management.isalnum()
    assert second.value["compliance"] == "compliant"
    assert second.value["os"] == "ios"
    assert second.value["os_version"] == "17.5.1"
    assert second.value["owner"] == "personal"


def test_clean_version_accepts_dotted_numbers_only() -> None:
    assert clean_version("10.0.22631") == "10.0.22631"
    assert clean_version("17") == "17"
    assert clean_version(None) is None
    assert clean_version("1.2.3.4.5.6") is None
    assert clean_version("10.0.x") is None
    assert clean_version("1" * 41) is None


def test_intune_json_reads_the_encryption_flag() -> None:
    def spoil(devices: list[Any]) -> None:
        devices[0]["isEncrypted"] = "unsure"
        del devices[1]["isEncrypted"]
        devices.append(7)

    result = parse("intune-devices", with_records(INTUNE_JSON, spoil))
    summary = summary_of(result)
    assert summary["encryption_known"] == 4
    assert summary["encrypted"] == 3
    assert summary["rows_rejected"] == 2
    assert reasons(result) == [
        "IsEncrypted must be true or false",
        "The record is not an object",
    ]


# --- Conditional Access -------------------------------------------------------------


def test_conditional_access_policies_become_flags_never_names() -> None:
    result = parse("conditional-access", CA_JSON.data)
    policies = [dict(fact.value) for fact in facts_with(result, ".policy")]
    assert policies[0] == {
        "state": "enabled",
        "all_users": True,
        "all_apps": True,
        "requires_mfa": True,
        "blocks": False,
        "targets_roles": False,
        "exclusions": 1,
        "legacy_clients": False,
        "modified": "2026-09-30T09:00:00+00:00",
    }
    assert policies[1]["blocks"] is True
    assert policies[1]["legacy_clients"] is True
    assert policies[1]["exclusions"] == 0
    assert policies[2]["state"] == "report-only"
    assert policies[3]["state"] == "disabled"
    assert policies[3]["targets_roles"] is True
    assert policies[3]["all_users"] is False
    assert policies[4]["all_apps"] is False
    assert policies[4]["requires_mfa"] is False
    assert policies[4]["all_users"] is False


def test_conditional_access_empty_list_is_the_state_security_defaults() -> None:
    summary = summary_of(parse("conditional-access", to_json({"value": []})))
    assert summary["tenant_state"] == "security-defaults"
    assert summary["policies"] == 0


def test_conditional_access_rejects_records_one_by_one() -> None:
    def spoil(policies: list[Any]) -> None:
        policies.append("text")
        policies.append({"state": " ", "conditions": {}})
        policies.append({"state": "enabled", "conditions": "none"})
        policies.append({"state": "enabled", "conditions": {}, "modifiedDateTime": "x"})
        policies.append({"state": "weird", "conditions": {}})

    result = parse("conditional-access", with_records(CA_JSON, spoil))
    summary = summary_of(result)
    assert summary["policies"] == 6
    assert summary["rows_rejected"] == 4
    assert reasons(result) == [
        "The record is not an object",
        "state is empty",
        "conditions must be an object",
        "modifiedDateTime must be an ISO 8601 date and time",
    ]
    assert facts_with(result, ".policy")[-1].value["state"] == "other"


def test_conditional_access_with_no_readable_record_is_rejected() -> None:
    data = to_json({"value": [{"state": "enabled", "conditions": 3}]})
    with pytest.raises(ImportRejectedError, match="No row .* conditions must be"):
        parse("conditional-access", data)


def test_conditional_access_reads_the_capture_time_of_the_file() -> None:
    root = json.loads(CA_JSON.data)
    root["capturedAt"] = GOOD_TIME
    result = parse("conditional-access", to_json(root))
    assert result.captured_at == CAPTURED_AT
    assert summary_of(result)["capture_time_source"] == "file"


def test_conditional_access_is_a_json_only_source() -> None:
    adapter = ConditionalAccessAdapter()
    assert adapter.columns == ()
    with pytest.raises(ImportRejectedError, match="must be a JSON file"):
        adapter.parse(b"state,conditions\nenabled,x\n", MAX_ROWS)


# --- Directory roles ----------------------------------------------------------------


def test_directory_roles_json_lists_who_holds_which_role() -> None:
    result = parse("directory-roles", ROLES_JSON.data)
    assignments = facts_with(result, ".assignment")
    assert [(f.value["role"], f.value["enabled"]) for f in assignments] == [
        ("Global Administrator", True),
        ("Global Administrator", True),
        ("Exchange Administrator", True),
        ("Exchange Administrator", False),
    ]
    assert [f.value["global_admin"] for f in assignments] == [True, True, False, False]
    assert all(f.value["permanent"] is None for f in assignments)


def test_directory_roles_json_rejects_roles_and_members_one_by_one() -> None:
    def spoil(roles: list[Any]) -> None:
        bad_flag = {"userPrincipalName": "a@x.test", "accountEnabled": "?"}
        members = [
            {"userPrincipalName": "USER01@" + DOMAIN},
            {"userPrincipalName": "someone@x.test"},
            "not an object",
        ]
        roles.append("text")
        roles.append({"displayName": " ", "members": []})
        roles.append({"displayName": "Broken", "members": "none"})
        roles.append({"displayName": "Bad flag", "members": [bad_flag]})
        roles.append({"displayName": "Company Administrator", "members": members})

    result = parse("directory-roles", with_records(ROLES_JSON, spoil))
    summary = summary_of(result)
    assert summary["rows_rejected"] == 4
    assert reasons(result) == [
        "The record is not an object",
        "displayName is empty",
        "members must be a list",
        "accountEnabled must be true or false",
    ]
    assert summary["non_user_members"] == 2
    assert summary["roles"] == 3
    assert summary["users"] == 4
    assert summary["global_admins"] == 3


def test_directory_roles_json_with_nothing_readable_is_rejected() -> None:
    data = to_json({"value": [{"displayName": "", "members": []}]})
    with pytest.raises(ImportRejectedError, match="No row .* displayName is empty."):
        parse("directory-roles", data)


def test_directory_roles_json_with_no_roles_is_valid() -> None:
    summary = summary_of(parse("directory-roles", to_json({"value": []})))
    assert summary["assignments"] == 0
    assert summary["input_format"] == "graph-json"


def test_directory_roles_csv_rejects_rows_one_by_one() -> None:
    text = (
        "User principal name,Role,Enabled,Permanent\n"
        f"a@{DOMAIN},Global Administrator,true,true\n"
        ",Global Administrator,true,true\n"
        f"c@{DOMAIN},,true,true\n"
        f"d@{DOMAIN},User Administrator,maybe,true\n"
        f"e@{DOMAIN},User Administrator,,\n"
    )
    result = parse("directory-roles", text.encode())
    summary = summary_of(result)
    assert (summary["assignments"], summary["rows_rejected"]) == (2, 3)
    assert reasons(result) == [
        "User principal name is empty",
        "Role is empty",
        "Enabled must be true or false",
    ]
    assert summary["input_format"] == "manual-csv"


def test_directory_roles_csv_accepts_alternative_column_names() -> None:
    text = f"User principal name,Role name,accountEnabled\na@{DOMAIN},Helpdesk,yes\n"
    result = parse("directory-roles", text.encode())
    assert facts_with(result, ".assignment")[0].value["enabled"] is True


# --- saved mappings and the adapter list ---------------------------------------------


def test_a_mapping_gives_a_new_adapter_of_the_same_kind() -> None:
    for adapter in ADAPTERS:
        mapped = adapter.with_mapping({"x": "y"})
        assert type(mapped) is type(adapter)
        assert mapped is not adapter
        assert mapped.mapping == {"x": "y"}
        assert adapter.mapping == {}


def test_every_adapter_names_a_source_and_a_version() -> None:
    codes = [adapter.source_code for adapter in ADAPTERS]
    assert sorted(codes) == [
        "conditional-access",
        "directory-roles",
        "entra-registration",
        "intune-devices",
        "secure-score",
    ]
    for adapter in ADAPTERS:
        assert adapter.version.startswith(adapter.source_code)


def test_the_required_csv_columns_are_the_documented_ones() -> None:
    def required(adapter: Any) -> set[str]:
        return {column.key for column in adapter.columns if column.required}

    assert required(IntuneDevicesAdapter) == {
        "device_id",
        "compliance",
        "os",
        "last_contact",
    }
    assert required(SecureScoreAdapter) == {"date", "score"}
    assert required(DirectoryRolesAdapter) == {"upn", "role"}
    assert required(EntraRegistrationAdapter) == {
        "upn",
        "mfa_capable",
        "passwordless_capable",
        "methods",
        "updated",
    }
