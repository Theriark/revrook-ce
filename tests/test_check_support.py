"""The parts of the check engine the vectors do not reach (phase 5, part 2).

Reading facts and times, the merge of the two device sources, and a few results
that need two sources at once. Everything is built from plain model objects: the
engine reads no database, no clock and no network.
"""

from datetime import UTC, date, datetime, timedelta
from fractions import Fraction
from typing import Any

import pytest

from app.checks import support
from app.checks.devices import Device, merged_devices
from app.checks.engine import evaluate_control
from app.checks.library import Control, load_library
from app.checks.model import Evidence, LifecycleEntry, SourceFacts
from app.checks.support import Context
from tools.vector_facts import AS_OF

LIBRARY = load_library()
CAPTURED = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
RECENT = (CAPTURED - timedelta(days=1)).isoformat()
STALE = (CAPTURED - timedelta(days=60)).isoformat()
INTUNE_CAPTURED = CAPTURED - timedelta(days=2)


def facts(**kinds: list[dict[str, Any]]) -> SourceFacts:
    return SourceFacts(CAPTURED, {kind: tuple(rows) for kind, rows in kinds.items()})


def context(control_id: str, evidence: Evidence) -> Context:
    return Context(LIBRARY.control(control_id), evidence)


# --- SourceFacts -----------------------------------------------------------------


def test_facts_are_grouped_by_record_kind_and_the_summary_is_kept_apart() -> None:
    grouped = SourceFacts.from_facts(
        CAPTURED,
        [
            ("inventory.device", {"device": "d1"}),
            ("inventory.device", {"device": "d2"}),
            ("inventory.summary", {"devices": 2}),
            ("bare", {"x": 1}),
        ],
    )
    assert grouped.captured_at == CAPTURED
    assert [row["device"] for row in grouped.rows("device")] == ["d1", "d2"]
    assert grouped.summary == {"devices": 2}
    assert grouped.rows("bare") == ({"x": 1},)
    assert grouped.rows("missing") == ()
    assert "summary" not in grouped.kinds


def test_a_source_without_a_summary_has_an_empty_one() -> None:
    assert SourceFacts.from_facts(CAPTURED, []).summary == {}


# --- times -----------------------------------------------------------------------


def test_a_time_is_read_from_iso_text_and_a_naive_time_is_utc() -> None:
    assert support.parse_time("2026-10-16T08:00:00+00:00") == CAPTURED
    assert support.parse_time("2026-10-16T08:00:00") == CAPTURED
    plus_one = support.parse_time("2026-10-16T09:00:00+01:00")
    assert plus_one == CAPTURED


@pytest.mark.parametrize("value", [None, 5, True, "", "yesterday", "2026-13-45"])
def test_anything_that_is_not_a_time_is_none(value: Any) -> None:
    assert support.parse_time(value) is None
    assert support.within(CAPTURED, value, 14) is None
    assert support.within_hours(CAPTURED, value, Fraction(36)) is None


def test_a_window_is_inclusive_and_a_time_after_the_capture_is_unreadable() -> None:
    exactly = (CAPTURED - timedelta(days=14)).isoformat()
    over = (CAPTURED - timedelta(days=14, seconds=1)).isoformat()
    later = (CAPTURED + timedelta(seconds=1)).isoformat()
    assert support.within(CAPTURED, exactly, 14) is True
    assert support.within(CAPTURED, over, 14) is False
    assert support.within(CAPTURED, later, 14) is None
    assert support.within(CAPTURED, CAPTURED.isoformat(), 14) is True


def test_a_window_of_exact_hours_is_inclusive() -> None:
    hours = Fraction(3, 2) * 24
    exactly = (CAPTURED - timedelta(hours=36)).isoformat()
    over = (CAPTURED - timedelta(hours=36, microseconds=1)).isoformat()
    later = (CAPTURED + timedelta(microseconds=1)).isoformat()
    assert support.within_hours(CAPTURED, exactly, hours) is True
    assert support.within_hours(CAPTURED, over, hours) is False
    assert support.within_hours(CAPTURED, later, hours) is None


