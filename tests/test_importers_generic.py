"""The six generic and administrative adapters, from synthetic fixtures."""

import csv
import io
import json
from pathlib import Path
from typing import Any

import pytest

from app.evidence.service import EMAIL_LIKE as store_pattern
from app.importers.base import ImportRejectedError, ParsedFact, ParseResult
from app.importers.framework import EMAIL_LIKE, Flags, RowError, safe_text
from app.importers.generic import ADAPTERS, CsvAdapter, read_port_cell
from app.importers.microsoft import DirectoryRolesAdapter, SecureScoreAdapter
from tools import make_generic_fixtures
from tools.make_fixtures import CAPTURED_AT, DOMAIN, Fixture, to_csv, user_name
from tools.make_generic_fixtures import MAIL_DOMAINS, UNREAD_VALUES

MAX_ROWS = 1000
EVERY = make_generic_fixtures.generic_fixtures()
BY_CODE = {adapter.source_code: adapter for adapter in ADAPTERS}
BY_FILE = {fixture.file_name: fixture for fixture in EVERY}
DEVICES = BY_FILE["device-inventory.csv"]
NETWORK = BY_FILE["network-export.csv"]
EXCHANGE = BY_FILE["exchange-export.csv"]
MISSING = "missing the column "
DEVICE_HEADER = [
    "hostname",
    "os",
    "last_seen",
    "patch_status",
    "pending_critical_updates",
    "av_product",
    "av_status",
    "av_signature_date",
    "disk_encrypted",
]
GOOD_DEVICE = [
    "host-1",
    "Windows 11",
    "2026-10-16T08:00:00Z",
    "up_to_date",
    "0",
    "Synthetic Shield",
    "protected",
    "2026-10-15T08:00:00Z",
    "true",
]
FORMULA = '=HYPERLINK("http://x.invalid")'


def parse(code: str, data: bytes, max_rows: int = MAX_ROWS) -> ParseResult:
    return BY_CODE[code].parse(data, max_rows)


def summary_of(result: ParseResult) -> dict[str, Any]:
    return dict(result.facts[-1].value)


def facts_with(result: ParseResult, suffix: str) -> list[ParsedFact]:
    return [fact for fact in result.facts if fact.key.endswith(suffix)]


def reasons(result: ParseResult) -> list[str]:
    return [str(fact.value["reason"]) for fact in facts_with(result, ".reject")]


def identifier_names(result: ParseResult, suffix: str) -> list[set[str]]:
    return [set(fact.identifiers) for fact in facts_with(result, suffix)]


def devices(*rows: list[str]) -> bytes:
    return to_csv(DEVICE_HEADER, list(rows))


def with_cell(row: list[str], name: str, value: str) -> list[str]:
    changed = list(row)
    changed[DEVICE_HEADER.index(name)] = value
    return changed


def table_of(data: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(data.decode("utf-8"))))


