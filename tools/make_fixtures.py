"""Deterministic synthetic fixtures for the Microsoft importers (phase 3).

Everything here is invented: the mail domain is fixture.example.invalid, the
device ids come from a seeded generator and the "sensitive" values are obvious
placeholders. The files follow the contracts in docs/importers.md (field names
marked INFERRED there are used only where phase-plan-3 lists them). Run

    python3 tools/make_fixtures.py OUTPUT_DIR [--seed N]

to write the five fixture files and a manifest.json that says, for each file,
its source code, how many facts it must produce and the counts of its summary.
The same seed always gives the same bytes. Only the standard library is used.
"""

import argparse
import csv
import io
import json
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SEED = 20261017
GRAPH = "https://graph.microsoft.com/v1.0/$metadata#"
DOMAIN = "fixture.example.invalid"
CAPTURED_AT = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
# Placeholders for the fields no importer may ever store.
IMEIS = tuple(f"99000000000{number:04d}" for number in range(1, 5))
PHONE_NUMBERS = tuple(f"+1555010{number:04d}" for number in range(1, 5))
BYPASS_CODES = tuple(f"BYPASS-SYNTHETIC-{number:04d}" for number in range(1, 5))
SENSITIVE_VALUES = (*IMEIS, *PHONE_NUMBERS, *BYPASS_CODES)
POLICY_NAMES = (
    "Require MFA for all users",
    "Block legacy authentication",
    "MFA report only",
    "Admin roles",
    "Guests",
)
DEVICE_NAME_PREFIX = "FIXTURE-DEVICE-"


@dataclass(frozen=True)
class Fixture:
    """One fixture file and what it must produce."""

    file_name: str
    source_code: str
    data: bytes
    facts: int
    expected: dict[str, Any]