def test_the_small_readers_never_guess() -> None:
    assert support.text_of("a") == "a"
    assert support.text_of("") is None
    assert support.text_of(3) is None
    assert support.count_of(3) == 3
    assert support.count_of(True) is None
    assert support.count_of("3") is None
    assert support.flag_of(False) is False
    assert support.flag_of(0) is None
    assert support.oldest([None, None]) is None
    assert support.oldest([CAPTURED, None, CAPTURED - timedelta(days=1)]) == (
        CAPTURED - timedelta(days=1)
    )


def test_a_threshold_that_is_not_there_is_none() -> None:
    assert support._least(None) is None
    assert support._most(None) is None


# --- the two device sources ------------------------------------------------------


def inventory_rows() -> list[dict[str, Any]]:
    return [
        {
            "device": "d1",
            "last_seen": RECENT,
            "os": "windows",
            "os_build": "10.0.19045",
            "disk_encrypted": False,
        },
        {"device": "d3", "last_seen": RECENT, "os": "windows", "disk_encrypted": None},
        {"device": "d4", "last_seen": RECENT, "disk_encrypted": None},
        {"device": None, "last_seen": RECENT, "os": "windows"},
        {"device": "d5", "last_seen": STALE, "os": "windows"},
    ]


def intune_rows() -> list[dict[str, Any]]:
    seen = (INTUNE_CAPTURED - timedelta(days=1)).isoformat()
    return [
        {
            "device": "d1",
            "last_contact": seen,
            "os": "macos",
            "os_version": "14",
            "encrypted": True,
        },
        {"device": "d2", "last_contact": seen, "os": "ios", "encrypted": False},
        {"device": "d3", "last_contact": seen, "os": "windows", "encrypted": None},
        {"device": "d4", "last_contact": seen, "os_version": "6.1", "encrypted": False},
    ]


def two_sources() -> Evidence:
    return Evidence(
        as_of=AS_OF,
        sources={
            "device-inventory": SourceFacts(
                CAPTURED, {"device": tuple(inventory_rows())}
            ),
            "intune-devices": SourceFacts(
                INTUNE_CAPTURED, {"device": tuple(intune_rows())}
            ),
        },
    )


def test_a_device_in_both_sources_is_one_device_and_the_first_source_wins() -> None:
    merged = merged_devices(context("PC-DEV-04", two_sources()))
    assert merged is not None
    devices, at = merged
    by_key = {device.key: device for device in devices}
    assert sorted(by_key) == ["d1", "d2", "d3", "d4"]
    # d1: the inventory names the system and the version, either source may
    # say the disk is encrypted, and one source saying so is enough.
    assert by_key["d1"] == Device("d1", "windows", "10.0.19045", True)
    assert by_key["d2"] == Device("d2", "ios", None, False)
    # d3: neither source knows, so it is unknown; the system comes from the inventory.
    assert by_key["d3"] == Device("d3", "windows", None, None)
    # d4: an unknown flag and a false one is false; the version comes from Intune.
    assert by_key["d4"] == Device("d4", None, "6.1", False)
    assert at == INTUNE_CAPTURED


def test_a_device_without_an_id_or_outside_the_window_is_left_out() -> None:
    merged = merged_devices(context("PC-DEV-04", two_sources()))
    assert merged is not None
    assert "d5" not in {device.key for device in merged[0]}
    assert len(merged[0]) == 4


def test_without_either_source_there_is_nothing_to_merge() -> None:
    evidence = Evidence(as_of=AS_OF)
    assert merged_devices(context("PC-DEV-04", evidence)) is None


def test_a_device_encrypted_in_one_source_only_counts_as_encrypted() -> None:
    control = LIBRARY.control("PC-DEV-04")
    evidence = two_sources()
    result = evaluate_control(LIBRARY, control, evidence)
    # d1 True, d2 False, d4 False are known; d3 is not and stays in the denominator.
    # One of four, and one unresolved device cannot lift it to the partial share.
    assert (result.numerator, result.denominator) == (1, 4)
    assert result.status == "fail"
    assert "1 could not be told" in result.detail


