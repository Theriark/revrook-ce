"""Synthetic evidence files for the Development seed (DEV_SEED=1, app/devseed.py).

One file for each evidence source of the product, so every page that reads a
source can be tried from the interface on the Development site. Everything here
is invented: the mail domains end in .example.invalid, the people are
user01@seed.example.invalid and so on, the hosts are SEED-HOST-0001 and so on, and
no file holds a password, a key or a real name. The bytes depend only on the
profile and on `captured` (a time with a time zone), so the same hour always gives
the same files.

Two profiles show the two ends of the score: TIDY (a well kept client) and GAPS (a
client with the usual findings: a user without MFA, a failed backup, an open
firewall rule, a mail domain without DMARC). The files follow the contracts of
docs/importers.md and tests/test_devdata.py reads each one with the importer of
its source, so a change to an importer that this module no longer fits fails there.
"""

import csv
import io
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.sources import DNS_SOURCE

TIDY = "tidy"
GAPS = "gaps"
PROFILES = (TIDY, GAPS)
DOMAIN = "seed.example.invalid"
GRAPH = "https://graph.microsoft.com/v1.0/$metadata#"
HOST_PREFIX = "SEED-HOST-"
USER_COUNT = 12
NAMESPACE = uuid.UUID("5eed0000-0000-4000-8000-000000000953")
# The mail domain of each profile, for the public DNS check (no network is used).
MAIL_DOMAINS = {
    TIDY: "tidy-mail.example.invalid",
    GAPS: "gaps-mail.example.invalid",
}
SELECTORS = ("selector1", "selector2")


@dataclass(frozen=True)
class SeedFile:
    """One synthetic export: the source it belongs to and its bytes."""

    source_code: str
    data: bytes


def user(number: int) -> str:
    return f"user{number:02d}@{DOMAIN}"


def stamp(moment: datetime) -> str:
    """A time as Graph writes it: UTC with a Z."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def naive(moment: datetime) -> str:
    """A time without a time zone, as many exports write it (read as UTC)."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S")


def new_id(profile: str, kind: str, number: int) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{profile}/{kind}/{number}"))


def to_json(document: object) -> bytes:
    return json.dumps(document, indent=2).encode("utf-8") + b"\n"