def render(rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    return buffer.getvalue().encode("utf-8")


def without_column(data: bytes, name: str) -> bytes:
    rows = table_of(data)
    index = rows[0].index(name)
    return render([[c for i, c in enumerate(row) if i != index] for row in rows])


def mail(number: int) -> str:
    return f"mail{number}.{DOMAIN}"


def fixture_id(fixture: Fixture) -> str:
    return fixture.file_name


def required_columns() -> list[Any]:
    found = []
    for fixture in EVERY:
        for column in BY_CODE[fixture.source_code].columns:
            if column.required:
                name = f"{fixture.source_code}-{column.key}"
                found.append(pytest.param(fixture, column.key, column.label, id=name))
    return found


def wrong_pairs() -> list[Any]:
    pairs = []
    for fixture in EVERY:
        for adapter in ADAPTERS:
            if adapter.source_code != fixture.source_code:
                name = f"{adapter.source_code}-{fixture.file_name}"
                pairs.append(pytest.param(adapter.source_code, fixture, id=name))
    return pairs


# --- every fixture -----------------------------------------------------------------


@pytest.mark.parametrize("fixture", EVERY, ids=fixture_id)
def test_each_fixture_gives_the_expected_counts_and_flags(fixture: Fixture) -> None:
    result = parse(fixture.source_code, fixture.data)
    assert len(result.facts) == fixture.facts
    assert summary_of(result) == fixture.expected
    assert result.captured_at is None


@pytest.mark.parametrize("fixture", EVERY, ids=fixture_id)
def test_nothing_personal_or_free_text_is_ever_a_fact_value(fixture: Fixture) -> None:
    result = parse(fixture.source_code, fixture.data)
    stored = json.dumps([dict(fact.value) for fact in result.facts])
    for text in (*UNREAD_VALUES, "@", "Fixture "):
        assert text not in stored


def test_identifiers_are_named_in_the_fact_never_in_its_value() -> None:
    inventory = parse("device-inventory", DEVICES.data)
    names = identifier_names(inventory, ".device")
    assert all("device" in found for found in names)
    assert sum("user" in found for found in names) == 7
    backup = parse("backup-export", BY_FILE["backup-export.csv"].data)
    assert identifier_names(backup, ".job") == [{"asset", "job"}] * 8
    network = parse("network-export", NETWORK.data)
    assert identifier_names(network, ".device") == [{"device"}] * 2
    assert identifier_names(network, ".rule") == [set()] * 4
    assert identifier_names(network, ".ssid") == [{"ssid"}] * 3
    exchange = parse("exchange-export", EXCHANGE.data)
    domains = {f.identifiers["domain"] for f in facts_with(exchange, ".dkim")}
    assert domains == set(MAIL_DOMAINS)
    assert len(facts_with(exchange, ".mailbox")) == 3
    training = parse("training-csv", BY_FILE["training.csv"].data)
    assert all("user" in f.identifiers for f in facts_with(training, ".completion"))
    leavers = parse("leavers-csv", BY_FILE["leavers.csv"].data)
    people = {f.identifiers["user"] for f in facts_with(leavers, ".leaver")}
    assert people == {user_name(number) for number in (6, 7, 8)}


def test_the_same_seed_gives_the_same_files_and_another_seed_other_serials() -> None:
    first = [fixture.data for fixture in make_generic_fixtures.generic_fixtures()]
    again = make_generic_fixtures.generic_fixtures()
    assert first == [fixture.data for fixture in again]
    other = make_generic_fixtures.generic_fixtures(seed=1)
    assert first != [fixture.data for fixture in other]
    assert [f.expected for f in other] == [f.expected for f in EVERY]


def test_the_six_files_and_a_manifest_are_written(tmp_path: Path) -> None:
    manifest = make_generic_fixtures.write_generic(tmp_path)
    written = {path.name for path in tmp_path.iterdir()}
    assert written == {*(fixture.file_name for fixture in EVERY), "manifest.json"}
    assert set(manifest["files"]) == set(BY_FILE)
    on_disk = json.loads((tmp_path / "manifest.json").read_text())
    assert on_disk == manifest
    assert on_disk["unread_values"] == list(UNREAD_VALUES)
    for fixture in EVERY:
        assert (tmp_path / fixture.file_name).read_bytes() == fixture.data
        entry = on_disk["files"][fixture.file_name]
        assert entry["source_code"] == fixture.source_code
        assert entry["facts"] == fixture.facts
        assert entry["expected"] == fixture.expected


def test_the_command_line_writes_the_set_with_a_seed(tmp_path: Path) -> None:
    for name in ("one", "two"):
        argument = str(tmp_path / name)
        assert make_generic_fixtures.main([argument, "--seed", "7"]) == 0
    manifest = json.loads((tmp_path / "one" / "manifest.json").read_text())
    assert manifest["seed"] == 7
    for name in (*BY_FILE, "manifest.json"):
        first = (tmp_path / "one" / name).read_bytes()
        assert first == (tmp_path / "two" / name).read_bytes()


def test_every_synthetic_address_uses_the_reserved_domain() -> None:
    for fixture in EVERY:
        words = fixture.data.decode().replace('"', " ").replace(",", " ").split()
        for word in words:
            if "@" in word and not word.startswith("@"):
                assert word.split("@")[1] == DOMAIN


# --- a wrong or incomplete file -------------------------------------------------------


@pytest.mark.parametrize(("fixture", "key", "label"), required_columns())
def test_a_missing_required_column_rejects_the_file_naming_the_column(
    fixture: Fixture, key: str, label: str
) -> None:
    broken = without_column(fixture.data, key)
    with pytest.raises(ImportRejectedError, match=f"missing the column {label}\\."):
        parse(fixture.source_code, broken)


def test_a_device_file_needs_a_hostname_or_a_device_id() -> None:
    broken = without_column(DEVICES.data, "hostname")
    with pytest.raises(ImportRejectedError, match="column device_id or hostname"):
        parse("device-inventory", broken)
    with_id = table_of(DEVICES.data)
    with_id[0][0] = "device_id"
    assert summary_of(parse("device-inventory", render(with_id)))["devices"] == 10


def test_a_network_file_needs_a_device_a_rule_or_a_network() -> None:
    data = to_csv(["record_type", "perimeter"], [["device", "true"]])
    with pytest.raises(ImportRejectedError, match="device_id or rule_enabled or ssid"):
        parse("network-export", data)


@pytest.mark.parametrize(("code", "fixture"), wrong_pairs())
def test_a_file_of_another_source_is_rejected(code: str, fixture: Fixture) -> None:
    with pytest.raises(ImportRejectedError):
        parse(code, fixture.data)


def test_a_file_in_which_no_row_can_be_read_is_rejected() -> None:
    data = devices(with_cell(GOOD_DEVICE, "hostname", ""))
    with pytest.raises(ImportRejectedError, match="No row of the file could be read"):
        parse("device-inventory", data)


def test_a_header_only_file_is_valid_and_empty() -> None:
    result = parse("device-inventory", devices())
    assert summary_of(result)["devices"] == 0
    assert summary_of(result)["last_seen_newest"] is None
    assert len(result.facts) == 1


def test_an_empty_file_and_too_many_rows_are_rejected() -> None:
    with pytest.raises(ImportRejectedError, match="The file is empty"):
        parse("training-csv", b"\n\n")
    with pytest.raises(ImportRejectedError, match="more than 3 rows"):
        parse("training-csv", BY_FILE["training.csv"].data, max_rows=3)


# --- bad rows -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (("hostname", ""), "device_id or hostname is empty"),
        (("os", ""), "os is empty"),
        (("last_seen", ""), "last_seen is empty"),
        (("last_seen", "yesterday"), "last_seen must be an ISO 8601 date and time"),
        (("disk_encrypted", "maybe"), "disk_encrypted must be true or false"),
        (("pending_critical_updates", "-1"), "must be a whole number"),
        (("pending_critical_updates", "1.5"), "must be a whole number"),
        (("pending_critical_updates", "1e-999990"), "must be a whole number"),
        (("pending_critical_updates", "9" * 40), "must be a whole number"),
        (("av_product", "someone@example.test"), "must not contain an email address"),
        (("hostname", "h" * 201), "hostname is too long"),
    ],
)
def test_a_row_that_cannot_be_read_is_rejected_and_the_rest_is_kept(
    change: tuple[str, str], reason: str
) -> None:
    other = with_cell(GOOD_DEVICE, "hostname", "host-2")
    bad = with_cell(GOOD_DEVICE, *change)
    result = parse("device-inventory", devices(GOOD_DEVICE, bad, other))
    summary = summary_of(result)
    assert (summary["devices"], summary["rows_rejected"]) == (2, 1)
    (found,) = reasons(result)
    assert reason in found
    assert not change[1] or change[1] not in found
    assert facts_with(result, ".reject")[0].value["row"] == 2


