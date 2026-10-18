"""Deterministic synthetic fixtures for the generic importers (phase 4).

Everything here is invented: the mail domain is fixture.example.invalid, the
serial numbers come from a seeded generator, and the names of hosts, jobs,
networks and mail domains are obvious placeholders that must never reach the
database. The files follow the contracts in docs/importers.md. Run, from the
repository root,

    python3 -m tools.make_generic_fixtures OUTPUT_DIR [--seed N]

to write the six fixture files and a manifest.json that says, for each file, its
source code, how many facts it must produce and the counts of its summary, and
lists the values that must never be stored (`unread_values`). The same seed always
gives the same bytes. Only the standard library is used.
"""

import argparse
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tools.make_fixtures import (
    CAPTURED_AT,
    DOMAIN,
    SEED,
    Fixture,
    stamp,
    to_csv,
    to_json,
    user_name,
)

HOSTNAME_PREFIX = "FIXTURE-HOST-"
SERIAL_PREFIX = "SERIAL-FIXTURE-"
CLIENT_LABEL = "Fixture Client Ltd"
SYSTEM_PREFIX = "FIXTURE-SYSTEM-"
JOB_PREFIX = "fixture-job-"
SSID_NAMES = ("FixtureCorp", "FixtureGuest", "FixtureOpen")
MAIL_DOMAINS = (f"mail1.{DOMAIN}", f"mail2.{DOMAIN}")
SYSLOG_HOST = f"syslog.{DOMAIN}"
UNREAD_VALUES = (
    HOSTNAME_PREFIX,
    SERIAL_PREFIX,
    CLIENT_LABEL,
    SYSTEM_PREFIX,
    JOB_PREFIX,
    *SSID_NAMES,
    *MAIL_DOMAINS,
    SYSLOG_HOST,
    DOMAIN,
)