# --- results that need two sources ----------------------------------------------


def lifecycle() -> tuple[LifecycleEntry, ...]:
    return (LifecycleEntry("windows", "10.0.19", date(2030, 1, 1)),)


def test_devices_the_lifecycle_table_does_not_know_are_named_in_the_detail() -> None:
    control = LIBRARY.control("PC-DEV-03")
    seen = {"last_seen": RECENT}
    rows = [
        {"device": "w1", **seen, "os": "windows", "os_build": "10.0.19045"},
        {"device": "l1", **seen, "os": "linux", "os_build": "6.1"},
    ]
    evidence = Evidence(
        as_of=AS_OF,
        sources={"device-inventory": SourceFacts(CAPTURED, {"device": tuple(rows)})},
        lifecycle=lifecycle(),
    )
    result = evaluate_control(LIBRARY, control, evidence)
    assert result.status == "pass"
    assert (result.numerator, result.denominator) == (0, 1)
    assert "1 are not in the table" in result.detail


def test_servers_of_the_inventory_count_toward_central_logging() -> None:
    control = LIBRARY.control("PC-LOG-06")
    network = facts(device=[{"perimeter": True, "syslog_target": True}])
    servers = facts(
        device=[
            {"last_seen": RECENT, "form_factor": "server", "log_forwarding": False},
            {"last_seen": RECENT, "form_factor": "workstation", "log_forwarding": True},
            {"last_seen": STALE, "form_factor": "server", "log_forwarding": True},
        ]
    )
    evidence = Evidence(
        as_of=AS_OF,
        sources={"network-export": network, "device-inventory": servers},
    )
    result = evaluate_control(LIBRARY, control, evidence)
    # The firewall sends its logs, the active server does not: one of two.
    assert (result.numerator, result.denominator) == (1, 2)
    assert result.status == "partial"


def test_central_logging_reads_the_inventory_alone_too() -> None:
    control = LIBRARY.control("PC-LOG-06")
    servers = facts(
        device=[{"last_seen": RECENT, "form_factor": "server", "log_forwarding": True}]
    )
    evidence = Evidence(as_of=AS_OF, sources={"device-inventory": servers})
    result = evaluate_control(LIBRARY, control, evidence)
    assert result.status == "pass"
    assert (result.numerator, result.denominator) == (1, 1)


# --- the control accessors --------------------------------------------------------


def control_with(name: str) -> Control:
    return next(item for item in LIBRARY.controls if name in item.params)


def test_a_parameter_is_read_as_the_kind_it_is() -> None:
    days = control_with("active_days")
    assert days.whole("active_days") == 14
    assert days.number("active_days") == 14
    ports = LIBRARY.control("PC-NET-02")
    assert ports.whole_list("risk_ports") == (3389, 445, 23, 5900, 22)
    modes = LIBRARY.control("PC-NET-04")
    assert modes.words("obsolete_modes") == ("open", "wep", "wpa")
    share = LIBRARY.control("PC-EML-01")
    assert share.number("partial_share") == Fraction(1, 2)


def test_a_parameter_of_the_wrong_kind_or_a_missing_one_is_a_key_error() -> None:
    days = control_with("active_days")
    ports = LIBRARY.control("PC-NET-02")
    with pytest.raises(KeyError):
        days.whole_list("active_days")
    with pytest.raises(KeyError):
        days.words("active_days")
    with pytest.raises(KeyError):
        ports.whole("risk_ports")
    with pytest.raises(KeyError):
        ports.number("risk_ports")
    with pytest.raises(KeyError):
        ports.words("risk_ports")
    with pytest.raises(KeyError):
        days.whole("nothing_of_the_kind")


def test_the_library_finds_a_control_and_a_domain() -> None:
    assert LIBRARY.control("PC-ACC-01").domain == "ACC"
    assert [item.id for item in LIBRARY.in_domain("NET")] == [
        f"PC-NET-0{number}" for number in range(1, 6)
    ]
    with pytest.raises(KeyError):
        LIBRARY.control("PC-XXX-99")
    assert LIBRARY.in_domain("XXX") == ()