def test_an_unknown_word_of_a_fixed_list_becomes_other_not_free_text() -> None:
    odd = with_cell(GOOD_DEVICE, "av_status", "Custom vendor status")
    stored = parse("device-inventory", devices(odd)).facts[0].value
    assert stored["av_status"] == "other"
    assert "Custom" not in json.dumps(dict(stored))


def test_a_reason_never_repeats_what_the_file_said() -> None:
    secret = "SECRET-CELL-CONTENT"
    odd = with_cell(GOOD_DEVICE, "last_seen", secret)
    result = parse("device-inventory", devices(GOOD_DEVICE, odd))
    assert secret not in json.dumps(reasons(result))


# --- hostile files --------------------------------------------------------------------


def test_a_formula_cell_is_neutralised() -> None:
    row = with_cell(GOOD_DEVICE, "av_product", FORMULA)
    stored = parse("device-inventory", devices(row)).facts[0].value
    assert stored["av_product"] == "'" + FORMULA
    course = to_csv(
        ["user_id", "course", "completed_utc"],
        [[user_name(1), "+cmd|' /C calc'!A0", "2026-10-01T00:00:00Z"]],
    )
    kept = parse("training-csv", course).facts[0].value
    assert str(kept["course"]).startswith("'+")


def test_a_field_above_the_csv_limit_is_rejected_not_an_exception() -> None:
    header = ",".join(DEVICE_HEADER).encode()
    huge = header + b"\n" + b"x" * 200_000 + b",Windows\n"
    with pytest.raises(ImportRejectedError, match="not a readable CSV"):
        parse("device-inventory", huge)