def stamp_naive(moment: datetime) -> str:
    """A time without a time zone, as many exports write it."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S")


def csv_summary(**counts: Any) -> dict[str, Any]:
    """The flags every CSV summary carries, with the counts of one file."""
    return {
        **counts,
        "rows_rejected": 0,
        "capture_time_source": "upload",
        "timezone_assumed_utc": False,
        "unread_columns_present": False,
    }


def device_inventory_csv(seed: int = SEED) -> Fixture:
    rng = random.Random(seed)
    systems = ["Windows 11"] * 7 + ["macOS 14", "Linux Ubuntu 22.04"]
    systems.append("Windows Server 2022")
    forms = ["laptop"] * 8 + ["server", "server"]
    header = [
        "hostname",
        "os",
        "form_factor",
        "os_build",
        "last_seen",
        "patch_status",
        "pending_critical_updates",
        "last_patch",
        "av_product",
        "av_status",
        "av_signature_date",
        "disk_encrypted",
        "local_admin_count",
        "tamper_protection",
        "dns_filter_active",
        "log_forwarding",
        "user",
        "serial",
        "client_name",
    ]
    rows: list[list[str]] = []
    for index in range(10):
        tamper = ("true" if index < 6 else "false") if index < 7 else ""
        status = "disabled" if index == 9 else "unknown" if index == 8 else "protected"
        rows.append(
            [
                f"{HOSTNAME_PREFIX}{index + 1:04d}",
                systems[index],
                forms[index],
                "10.0.22631" if systems[index].startswith("Windows") else "",
                stamp_naive(CAPTURED_AT - timedelta(hours=index)),
                "pending" if index in (7, 8) else "up_to_date",
                {7: "2", 8: "1"}.get(index, "0"),
                stamp(CAPTURED_AT - timedelta(days=index + 1)) if index < 9 else "",
                "Synthetic Shield",
                status,
                stamp(CAPTURED_AT - timedelta(days=1)),
                "false" if index == 9 else "true",
                "1" if index < 5 else "",
                tamper,
                "yes" if index < 5 else "no",
                "true" if index == 9 else "",
                user_name(index + 1) if index < 7 else "",
                f"{SERIAL_PREFIX}{rng.getrandbits(32):08x}",
                CLIENT_LABEL,
            ]
        )
    expected = csv_summary(
        devices=10,
        windows=8,
        macos=1,
        ios=0,
        android=0,
        linux=1,
        servers=2,
        patch_up_to_date=8,
        patch_pending=2,
        with_pending_critical=2,
        pending_critical_known=10,
        last_patch_known=9,
        av_protected=8,
        av_disabled=1,
        encrypted=9,
        encryption_known=10,
        local_admin_known=5,
        tamper_protected=6,
        tamper_known=7,
        dns_filtered=5,
        dns_filter_known=10,
        log_forwarded=1,
        log_forwarding_known=1,
        last_seen_newest=CAPTURED_AT.isoformat(),
        with_user=7,
    )
    expected["timezone_assumed_utc"] = True
    expected["unread_columns_present"] = True
    return Fixture(
        "device-inventory.csv",
        "device-inventory",
        to_csv(header, rows),
        11,
        expected,
    )


def backup_export_csv() -> Fixture:
    header = [
        "system_or_device",
        "backup_job",
        "last_success",
        "last_result",
        "retention_days",
        "restore_test_date",
        "asset_type",
        "schedule_hours",
        "encrypted",
        "immutable",
        "offsite",
        "restore_test_result",
    ]
    types = ["server", "server", "exchange", "onedrive"]
    types += ["sharepoint", "teams", "workstation", "database"]
    results = ["success"] * 5 + ["warning", "warning", "failed"]
    tests = ["success", "success", "failed"] + [""] * 5
    rows: list[list[str]] = []
    for index in range(8):
        immutable = "true" if index < 3 else "false" if index < 6 else ""
        rows.append(
            [
                f"{SYSTEM_PREFIX}{index % 6 + 1:02d}",
                f"{JOB_PREFIX}{index + 1}",
                stamp(CAPTURED_AT - timedelta(hours=index * 6 + 2)),
                results[index],
                str(30 + index * 10),
                stamp(CAPTURED_AT - timedelta(days=20)) if index < 3 else "",
                types[index],
                "24" if index < 6 else "",
                "false" if index == 7 else "true",
                immutable,
                "no" if index == 7 else "yes",
                tests[index],
            ]
        )
    expected = csv_summary(
        jobs=8,
        success=5,
        warning=2,
        failed=1,
        schedule_known=6,
        retention_known=8,
        encrypted=7,
        encryption_known=8,
        immutable=3,
        immutable_known=6,
        offsite=7,
        offsite_known=8,
        restore_tested=3,
        restore_passed=2,
        restore_failed=1,
        exchange=1,
        onedrive=1,
        sharepoint=1,
        teams=1,
        assets=6,
        last_success_newest=(CAPTURED_AT - timedelta(hours=2)).isoformat(),
    )
    return Fixture(
        "backup-export.csv", "backup-export", to_csv(header, rows), 9, expected
    )


def network_export_csv() -> Fixture:
    header = [
        "record_type",
        "device_id",
        "perimeter",
        "firmware_release_date",
        "end_of_support_date",
        "wan_admin_enabled",
        "default_credentials_flag",
        "syslog_target",
        "rule_enabled",
        "direction",
        "action",
        "source",
        "destination_port",
        "ssid",
        "security_mode",
        "guest_isolated",
        "guest_ssid",
    ]

    def line(**cells: str) -> list[str]:
        return [cells.get(name, "") for name in header]

    firmware = stamp(datetime(2026, 3, 1, 9, 0, tzinfo=UTC))
    older = stamp(datetime(2024, 6, 1, 9, 0, tzinfo=UTC))
    rows = [
        line(
            record_type="device",
            device_id=f"{HOSTNAME_PREFIX}FW1",
            perimeter="true",
            firmware_release_date=firmware,
            end_of_support_date="2028-01-01",
            wan_admin_enabled="false",
            default_credentials_flag="false",
            syslog_target=SYSLOG_HOST,
        ),
        line(
            record_type="device",
            device_id=f"{HOSTNAME_PREFIX}FW2",
            perimeter="false",
            firmware_release_date=older,
            wan_admin_enabled="true",
            default_credentials_flag="true",
        ),
        line(
            record_type="rule",
            rule_enabled="true",
            direction="inbound",
            action="allow",
            source="any",
            destination_port="3389",
        ),
        line(
            record_type="rule",
            rule_enabled="true",
            direction="inbound",
            action="allow",
            source="203.0.113.0/24",
            destination_port="443",
        ),
        line(
            record_type="rule",
            rule_enabled="false",
            direction="inbound",
            action="deny",
            source="any",
            destination_port="any",
        ),
        line(
            record_type="rule",
            rule_enabled="true",
            direction="outbound",
            action="allow",
            source="any",
            destination_port="1024-2048",
        ),
        line(
            record_type="ssid",
            ssid=SSID_NAMES[0],
            security_mode="WPA3",
            guest_ssid="false",
        ),
        line(
            record_type="ssid",
            ssid=SSID_NAMES[1],
            security_mode="WPA2",
            guest_ssid="true",
            guest_isolated="true",
        ),
        line(
            record_type="ssid",
            ssid=SSID_NAMES[2],
            security_mode="Open",
            guest_ssid="true",
            guest_isolated="false",
        ),
    ]
    expected = csv_summary(
        devices=2,
        perimeter_devices=1,
        wan_admin_enabled=1,
        default_credentials=1,
        syslog_configured=1,
        rules=4,
        rules_enabled=3,
        rules_inbound=3,
        rules_allow=3,
        rules_any_source=3,
        ssids=3,
        ssids_open=1,
        ssids_guest=2,
        ssids_guest_isolated=1,
        firmware_newest=datetime(2026, 3, 1, 9, 0, tzinfo=UTC).isoformat(),
    )
    expected["timezone_assumed_utc"] = True
    return Fixture(
        "network-export.csv", "network-export", to_csv(header, rows), 10, expected
    )


def training_csv() -> Fixture:
    header = ["user_id", "course", "completed_utc"]
    completions = ((1, 10), (2, 20), (3, 30), (4, 40), (5, 50), (1, 3))
    rows: list[list[str]] = []
    for number, days in completions:
        done = stamp(CAPTURED_AT - timedelta(days=days))
        rows.append([user_name(number), "Security basics 2026", done])
    expected = csv_summary(
        completions=6,
        users=5,
        completed_newest=(CAPTURED_AT - timedelta(days=3)).isoformat(),
    )
    return Fixture("training.csv", "training-csv", to_csv(header, rows), 7, expected)


def leavers_csv() -> Fixture:
    header = ["user_id", "leave_date", "account_enabled"]
    rows = [
        [user_name(6), "2026-09-20", "false"],
        [user_name(7), "2026-10-01", "true"],
        [user_name(8), "2026-10-10", ""],
    ]
    expected = csv_summary(
        leavers=3,
        account_state_known=2,
        still_enabled=1,
        users=3,
        leave_newest=datetime(2026, 10, 10, tzinfo=UTC).isoformat(),
    )
    expected["timezone_assumed_utc"] = True
    return Fixture("leavers.csv", "leavers-csv", to_csv(header, rows), 4, expected)


def exchange_export_csv() -> Fixture:
    header = [
        "record_type",
        "domain",
        "enabled",
        "policy_type",
        "auto_forwarding_mode",
        "mailbox",
        "recipient_type",
        "forwarding_external",
        "account_enabled",
        "unified_audit_log_enabled",
        "audit_disabled",
        "alert_kind",
        "disabled",
        "recipient_count",
        "last_acknowledged",
    ]

    def line(**cells: str) -> list[str]:
        return [cells.get(name, "") for name in header]

    acknowledged = stamp(CAPTURED_AT - timedelta(days=5))
    rows = [
        line(record_type="dkim", domain=MAIL_DOMAINS[0], enabled="true"),
        line(record_type="dkim", domain=MAIL_DOMAINS[1], enabled="false"),
        line(record_type="policy", policy_type="Anti-phish", enabled="true"),
        line(record_type="policy", policy_type="Safe links", enabled="true"),
        line(record_type="policy", policy_type="Safe attachments", enabled="false"),
        line(record_type="policy", policy_type="Preset", enabled="false"),
        line(
            record_type="policy",
            policy_type="Outbound spam",
            enabled="true",
            auto_forwarding_mode="Off",
        ),
        line(
            record_type="mailbox",
            mailbox=user_name(1),
            recipient_type="UserMailbox",
            forwarding_external="false",
        ),
        line(
            record_type="mailbox",
            mailbox=f"shared1@{DOMAIN}",
            recipient_type="SharedMailbox",
            forwarding_external="false",
            account_enabled="true",
        ),
        line(
            record_type="mailbox",
            mailbox=f"shared2@{DOMAIN}",
            recipient_type="SharedMailbox",
            forwarding_external="true",
            account_enabled="false",
        ),
        line(
            record_type="audit",
            unified_audit_log_enabled="true",
            audit_disabled="false",
        ),
        line(
            record_type="alert",
            alert_kind="New admin role assignment",
            disabled="false",
            recipient_count="2",
            last_acknowledged=acknowledged,
        ),
        line(
            record_type="alert",
            alert_kind="Mail forwarding rule",
            disabled="true",
            recipient_count="0",
        ),
        line(
            record_type="alert",
            alert_kind="Risky sign-in",
            disabled="false",
            recipient_count="1",
        ),
    ]
    expected = csv_summary(
        dkim_domains=2,
        dkim_enabled=1,
        policies=5,
        anti_phish_enabled=1,
        safe_links_enabled=1,
        safe_attachments_enabled=0,
        preset_enabled=0,
        auto_forwarding_off=1,
        mailboxes=3,
        shared_mailboxes=2,
        shared_mailboxes_enabled=1,
        forwarding_external=1,
        audit_records=1,
        audit_ingestion_enabled=1,
        alerts=3,
        alerts_with_recipient=2,
        alert_admin_role_enabled=1,
        alert_forwarding_rule_enabled=0,
        alert_risky_sign_in_enabled=1,
        alert_acknowledged_newest=(CAPTURED_AT - timedelta(days=5)).isoformat(),
    )
    return Fixture(
        "exchange-export.csv", "exchange-export", to_csv(header, rows), 15, expected
    )


# --- the set and the command line ----------------------------------------------


def generic_fixtures(seed: int = SEED) -> list[Fixture]:
    """The six files of the generic and administrative sources."""
    return [
        device_inventory_csv(seed),
        backup_export_csv(),
        network_export_csv(),
        training_csv(),
        leavers_csv(),
        exchange_export_csv(),
    ]


def write_generic(directory: Path, seed: int = SEED) -> dict[str, Any]:
    """Write the six files and manifest.json; returns the manifest."""
    directory.mkdir(parents=True, exist_ok=True)
    files: dict[str, Any] = {}
    for fixture in generic_fixtures(seed):
        (directory / fixture.file_name).write_bytes(fixture.data)
        files[fixture.file_name] = {
            "source_code": fixture.source_code,
            "facts": fixture.facts,
            "expected": fixture.expected,
        }
    manifest = {
        "seed": seed,
        "domain": DOMAIN,
        "unread_values": list(UNREAD_VALUES),
        "files": files,
    }
    (directory / "manifest.json").write_bytes(to_json(manifest))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the generic fixtures.")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--seed", type=int, default=SEED)
    arguments = parser.parse_args(argv)
    manifest = write_generic(arguments.directory, arguments.seed)
    count = len(manifest["files"])
    print(f"wrote {count} fixture files to {arguments.directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