def to_csv(header: Sequence[str], rows: Sequence[Sequence[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def keyed_rows(header: Sequence[str], lines: Sequence[dict[str, str]]) -> bytes:
    """A CSV whose rows are given by column name; a column left out stays empty."""
    return to_csv(header, [[line.get(name, "") for name in header] for line in lines])


# --- Microsoft sources -------------------------------------------------------------


def entra_registration(profile: str, captured: datetime) -> bytes:
    tidy = profile == TIDY
    users = []
    for number in range(1, USER_COUNT + 1):
        registered = tidy or number not in (5, 9)
        users.append(
            {
                "id": new_id(profile, "user", number),
                "userPrincipalName": user(number),
                "userDisplayName": f"Seed User {number:02d}",
                "isAdmin": number in (1, 2),
                "isMfaRegistered": registered,
                "isMfaCapable": registered and (tidy or number != 10),
                "isPasswordlessCapable": number in (1, 2, 3),
                "methodsRegistered": (
                    ["microsoftAuthenticatorPush"] if registered else []
                ),
                "userType": "guest" if number == USER_COUNT else "member",
                "lastUpdatedDateTime": stamp(captured - timedelta(hours=5 * number)),
            }
        )
    return to_json(
        {
            "@odata.context": f"{GRAPH}userRegistrationDetails",
            "capturedAt": stamp(captured),
            "value": users,
        }
    )


SCORE_CONTROLS = (
    ("AdminMFAV2", "Identity", 10),
    ("BlockLegacyAuthentication", "Identity", 8),
    ("SafeLinksPolicy", "Apps", 6),
    ("MailboxAuditing", "Data", 4),
)


def secure_score(profile: str, captured: datetime) -> bytes:
    scale = 1 if profile == TIDY else 0.5
    controls = [
        {
            "controlName": name,
            "controlCategory": category,
            "score": score * scale,
            "description": f"Synthetic description of {name}",
        }
        for name, category, score in SCORE_CONTROLS
    ]
    readings = ((0, 78.0 if profile == TIDY else 41.5), (-1, 74.0), (-2, 71.5))
    value = [
        {
            "id": f"seed-score-{index}",
            "azureTenantId": new_id(profile, "tenant", 1),
            "activeUserCount": USER_COUNT - 1,
            "createdDateTime": stamp(captured + timedelta(days=offset)),
            "currentScore": current,
            "enabledServices": ["Exchange", "SharePoint", "Teams"],
            "licensedUserCount": USER_COUNT,
            "maxScore": 100,
            "averageComparativeScores": [{"basis": "AllTenants", "averageScore": 41.2}],
            "controlScores": controls,
        }
        for index, (offset, current) in enumerate(readings)
    ]
    return to_json({"@odata.context": f"{GRAPH}secureScores", "value": value})


def intune_devices(profile: str, captured: datetime) -> bytes:
    header = (
        "DeviceName",
        "managementAgent",
        "ownerType",
        "complianceState",
        "OS",
        "OSVersion",
        "LastContact",
        "UPN",
        "DeviceId",
    )
    tidy = profile == TIDY
    systems = ["Windows"] * 5 + ["macOS", "iOS", "Android"]
    rows = []
    for index, system in enumerate(systems):
        compliant = tidy or index not in (2, 3, 7)
        rows.append(
            [
                f"{HOST_PREFIX}M{index + 1:03d}",
                "mdm",
                "company" if tidy or index < 6 else "personal",
                "compliant" if compliant else "noncompliant",
                system,
                f"10.0.{22000 + index}",
                naive(captured - timedelta(hours=index)),
                user(index % USER_COUNT + 1),
                new_id(profile, "device", index),
            ]
        )
    return to_csv(header, rows)


def policy(
    profile: str,
    modified: datetime,
    number: int,
    name: str,
    state: str,
    users: Mapping[str, object],
    controls: list[str] | None,
    clients: list[str],
) -> dict[str, object]:
    grant = None
    if controls is not None:
        grant = {"operator": "OR", "builtInControls": controls}
    return {
        "id": new_id(profile, "policy", number),
        "displayName": name,
        "state": state,
        "createdDateTime": "2026-01-10T09:00:00Z",
        "modifiedDateTime": stamp(modified),
        "conditions": {
            "users": users,
            "applications": {"includeApplications": ["All"]},
            "clientAppTypes": clients,
        },
        "grantControls": grant,
    }


def conditional_access(profile: str, captured: datetime) -> bytes:
    modified = captured - timedelta(days=1)
    everyone = {"includeUsers": ["All"], "excludeUsers": [user(1)]}
    if profile == TIDY:
        policies = [
            policy(
                profile,
                modified,
                1,
                "Require MFA",
                "enabled",
                everyone,
                ["mfa"],
                ["all"],
            ),
            policy(
                profile,
                modified,
                2,
                "Block legacy authentication",
                "enabled",
                {"includeUsers": ["All"]},
                ["block"],
                ["exchangeActiveSync", "other"],
            ),
            policy(
                profile,
                modified,
                3,
                "Admin roles",
                "enabled",
                {"includeRoles": ["role-a", "role-b"]},
                ["mfa"],
                ["all"],
            ),
        ]
    else:
        policies = [
            policy(
                profile,
                modified,
                1,
                "MFA report only",
                "enabledForReportingButNotEnforced",
                {"includeUsers": ["All"]},
                ["mfa"],
                ["all"],
            ),
            policy(
                profile,
                modified,
                2,
                "Admin roles",
                "disabled",
                {"includeRoles": ["role-a"]},
                ["mfa"],
                ["all"],
            ),
        ]
    return to_json({"value": policies})


def directory_roles(profile: str, captured: datetime) -> bytes:
    def member(number: int, enabled: bool) -> dict[str, object]:
        return {
            "@odata.type": "#microsoft.graph.user",
            "id": new_id(profile, "user", number),
            "userPrincipalName": user(number),
            "accountEnabled": enabled,
        }

    global_admins = [member(1, True), member(2, True)]
    if profile == GAPS:
        global_admins += [member(3, True), member(4, False)]
    roles = [
        {"displayName": "Global Administrator", "members": global_admins},
        {"displayName": "Exchange Administrator", "members": [member(2, True)]},
        {"displayName": "User Administrator", "members": []},
    ]
    return to_json({"exportedAt": stamp(captured), "value": roles})


# --- generic and administrative sources ---------------------------------------------

INVENTORY_HEADER = (
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
)


def device_inventory(profile: str, captured: datetime) -> bytes:
    tidy = profile == TIDY
    systems = ["Windows 11"] * 6 + ["macOS 14", "Linux Ubuntu 22.04"]
    systems += ["Windows Server 2022"]
    forms = ["laptop"] * 7 + ["server", "server"]
    lines = []
    for index, system in enumerate(systems):
        weak = not tidy and index in (6, 7, 8)
        lines.append(
            {
                "hostname": f"{HOST_PREFIX}{index + 1:04d}",
                "os": system,
                "form_factor": forms[index],
                "os_build": "10.0.22631" if system.startswith("Windows") else "",
                "last_seen": naive(captured - timedelta(hours=index)),
                "patch_status": "pending" if weak else "up_to_date",
                "pending_critical_updates": "2" if weak else "0",
                "last_patch": stamp(captured - timedelta(days=index + 1)),
                "av_product": "Synthetic Shield",
                "av_status": "disabled" if weak and index == 8 else "protected",
                "av_signature_date": stamp(captured - timedelta(days=1)),
                "disk_encrypted": "false" if weak and index == 7 else "true",
                "local_admin_count": "3" if weak else "1",
                "tamper_protection": "false" if weak else "true",
                "dns_filter_active": "no" if weak else "yes",
                "log_forwarding": "true" if tidy else "",
                "user": user(index + 1) if index < 7 else "",
            }
        )
    return keyed_rows(INVENTORY_HEADER, lines)


BACKUP_HEADER = (
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
)


def backup_export(profile: str, captured: datetime) -> bytes:
    tidy = profile == TIDY
    types = ["server", "server", "exchange", "onedrive", "sharepoint", "workstation"]
    lines = []
    for index, asset in enumerate(types):
        failed = not tidy and index in (1, 5)
        tested = tidy or index == 0
        lines.append(
            {
                "system_or_device": f"SEED-SYSTEM-{index + 1:02d}",
                "backup_job": f"seed-job-{index + 1}",
                "last_success": stamp(
                    captured - timedelta(hours=index * 6 + (400 if failed else 2))
                ),
                "last_result": "failed" if failed else "success",
                "retention_days": "35" if tidy else "7",
                "restore_test_date": stamp(captured - timedelta(days=20))
                if tested
                else "",
                "asset_type": asset,
                "schedule_hours": "24",
                "encrypted": "false" if failed else "true",
                "immutable": "true" if tidy else "false",
                "offsite": "no" if failed else "yes",
                "restore_test_result": "success" if tested else "",
            }
        )
    return keyed_rows(BACKUP_HEADER, lines)


NETWORK_HEADER = (
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
)


def network_export(profile: str, captured: datetime) -> bytes:
    tidy = profile == TIDY
    lines = [
        {
            "record_type": "device",
            "device_id": f"{HOST_PREFIX}FW1",
            "perimeter": "true",
            "firmware_release_date": stamp(
                captured - timedelta(days=60 if tidy else 900)
            ),
            "end_of_support_date": "2030-01-01" if tidy else "2025-01-01",
            "wan_admin_enabled": "false" if tidy else "true",
            "default_credentials_flag": "false" if tidy else "true",
            "syslog_target": f"syslog.{DOMAIN}" if tidy else "",
        },
        {
            "record_type": "rule",
            "rule_enabled": "true",
            "direction": "inbound",
            "action": "allow",
            "source": "203.0.113.0/24" if tidy else "any",
            "destination_port": "443" if tidy else "3389",
        },
        {
            "record_type": "rule",
            "rule_enabled": "true",
            "direction": "outbound",
            "action": "allow",
            "source": "any",
            "destination_port": "1024-2048",
        },
        {
            "record_type": "ssid",
            "ssid": "SeedCorp",
            "security_mode": "WPA3" if tidy else "WPA2",
            "guest_ssid": "false",
        },
        {
            "record_type": "ssid",
            "ssid": "SeedGuest",
            "security_mode": "WPA2" if tidy else "Open",
            "guest_ssid": "true",
            "guest_isolated": "true" if tidy else "false",
        },
    ]
    return keyed_rows(NETWORK_HEADER, lines)


def training(profile: str, captured: datetime) -> bytes:
    people = range(1, 10) if profile == TIDY else range(1, 4)
    rows = [
        [user(number), "Security basics 2026", stamp(captured - timedelta(days=number))]
        for number in people
    ]
    return to_csv(("user_id", "course", "completed_utc"), rows)


def leavers(profile: str, captured: datetime) -> bytes:
    still_enabled = "false" if profile == TIDY else "true"
    rows = [
        [user(10), "2026-09-20", "false", stamp(captured)],
        [user(11), "2026-10-01", still_enabled, stamp(captured)],
    ]
    return to_csv(("user_id", "leave_date", "account_enabled", "exported"), rows)


EXCHANGE_HEADER = (
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
)


def exchange_export(profile: str, captured: datetime) -> bytes:
    tidy = profile == TIDY
    on = "true" if tidy else "false"
    lines = [
        {"record_type": "dkim", "domain": MAIL_DOMAINS[profile], "enabled": on},
        {"record_type": "policy", "policy_type": "Anti-phish", "enabled": "true"},
        {"record_type": "policy", "policy_type": "Safe links", "enabled": on},
        {"record_type": "policy", "policy_type": "Safe attachments", "enabled": on},
        {
            "record_type": "policy",
            "policy_type": "Outbound spam",
            "enabled": "true",
            "auto_forwarding_mode": "Off" if tidy else "On",
        },
        {
            "record_type": "mailbox",
            "mailbox": user(1),
            "recipient_type": "UserMailbox",
            "forwarding_external": "false",
        },
        {
            "record_type": "mailbox",
            "mailbox": f"shared1@{DOMAIN}",
            "recipient_type": "SharedMailbox",
            "forwarding_external": "false" if tidy else "true",
            "account_enabled": "false" if tidy else "true",
        },
        {
            "record_type": "audit",
            "unified_audit_log_enabled": on,
            "audit_disabled": "false" if tidy else "true",
        },
        {
            "record_type": "alert",
            "alert_kind": "New admin role assignment",
            "disabled": "false" if tidy else "true",
            "recipient_count": "2" if tidy else "0",
            "last_acknowledged": stamp(captured - timedelta(days=5)),
        },
    ]
    return keyed_rows(EXCHANGE_HEADER, lines)


def reference_users(profile: str, captured: datetime) -> bytes:
    rows = [
        [
            user(number),
            "true" if profile == TIDY or number % 4 else "false",
            stamp(captured),
        ]
        for number in range(1, 9)
    ]
    return to_csv(("user_principal_name", "mfa_registered", "exported"), rows)


# --- the public DNS check -----------------------------------------------------------


class SeedResolver:
    """Answers the public DNS check from a table, so the seed never uses the network.

    The TIDY mail domain has an SPF record that ends in -all, a DMARC policy of
    reject and a DKIM key for each selector; the GAPS one allows every sender and has
    no DMARC and no DKIM. A name that is not in the table has no record.
    """

    def __init__(self, profile: str) -> None:
        domain = MAIL_DOMAINS[profile]
        self.table: dict[tuple[str, str], tuple[str, ...]] = {}
        if profile == TIDY:
            self.table[(domain, "TXT")] = (
                "v=spf1 include:spf.protection.outlook.com -all",
            )
            self.table[(f"_dmarc.{domain}", "TXT")] = (
                f"v=DMARC1; p=reject; rua=mailto:reports@{domain}",
            )
            for selector in SELECTORS:
                key = (f"{selector}._domainkey.{domain}", "CNAME")
                self.table[key] = (f"{selector}.dkim.example.invalid",)
        else:
            self.table[(domain, "TXT")] = ("v=spf1 +all",)

    def lookup(self, name: str, rdtype: str) -> tuple[str, ...]:
        return self.table.get((name.lower(), rdtype.upper()), ())


# --- the set ---------------------------------------------------------------

BUILDERS = {
    "entra-registration": entra_registration,
    "secure-score": secure_score,
    "intune-devices": intune_devices,
    "conditional-access": conditional_access,
    "directory-roles": directory_roles,
    "device-inventory": device_inventory,
    "backup-export": backup_export,
    "network-export": network_export,
    "training-csv": training,
    "leavers-csv": leavers,
    "exchange-export": exchange_export,
    "reference-csv": reference_users,
}
# Every source is either built here or is the DNS check (SeedResolver above).
SOURCES = (*BUILDERS, DNS_SOURCE)


def seed_files(profile: str, captured: datetime) -> list[SeedFile]:
    """One file for every source that is imported from a file, in a fixed order."""
    if profile not in PROFILES:
        raise ValueError(f"profile must be one of {', '.join(PROFILES)}")
    return [
        SeedFile(code, build(profile, captured)) for code, build in BUILDERS.items()
    ]
