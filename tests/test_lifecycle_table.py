"""The shipped vendor end-of-support table (data/lifecycle.yaml) read by PC-DEV-03."""

from datetime import date

import pytest

from app.checks.devices import Device, _lifecycle_end
from app.checks.lifecycle import load_lifecycle, parse_lifecycle

TABLE = load_lifecycle()


def end(os_name: str, version: str, form: str | None = None) -> date | None:
    entry = _lifecycle_end(TABLE, Device("d", os_name, version, None, form))
    return None if entry is None else entry.end_of_support


def test_the_shipped_table_reads_and_dates_known_builds() -> None:
    assert len(TABLE) >= 15
    assert end("windows", "10.0.19045.6456") == date(2025, 10, 14)  # Windows 10 22H2
    assert end("windows", "10.0.22631.4317") == date(2025, 11, 11)  # 11 23H2 Home/Pro
    assert end("windows", "10.0.20348.2700") == date(2031, 10, 14)  # Server 2022
    assert end("linux", "22.04") == date(2027, 5, 31)
    assert end("macos", "15.1") is None  # Apple publishes no dates
    assert end("windows", "10.0.10240") is None  # not in the table: unknown


def test_one_build_of_two_products_needs_the_form_factor() -> None:
    # 10.0.26100 is Windows 11 24H2 and Windows Server 2025.
    assert end("windows", "10.0.26100.2033", "workstation") == date(2026, 10, 13)
    assert end("windows", "10.0.26100.2033", "server") == date(2034, 11, 14)
    assert end("windows", "10.0.26100.2033", None) is None


@pytest.mark.parametrize(
    "text",
    [
        "entries: [{os: beos, version_prefix: '5', end_of_support: 2001-01-01}]",
        "entries: [{os: windows, version_prefix: '', end_of_support: 2030-01-01}]",
        "entries: [{os: windows, version_prefix: '10.0', end_of_support: soon}]",
        "entries: [{os: windows, version_prefix: '10.0', end_of_support: 2030-01-01,"
        " form_factor: phone}]",
        "entries: [{os: linux, version_prefix: '22.04', end_of_support: 2027-05-31},"
        " {os: linux, version_prefix: '22.04', end_of_support: 2027-05-31}]",
    ],
)
def test_a_wrong_entry_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        parse_lifecycle(text)
