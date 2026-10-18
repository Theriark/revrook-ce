"""The preview of the mapping profile editor (synthetic data, no database)."""

import re

import pytest

from app.importers.base import ImportRejectedError
from app.importers.generic import CsvAdapter
from app.importers.preview import (
    EMPTY,
    NOT_READ,
    PREVIEW_ROWS,
    PSEUDONYM,
    UNREADABLE,
    VALUE,
    Preview,
    build_preview,
    editor_adapters,
    offered_headers,
)
from app.importers.registry import build_default_registry
from app.pseudonym import Pseudonymiser
from helpers import (
    VENDOR_COLUMNS,
    VENDOR_REQUIRED,
    vendor_device_row,
    vendor_header,
    vendor_inventory,
)
from tools.make_fixtures import DOMAIN, to_csv, user_name
from tools.make_generic_fixtures import CLIENT_LABEL, HOSTNAME_PREFIX, SERIAL_PREFIX

REGISTRY = build_default_registry()
PSEUDONYMISE = Pseudonymiser(bytes(range(32)))
HEX16 = re.compile(r"[0-9a-f]{16}")
MAX_ROWS = 1000
REQUIRED_ONLY = {key: VENDOR_COLUMNS[key] for key in VENDOR_REQUIRED}


def adapter(code: str) -> CsvAdapter:
    found = REGISTRY.get(code)
    assert isinstance(found, CsvAdapter)
    return found


def preview_of(
    data: bytes, chosen: dict[str, str], code: str = "device-inventory"
) -> Preview:
    return build_preview(adapter(code), data, chosen, PSEUDONYMISE, MAX_ROWS)


def short_file(rows: list[list[str]]) -> bytes:
    return to_csv(vendor_header(), rows)


def cell(preview: Preview, row: int, key: str) -> tuple[str, str, bool]:
    keys = [choice.key for choice in preview.shown]
    found = preview.rows[row].cells[keys.index(key)]
    return found.text, found.state, found.assumed_utc


def every_text(preview: Preview) -> str:
    parts = list(preview.offered)
    for row in preview.rows:
        parts.append(row.reason or "")
        parts.extend(item.text for item in row.cells)
    return "\n".join(parts)


def test_the_editor_maps_the_six_generic_sources() -> None:
    codes = [item.source_code for item in editor_adapters(REGISTRY)]
    assert codes == [
        "backup-export",
        "device-inventory",
        "exchange-export",
        "leavers-csv",
        "network-export",
        "training-csv",
    ]


def test_a_vendor_file_is_mapped_and_read_as_the_importer_reads_it() -> None:
    preview = preview_of(vendor_inventory(), VENDOR_COLUMNS)
    assert preview.importable
    assert preview.missing == ()
    assert preview.mapping() == {v: k for k, v in VENDOR_COLUMNS.items()}
    assert len(preview.rows) == 10
    assert preview.rejected == 0
    assert not preview.more_rows
    assert [row.number for row in preview.rows] == list(range(1, 11))
    assert preview.assumed_utc
    text, state, assumed = cell(preview, 0, "last_seen")
    assert (state, assumed) == (VALUE, True)
    assert text.endswith("+00:00")
    assert cell(preview, 0, "av_signature_date")[2] is False
    host, host_state, _ = cell(preview, 0, "hostname")
    assert host_state == PSEUDONYM and HEX16.fullmatch(host)
    owner, owner_state, _ = cell(preview, 0, "user")
    assert owner_state == PSEUDONYM and HEX16.fullmatch(owner)
    assert owner == PSEUDONYMISE(user_name(1))
    assert cell(preview, 9, "user")[1] == EMPTY
    assert cell(preview, 0, "disk_encrypted")[0] == "yes"


def test_unread_columns_are_neither_offered_nor_shown() -> None:
    preview = preview_of(vendor_inventory(), VENDOR_COLUMNS)
    assert preview.hidden_headers == 2
    assert "serial" not in preview.offered
    assert "client_name" not in preview.offered
    everything = every_text(preview)
    for value in (SERIAL_PREFIX, CLIENT_LABEL, HOSTNAME_PREFIX, DOMAIN, "@"):
        assert value not in everything


def test_without_a_mapping_the_missing_columns_are_named() -> None:
    preview = preview_of(vendor_inventory(), {})
    assert not preview.importable
    assert "os" in preview.missing
    assert "last_seen" in preview.missing
    assert "device_id or hostname" in preview.missing
    assert preview.problem is not None
    assert "missing the column" in preview.problem
    assert preview.rows == ()
    assert preview.mapping() == {}


def test_one_missing_required_column_is_named_alone() -> None:
    chosen = {key: header for key, header in VENDOR_COLUMNS.items() if key != "os"}
    preview = preview_of(vendor_inventory(), chosen)
    assert preview.missing == ("os",)
    assert preview.problem == "The file is missing the column os."
    by_key = {choice.key: choice for choice in preview.choices}
    assert by_key["os"].header is None and by_key["os"].required
    assert by_key["hostname"].header == "Machine"


def test_only_the_first_20_rows_are_shown() -> None:
    rows = [vendor_device_row(f"vendor-{number}", "Shield") for number in range(25)]
    preview = preview_of(short_file(rows), REQUIRED_ONLY)
    assert len(preview.rows) == PREVIEW_ROWS == 20
    assert preview.more_rows