def test_json_is_refused_whatever_its_shape() -> None:
    deep = json.dumps({"value": []})
    for _ in range(40):
        deep = f'{{"value": [{deep}]}}'
    for code in BY_CODE:
        for data in (deep.encode(), b'[{"hostname": "x"}]', b'{"value": []}'):
            with pytest.raises(ImportRejectedError, match="must be a CSV file"):
                parse(code, data)


def test_binary_data_is_refused() -> None:
    with pytest.raises(ImportRejectedError, match="not readable text"):
        parse("leavers-csv", b"user_id,leave_date\n\x00\x01,2026-01-01\n")


def test_a_byte_order_mark_and_windows_line_ends_are_accepted() -> None:
    data = (
        b"\xef\xbb\xbfuser_id,leave_date\r\n"
        + f"{user_name(1)},2026-09-01T00:00:00Z\r\n".encode()
        + f"{user_name(2)},2026-09-02T00:00:00Z\r\n".encode()
    )
    assert summary_of(parse("leavers-csv", data))["leavers"] == 2


def test_a_utf16_file_is_read() -> None:
    text = f"user_id,leave_date\n{user_name(1)},2026-09-01T00:00:00Z\n"
    result = parse("leavers-csv", b"\xff\xfe" + text.encode("utf-16-le"))
    assert summary_of(result)["leavers"] == 1


def test_tiny_decimals_and_long_digit_strings_never_raise() -> None:
    cells = ["1e-999999", "0.0000001", "1" * 5000, "9" * 19, "1e999", "nan"]
    rows = [with_cell(GOOD_DEVICE, "pending_critical_updates", c) for c in cells]
    result = parse("device-inventory", devices(GOOD_DEVICE, *rows))
    summary = summary_of(result)
    assert (summary["devices"], summary["rows_rejected"]) == (1, 6)
    assert len(reasons(result)) == 6


def test_an_email_like_text_is_a_row_error_not_a_refused_upload() -> None:
    good = with_cell(GOOD_DEVICE, "hostname", "host-2")
    leaky = with_cell(GOOD_DEVICE, "av_product", f"contact me at ops@{DOMAIN}")
    result = parse("device-inventory", devices(good, leaky))
    assert summary_of(result)["devices"] == 1
    assert reasons(result) == ["av_product must not contain an email address"]
    assert DOMAIN not in json.dumps([dict(fact.value) for fact in result.facts])


def test_the_microsoft_adapters_reject_the_row_for_an_email_like_text_too() -> None:
    roles = (
        "User principal name,Role\n"
        f"{user_name(1)},Global Administrator\n"
        f"{user_name(2)},admin@{DOMAIN}\n"
    ).encode()
    result = DirectoryRolesAdapter().parse(roles, MAX_ROWS)
    summary = summary_of(result)
    assert (summary["assignments"], summary["rows_rejected"]) == (1, 1)
    assert reasons(result) == ["A text field must not contain an email address"]
    controls = [
        {"controlName": "AdminMFAV2", "score": 3},
        {"controlName": f"mail {user_name(1)}", "score": 2},
        {"controlName": "Other", "controlCategory": f"a@{DOMAIN}", "score": 1},
    ]
    entry = {
        "createdDateTime": "2026-10-16T08:00:00Z",
        "currentScore": 10,
        "maxScore": 100,
        "controlScores": controls,
    }
    data = json.dumps({"value": [entry]}).encode()
    scored = summary_of(SecureScoreAdapter().parse(data, MAX_ROWS))
    assert (scored["controls"], scored["rows_rejected"]) == (1, 2)


def test_the_importers_and_the_store_agree_on_what_an_email_address_is() -> None:
    assert EMAIL_LIKE.pattern == store_pattern.pattern


def test_safe_text_names_the_field_and_leaves_other_at_signs_alone() -> None:
    with pytest.raises(RowError, match="Role must not contain an email address"):
        safe_text("who@example.test", label="Role")
    with pytest.raises(RowError, match="A text field must not contain"):
        safe_text("who@example.test")
    assert safe_text("@home") == "'@home"
    assert safe_text("price @ 5") == "price @ 5"


