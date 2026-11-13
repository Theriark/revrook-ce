"""The exported_at column of a CSV export: the file's own capture time."""

from datetime import UTC, datetime

from app.importers.generic import ADAPTERS

BY_CODE = {adapter.source_code: adapter for adapter in ADAPTERS}
HEADER = "record_type,device_id,rule_enabled,direction,action,source,destination_port"


def parse(code: str, text: str):
    return BY_CODE[code].parse(text.encode(), 100)


def test_exported_at_is_the_capture_time_of_the_file() -> None:
    rule = "rule,fw,true,inbound,allow,any,443"
    result = parse(
        "network-export",
        f"{HEADER},exported_at\n{rule},2026-11-13T10:00:00Z\n{rule},2026-11-13T10:05:00Z\n",
    )
    assert result.captured_at == datetime(2026, 11, 13, 10, 5, tzinfo=UTC)
    assert dict(result.facts[-1].value)["capture_time_source"] == "file"


def test_without_the_column_the_upload_time_is_used() -> None:
    result = parse("network-export", f"{HEADER}\nrule,fw,true,inbound,allow,any,443\n")
    assert result.captured_at is None
    assert dict(result.facts[-1].value)["capture_time_source"] == "upload"


def test_every_csv_source_reads_it_and_the_leavers_exported_column() -> None:
    sources = {
        "device-inventory",
        "backup-export",
        "network-export",
        "training-csv",
        "leavers-csv",
        "exchange-export",
    }
    for code in sources:
        assert any(c.key == "exported_at" for c in BY_CODE[code].columns), code
    leavers = parse(
        "leavers-csv",
        "user_id,leave_date,account_enabled,exported\n"
        "user10@example.invalid,2026-10-01,false,2026-11-12T08:00:00Z\n",
    )
    assert leavers.captured_at == datetime(2026, 11, 12, 8, 0, tzinfo=UTC)