def test_hostile_cells_are_neutralised_and_never_repeated() -> None:
    rows = [
        vendor_device_row("vendor-1", "=cmd|' /C calc'!A0"),
        vendor_device_row("vendor-2", "<script>alert(1)</script>"),
        vendor_device_row("vendor-3", "A" * 5000),
        vendor_device_row("vendor-4", f"contact ops@{DOMAIN}"),
        vendor_device_row("vendor-5", "Shield", seen="not a time"),
        vendor_device_row("x" * 300, "Shield"),
    ]
    preview = preview_of(short_file(rows), REQUIRED_ONLY)
    assert cell(preview, 0, "av_product")[0] == "'=cmd|' /C calc'!A0"
    # The text is kept as written; the page escapes it (test_profile_editor.py).
    assert cell(preview, 1, "av_product")[0] == "<script>alert(1)</script>"
    assert cell(preview, 2, "av_product")[0] == "A" * 100
    assert cell(preview, 3, "av_product")[1] == UNREADABLE
    assert preview.rows[3].reason == "av_product must not contain an email address"
    assert cell(preview, 4, "last_seen")[1] == UNREADABLE
    assert preview.rows[4].reason == "last_seen must be an ISO 8601 date and time"
    assert cell(preview, 5, "hostname")[1] == UNREADABLE
    assert preview.rows[5].reason == "hostname is too long"
    assert preview.rejected == 3
    assert DOMAIN not in every_text(preview)
    assert "x" * 300 not in every_text(preview)


def test_record_types_mark_the_columns_they_do_not_read() -> None:
    header = ["Kind", "Box", "Rule on", "Way", "Verdict", "Network", "Mode"]
    chosen = {
        "record_type": "Kind",
        "device_id": "Box",
        "rule_enabled": "Rule on",
        "direction": "Way",
        "action": "Verdict",
        "ssid": "Network",
        "security_mode": "Mode",
    }
    rows = [
        ["device", "fw-1", "", "", "", "", ""],
        ["rule", "", "true", "inbound", "allow", "", ""],
        ["printer", "fw-2", "", "", "", "", ""],
    ]
    preview = preview_of(to_csv(header, rows), chosen, "network-export")
    assert preview.importable
    assert cell(preview, 0, "record_type") == ("device", VALUE, False)
    assert cell(preview, 0, "direction")[1] == NOT_READ
    assert cell(preview, 1, "device_id")[1] == NOT_READ
    assert cell(preview, 1, "direction")[0] == "inbound"
    assert cell(preview, 2, "record_type")[1] == UNREADABLE
    assert cell(preview, 2, "device_id")[1] == NOT_READ
    assert preview.rows[2].reason == "record_type must be one of device, rule, ssid"


def test_one_file_column_for_two_columns_is_refused() -> None:
    chosen = {**REQUIRED_ONLY, "os": "Machine"}
    preview = preview_of(short_file([vendor_device_row("v", "S")]), chosen)
    message = "One file column is chosen for two columns: hostname and os."
    assert preview.problem == message
    assert preview.rows == ()
    by_key = {choice.key: choice.header for choice in preview.choices}
    assert by_key["os"] == "Machine"


def test_a_column_found_twice_is_a_problem_not_an_error() -> None:
    header = [*vendor_header(), "hostname"]
    rows = [[*vendor_device_row("v", "S"), "w"]]
    preview = preview_of(to_csv(header, rows), REQUIRED_ONLY)
    assert preview.problem == "The file has the column hostname twice."
    assert not preview.importable
    assert preview.rows == ()


def test_choices_of_unknown_columns_or_headers_are_ignored() -> None:
    chosen = {**REQUIRED_ONLY, "no_such_column": "Machine", "user": "Not in file"}
    preview = preview_of(short_file([vendor_device_row("v", "S")]), chosen)
    assert preview.importable
    assert "Not in file" not in preview.mapping()
    assert set(preview.mapping().values()) == set(REQUIRED_ONLY)


def test_a_semicolon_file_says_so() -> None:
    preview = preview_of(b"Machine;Platform\nv;Windows\n", {})
    assert preview.problem is not None
    assert preview.problem.startswith("The delimiter looks like a semicolon")


def test_a_file_with_more_rows_than_allowed_is_a_problem() -> None:
    rows = [vendor_device_row(f"v{number}", "S") for number in range(5)]
    data = short_file(rows)
    inventory = adapter("device-inventory")
    preview = build_preview(inventory, data, REQUIRED_ONLY, PSEUDONYMISE, 3)
    assert preview.problem == "The file has more than 3 rows."
    assert len(preview.rows) == 3


def test_a_header_only_file_has_no_rows() -> None:
    preview = preview_of(short_file([]), REQUIRED_ONLY)
    assert preview.importable
    assert preview.rows == ()


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b'{"value": []}', "must be a CSV file"),
        (b"\n\n", "The file is empty."),
        (b'"unclosed\n' + b"x" * 200_000, "not a readable CSV"),
        (b"a\x00b", "not readable text"),
    ],
)
def test_a_file_that_cannot_be_read_is_refused(data: bytes, message: str) -> None:
    with pytest.raises(ImportRejectedError, match=message):
        preview_of(data, {})


def test_offered_headers_hide_what_must_not_be_mapped() -> None:
    header = [
        "Machine",
        "",
        "Serial Number",
        "Client name",
        f"owner@{DOMAIN}",
        "N" * 101,
        "Tab\there",
        "Machine",
    ]
    offered, hidden = offered_headers(header)
    assert offered == ("Machine",)
    assert hidden == 6


def test_at_most_200_headers_are_offered() -> None:
    offered, hidden = offered_headers([f"Column {number}" for number in range(205)])
    assert len(offered) == 200
    assert hidden == 5