def test_safe_text_checks_the_text_as_stored_after_the_formula_prefix() -> None:
    with pytest.raises(RowError, match="Course must not contain an email address"):
        safe_text("@acme.com", label="Course")
    stored = safe_text("@acme")
    assert stored == "'@acme"
    assert not EMAIL_LIKE.search(stored)
    assert not store_pattern.search(safe_text("=1+1"))


def test_a_text_starting_with_an_at_sign_and_a_dot_rejects_only_its_row() -> None:
    bad = with_cell(GOOD_DEVICE, "av_product", "@acme.com")
    good = with_cell(GOOD_DEVICE, "hostname", "host-2")
    result = parse("device-inventory", devices(GOOD_DEVICE, bad, good))
    summary = summary_of(result)
    assert (summary["devices"], summary["rows_rejected"]) == (2, 1)
    assert reasons(result) == ["av_product must not contain an email address"]
    for fact in result.facts:
        assert not any(
            isinstance(item, str) and store_pattern.search(item)
            for item in fact.value.values()
        )


def test_width_variants_of_one_user_or_asset_are_counted_once() -> None:
    plain, wide = "alice@x.invalid", "ａlice@x.invalid"
    when = "2026-10-16T08:00:00Z"
    people = [plain, wide, " ALICE@x.invalid"]
    training = to_csv(
        ["user_id", "course", "completed_utc"],
        [[person, "Phishing", when] for person in people],
    )
    assert summary_of(parse("training-csv", training))["users"] == 1
    leavers = to_csv(["user_id", "leave_date"], [[plain, when], [wide, when]])
    assert summary_of(parse("leavers-csv", leavers))["users"] == 1
    header = [
        "system_or_device",
        "backup_job",
        "last_success",
        "last_result",
        "retention_days",
        "restore_test_date",
    ]
    systems = ["srv-1", "ｓrv-1"]
    rows = [[name, "job", when, "success", "30", when] for name in systems]
    assert summary_of(parse("backup-export", to_csv(header, rows)))["assets"] == 1


def test_common_direction_and_action_words_make_an_open_inbound_allow_rule() -> None:
    header = ["record_type", "rule_enabled", "direction", "action", "source", "port"]
    rows = [
        ["rule", "true", "Ingress", "Accept", "Anywhere", "443"],
        ["rule", "true", "Incoming", "Accept", "any", "anywhere"],
    ]
    summary = summary_of(parse("network-export", to_csv(header, rows)))
    assert summary["rules"] == 2
    assert summary["rules_inbound"] == 2
    assert summary["rules_allow"] == 2
    assert summary["rules_any_source"] == 2


def test_a_semicolon_separated_file_is_refused_saying_so() -> None:
    data = b"user_id;course;completed_utc\nalice@x.invalid;Phishing;2026-10-16\n"
    with pytest.raises(ImportRejectedError, match="semicolon") as refused:
        parse("training-csv", data)
    assert "must be comma separated" in str(refused.value)
    assert "missing the column" in str(refused.value)
    commas = b"course,completed_utc\nPhishing,2026-10-16\n"
    with pytest.raises(ImportRejectedError, match="missing the column") as plain:
        parse("training-csv", commas)
    assert "semicolon" not in str(plain.value)


# --- dates without a time zone --------------------------------------------------------


def test_dates_without_a_time_zone_are_stored_as_utc_and_flagged() -> None:
    naive = with_cell(GOOD_DEVICE, "last_seen", "2026-10-16T08:00:00")
    result = parse("device-inventory", devices(naive))
    assert result.facts[0].value["last_seen"] == CAPTURED_AT.isoformat()
    assert summary_of(result)["timezone_assumed_utc"] is True
    zoned = with_cell(GOOD_DEVICE, "last_seen", "2026-10-16T10:00:00+02:00")
    flagged = parse("device-inventory", devices(zoned))
    assert flagged.facts[0].value["last_seen"] == CAPTURED_AT.isoformat()
    assert summary_of(flagged)["timezone_assumed_utc"] is False
    leavers = parse("leavers-csv", BY_FILE["leavers.csv"].data)
    assert summary_of(leavers)["timezone_assumed_utc"] is True