def stamp(moment: datetime) -> str:
    """A time in the form Graph uses: UTC with a Z."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def user_name(number: int) -> str:
    return f"user{number:02d}@{DOMAIN}"


def to_json(document: object) -> bytes:
    return json.dumps(document, indent=2).encode("utf-8") + b"\n"


def to_csv(header: list[str], rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def new_id(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


# --- Entra authentication-methods registration -----------------------------


def entra_users(rng: random.Random) -> list[dict[str, Any]]:
    users: list[dict[str, Any]] = []
    for number in range(1, 13):
        registered = number not in (5, 9)
        methods: list[str] = []
        if registered:
            methods.append("microsoftAuthenticatorPush")
            if number % 2 == 0:
                methods.append("mobilePhone")
        users.append(
            {
                "id": new_id(rng),
                "userPrincipalName": user_name(number),
                "userDisplayName": f"Fixture User {number:02d}",
                "isAdmin": number in (1, 2),
                "isMfaRegistered": registered,
                "isMfaCapable": number not in (5, 9, 10),
                "isPasswordlessCapable": number in (1, 2, 3),
                "methodsRegistered": methods,
                "userType": "guest" if number == 12 else "member",
                "lastUpdatedDateTime": stamp(CAPTURED_AT - timedelta(hours=5 * number)),
            }
        )
    return users


def entra_registration_json(seed: int = SEED) -> Fixture:
    users = entra_users(random.Random(seed))
    document = {
        "@odata.context": f"{GRAPH}userRegistrationDetails",
        "capturedAt": stamp(CAPTURED_AT),
        "value": users,
    }
    newest = CAPTURED_AT - timedelta(hours=5)
    expected = {
        "users": 12,
        "admins": 2,
        "guests": 1,
        "mfa_registered": 10,
        "mfa_registered_known": True,
        "mfa_capable": 9,
        "passwordless_capable": 3,
        "report_updated_at": newest.isoformat(),
        "rows_rejected": 0,
        "capture_time_source": "file",
        "timezone_assumed_utc": False,
    }
    return Fixture(
        "entra-registration.json",
        "entra-registration",
        to_json(document),
        13,
        expected,
    )


def entra_registration_csv(seed: int = SEED) -> Fixture:
    users = entra_users(random.Random(seed))
    header = [
        "User principal name",
        "MFA Capable",
        "Passwordless Capable",
        "Methods registered",
        "Last Updated Time",
    ]
    rows = [
        [
            user["userPrincipalName"],
            str(user["isMfaCapable"]).lower(),
            str(user["isPasswordlessCapable"]).lower(),
            ";".join(user["methodsRegistered"]),
            user["lastUpdatedDateTime"],
        ]
        for user in users
    ]
    expected = {
        "users": 12,
        "admins": 0,
        "guests": 0,
        "mfa_registered": 0,
        "mfa_registered_known": False,
        "mfa_capable": 9,
        "passwordless_capable": 3,
        "report_updated_at": (CAPTURED_AT - timedelta(hours=5)).isoformat(),
        "rows_rejected": 0,
        "capture_time_source": "upload",
        "timezone_assumed_utc": False,
    }
    return Fixture(
        "entra-registration.csv",
        "entra-registration",
        to_csv(header, rows),
        13,
        expected,
    )


# --- Microsoft Secure Score -------------------------------------------------

CONTROL_NAMES = (
    ("AdminMFAV2", "Identity", 10),
    ("MFARegistrationV2", "Identity", 9),
    ("BlockLegacyAuthentication", "Identity", 8),
    ("PWAgePolicyNew", "Identity", 0),
    ("SigninRiskPolicy", "Identity", 0),
    ("IntuneCompliancePolicy", "Device", 5),
    ("DeviceEncryption", "Device", 4),
    ("EnableATP", "Device", 0),
    ("SafeLinksPolicy", "Apps", 3),
    ("AntiPhishingPolicy", "Apps", 3),
    ("OneAdmin", "Identity", 1),
    ("AuditLogEnabled", "Data", 4),
)


def secure_score_json(seed: int = SEED) -> Fixture:
    controls = [
        {
            "controlName": name,
            "controlCategory": category,
            "score": score,
            "description": f"Synthetic description of {name}",
        }
        for name, category, score in CONTROL_NAMES
    ]
    readings = [
        (0, 48.5, controls),
        (-1, 44, controls[:3]),
        (-2, 41.5, controls[:3]),
    ]
    average = [{"basis": "AllTenants", "averageScore": 41.2}]
    value = [
        {
            "id": f"fixture-score-{index}",
            "azureTenantId": new_id(random.Random(seed)),
            "activeUserCount": 11,
            "createdDateTime": stamp(CAPTURED_AT + timedelta(days=offset)),
            "currentScore": current,
            "enabledServices": ["Exchange", "SharePoint", "Teams"],
            "licensedUserCount": 12,
            "maxScore": 100,
            "averageComparativeScores": average,
            "controlScores": scores,
        }
        for index, (offset, current, scores) in enumerate(readings)
    ]
    document = {"@odata.context": f"{GRAPH}secureScores", "value": value}
    expected = {
        "entries": 3,
        "current_score": "48.5",
        "max_score": "100",
        "licensed_users": 12,
        "active_users": 11,
        "services": 3,
        "controls": len(controls),
        "score_created_at": CAPTURED_AT.isoformat(),
        "rows_rejected": 0,
        "capture_time_source": "file",
        "timezone_assumed_utc": False,
    }
    return Fixture(
        "secure-score.json",
        "secure-score",
        to_json(document),
        len(controls) + 1,
        expected,
    )


# --- Intune devices -----------------------------------------------------------

COMPLIANCE_BY_DEVICE = (
    ["compliant"] * 11 + ["noncompliant"] * 3 + ["inGracePeriod"],
    ["Windows"] * 9 + ["macOS"] * 2 + ["iOS"] * 2 + ["Android"] * 2,
)


def intune_devices_csv(seed: int = SEED) -> Fixture:
    rng = random.Random(seed)
    compliance, systems = COMPLIANCE_BY_DEVICE
    header = [
        "DeviceName",
        "managementAgent",
        "ownerType",
        "complianceState",
        "OS",
        "OSVersion",
        "LastContact",
        "UPN",
        "DeviceId",
        "IMEI",
        "PhoneNumber",
    ]
    rows: list[list[str]] = []
    mobile = 0
    for index in range(15):
        is_mobile = systems[index] in ("iOS", "Android")
        rows.append(
            [
                f"{DEVICE_NAME_PREFIX}{index + 1:04d}",
                "configurationManagerClientMdm" if index in (3, 4) else "mdm",
                "personal" if index in (12, 13, 14) else "company",
                compliance[index],
                systems[index],
                f"10.0.{22000 + index}",
                (CAPTURED_AT - timedelta(hours=index)).strftime("%Y-%m-%dT%H:%M:%S"),
                "" if index in (6, 7) else user_name(index % 12 + 1),
                new_id(rng),
                IMEIS[mobile] if is_mobile else "",
                PHONE_NUMBERS[mobile] if is_mobile else "",
            ]
        )
        mobile += 1 if is_mobile else 0
    expected = {
        "devices": 15,
        "compliant": 11,
        "noncompliant": 3,
        "windows": 9,
        "macos": 2,
        "ios": 2,
        "android": 2,
        "personal": 3,
        "with_user": 13,
        "encryption_known": 0,
        "encrypted": 0,
        "sensitive_fields_dropped": True,
        "rows_rejected": 0,
        "capture_time_source": "upload",
        "timezone_assumed_utc": True,
    }
    return Fixture(
        "intune-devices.csv",
        "intune-devices",
        to_csv(header, rows),
        16,
        expected,
    )


def intune_devices_json(seed: int = SEED) -> Fixture:
    rng = random.Random(seed)
    value: list[dict[str, Any]] = []
    for index in range(6):
        value.append(
            {
                "id": new_id(rng),
                "deviceName": f"{DEVICE_NAME_PREFIX}J{index + 1:03d}",
                "managementAgent": "mdm",
                "ownerType": "company",
                "complianceState": "compliant" if index < 4 else "noncompliant",
                "operatingSystem": "Windows" if index < 5 else "iOS",
                "osVersion": "10.0.22631",
                "lastSyncDateTime": stamp(CAPTURED_AT - timedelta(hours=index)),
                "userPrincipalName": user_name(index + 1),
                "isEncrypted": index != 2,
                "imei": IMEIS[index % 4],
                "phoneNumber": PHONE_NUMBERS[index % 4],
                "activationLockBypassCode": BYPASS_CODES[index % 4],
            }
        )
    document = {"capturedAt": stamp(CAPTURED_AT), "value": value}
    expected = {
        "devices": 6,
        "compliant": 4,
        "noncompliant": 2,
        "windows": 5,
        "macos": 0,
        "ios": 1,
        "android": 0,
        "personal": 0,
        "with_user": 6,
        "encryption_known": 6,
        "encrypted": 5,
        "sensitive_fields_dropped": True,
        "rows_rejected": 0,
        "capture_time_source": "file",
        "timezone_assumed_utc": False,
    }
    return Fixture(
        "intune-devices.json",
        "intune-devices",
        to_json(document),
        7,
        expected,
    )


# --- Conditional Access policies ---------------------------------------------


def policy(
    number: int,
    state: str,
    users: dict[str, Any],
    controls: list[str] | None,
    clients: list[str],
) -> dict[str, Any]:
    applications = ["Office365"] if number == 5 else ["All"]
    grant: dict[str, Any] | None = None
    if controls is not None:
        grant = {"operator": "OR", "builtInControls": controls}
    return {
        "id": f"fixture-policy-{number}",
        "displayName": POLICY_NAMES[number - 1],
        "state": state,
        "createdDateTime": "2026-01-10T09:00:00Z",
        "modifiedDateTime": "2026-09-30T09:00:00Z",
        "conditions": {
            "users": users,
            "applications": {"includeApplications": applications},
            "clientAppTypes": clients,
        },
        "grantControls": grant,
    }


def conditional_access_json() -> Fixture:
    everyone = {"includeUsers": ["All"], "excludeUsers": [user_name(1)]}
    policies = [
        policy(1, "enabled", everyone, ["mfa"], ["all"]),
        policy(
            2,
            "enabled",
            {"includeUsers": ["All"]},
            ["block"],
            ["exchangeActiveSync", "other"],
        ),
        policy(
            3,
            "enabledForReportingButNotEnforced",
            {"includeUsers": ["All"]},
            ["mfa"],
            ["all"],
        ),
        policy(
            4,
            "disabled",
            {"includeRoles": ["role-a", "role-b", "role-c"]},
            ["mfa"],
            ["all"],
        ),
        policy(5, "enabled", {"includeUsers": ["GuestsOrExternalUsers"]}, None, []),
    ]
    expected = {
        "policies": 5,
        "enabled": 3,
        "report_only": 1,
        "disabled": 1,
        "tenant_state": "conditional-access",
        "rows_rejected": 0,
        "capture_time_source": "upload",
        "timezone_assumed_utc": False,
    }
    document = {"value": policies}
    return Fixture(
        "conditional-access.json",
        "conditional-access",
        to_json(document),
        6,
        expected,
    )


def conditional_access_empty() -> Fixture:
    expected = {
        "policies": 0,
        "enabled": 0,
        "report_only": 0,
        "disabled": 0,
        "tenant_state": "security-defaults",
        "rows_rejected": 0,
        "capture_time_source": "upload",
        "timezone_assumed_utc": False,
    }
    return Fixture(
        "conditional-access-empty.json",
        "conditional-access",
        to_json({"value": []}),
        1,
        expected,
    )


# --- Directory roles ----------------------------------------------------------


def directory_roles_json(seed: int = SEED) -> Fixture:
    rng = random.Random(seed)

    def member(number: int, enabled: bool) -> dict[str, Any]:
        return {
            "@odata.type": "#microsoft.graph.user",
            "id": new_id(rng),
            "userPrincipalName": user_name(number),
            "accountEnabled": enabled,
        }

    service_principal = {
        "@odata.type": "#microsoft.graph.servicePrincipal",
        "id": new_id(rng),
        "displayName": "Fixture automation",
    }
    roles = [
        {
            "displayName": "Global Administrator",
            "members": [member(1, True), member(2, True), service_principal],
        },
        {
            "displayName": "Exchange Administrator",
            "members": [member(2, True), member(3, False)],
        },
        {"displayName": "User Administrator", "members": []},
    ]
    expected = {
        "assignments": 4,
        "roles": 2,
        "users": 3,
        "global_admins": 2,
        "non_user_members": 1,
        "input_format": "graph-json",
        "rows_rejected": 0,
        "capture_time_source": "upload",
        "timezone_assumed_utc": False,
    }
    return Fixture(
        "directory-roles.json",
        "directory-roles",
        to_json({"value": roles}),
        5,
        expected,
    )


def directory_roles_csv() -> Fixture:
    header = ["User principal name", "Role", "Enabled", "Permanent"]
    rows = [
        [user_name(1), "Global Administrator", "true", "true"],
        [user_name(2), "Global Administrator", "true", "false"],
        [user_name(3), "Exchange Administrator", "true", "true"],
    ]
    expected = {
        "assignments": 3,
        "roles": 2,
        "users": 3,
        "global_admins": 2,
        "non_user_members": 0,
        "input_format": "manual-csv",
        "rows_rejected": 0,
        "capture_time_source": "upload",
        "timezone_assumed_utc": False,
    }
    return Fixture(
        "directory-roles.csv",
        "directory-roles",
        to_csv(header, rows),
        4,
        expected,
    )


# --- sets and the command line -------------------------------------------------


def main_fixtures(seed: int = SEED) -> list[Fixture]:
    """The five files the end-to-end script imports, one per adapter."""
    return [
        entra_registration_json(seed),
        secure_score_json(seed),
        intune_devices_csv(seed),
        conditional_access_json(),
        directory_roles_json(seed),
    ]


def variant_fixtures(seed: int = SEED) -> list[Fixture]:
    """Other shapes the adapters accept (used by the tests)."""
    return [
        entra_registration_csv(seed),
        intune_devices_json(seed),
        conditional_access_empty(),
        directory_roles_csv(),
    ]


def write_all(directory: Path, seed: int = SEED) -> dict[str, Any]:
    """Write the five files and manifest.json; returns the manifest."""
    directory.mkdir(parents=True, exist_ok=True)
    files: dict[str, Any] = {}
    for fixture in main_fixtures(seed):
        (directory / fixture.file_name).write_bytes(fixture.data)
        files[fixture.file_name] = {
            "source_code": fixture.source_code,
            "facts": fixture.facts,
            "expected": fixture.expected,
        }
    manifest = {
        "seed": seed,
        "domain": DOMAIN,
        "device_name_prefix": DEVICE_NAME_PREFIX,
        "policy_names": list(POLICY_NAMES),
        "sensitive_values": list(SENSITIVE_VALUES),
        "files": files,
    }
    (directory / "manifest.json").write_bytes(to_json(manifest))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the synthetic fixtures.")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--seed", type=int, default=SEED)
    arguments = parser.parse_args(argv)
    manifest = write_all(arguments.directory, arguments.seed)
    count = len(manifest["files"])
    print(f"wrote {count} fixture files to {arguments.directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