def test_the_capture_time_is_never_taken_from_a_csv() -> None:
    for fixture in EVERY:
        result = parse(fixture.source_code, fixture.data)
        assert result.captured_at is None
        assert summary_of(result)["capture_time_source"] == "upload"


# --- record types, ports and the rest of the reading ----------------------------------


def test_a_network_line_defaults_to_a_device_and_a_wrong_type_is_rejected() -> None:
    header = ["record_type", "device_id", "ssid", "security_mode"]
    rows = [
        ["", "fw-1", "", ""],
        ["router", "fw-2", "", ""],
        ["ssid", "", "Guests", "WPA2"],
    ]
    result = parse("network-export", to_csv(header, rows))
    assert [fact.key for fact in result.facts[:2]] == ["network.device", "network.ssid"]
    assert reasons(result) == ["record_type must be one of device, rule, ssid"]
    device = facts_with(result, ".device")[0]
    assert device.value["syslog_target"] is None


def test_an_exchange_line_needs_a_record_type() -> None:
    header = ["record_type", "domain", "enabled"]
    rows = [["", mail(1), "true"], ["dkim", mail(2), "true"]]
    result = parse("exchange-export", to_csv(header, rows))
    assert summary_of(result)["dkim_domains"] == 1
    assert reasons(result) == ["record_type is empty"]


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("3389", 3389),
        ("0", 0),
        ("65535", 65535),
        ("1024-2048", "1024-2048"),
        ("0080-0090", "80-90"),
        ("ANY", "any"),
        ("*", "any"),
        ("", None),
    ],
)
def test_a_firewall_port_is_a_number_a_range_or_any(
    cell: str, expected: object
) -> None:
    found = read_port_cell({"port": cell}, "port", "destination_port", Flags())
    assert found == expected


BAD_PORTS = ["65536", "80,443", "http", "1-2-3", "-5", "1-", "9" * 9]


@pytest.mark.parametrize("cell", BAD_PORTS)
def test_anything_else_in_a_port_cell_is_a_row_error(cell: str) -> None:
    with pytest.raises(RowError, match="must be a port number"):
        read_port_cell({"port": cell}, "port", "destination_port", Flags())


def test_the_exchange_alerts_are_told_apart_by_kind_and_state() -> None:
    result = parse("exchange-export", EXCHANGE.data)
    alerts = {
        fact.value["alert_kind"]: fact.value["disabled"]
        for fact in facts_with(result, ".alert")
    }
    assert alerts == {
        "admin-role": False,
        "forwarding-rule": True,
        "risky-sign-in": False,
    }


# --- a saved mapping --------------------------------------------------------------


def vendor_style(fixture: Fixture) -> tuple[bytes, dict[str, str]]:
    """The fixture with every contract column renamed, and the mapping to undo it."""
    keys = {column.key for column in BY_CODE[fixture.source_code].columns}
    rows = table_of(fixture.data)
    mapping: dict[str, str] = {}
    for index, name in enumerate(rows[0]):
        if name in keys:
            vendor = f"Vendor column {index}"
            mapping[vendor] = name
            rows[0][index] = vendor
    return render(rows), mapping


@pytest.mark.parametrize("fixture", EVERY, ids=fixture_id)
def test_a_saved_mapping_reads_a_vendor_style_file_to_the_same_facts(
    fixture: Fixture,
) -> None:
    adapter = BY_CODE[fixture.source_code]
    vendor, mapping = vendor_style(fixture)
    with pytest.raises(ImportRejectedError, match=MISSING):
        adapter.parse(vendor, MAX_ROWS)
    mapped = adapter.with_mapping(mapping)
    assert isinstance(mapped, CsvAdapter)
    assert mapped is not adapter
    result = mapped.parse(vendor, MAX_ROWS)
    assert result.facts == adapter.parse(fixture.data, MAX_ROWS).facts
    assert summary_of(result) == fixture.expected


def test_a_column_found_twice_is_refused() -> None:
    header = ["Machine", "hostname", *DEVICE_HEADER[1:]]
    row = ["machine-1", *GOOD_DEVICE]
    mapped = BY_CODE["device-inventory"].with_mapping({"Machine": "hostname"})
    with pytest.raises(ImportRejectedError, match="has the column hostname twice"):
        mapped.parse(to_csv(header, [row]), MAX_ROWS)
