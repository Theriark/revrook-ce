"""The five Microsoft source adapters (phase 3).

Each adapter reads one kind of export (see docs/importers.md for the exact
contract of each) and turns it into facts: counts and flags. A personal
identifier goes into `identifiers`, never into a value, so the evidence store
replaces it with the client's pseudonym. Anything else the adapter keeps is a
number, a flag, a time it parsed itself, a word from a fixed list or a short
safe text. Fields that are sensitive (imei, phoneNumber,
activationLockBypassCode) and free text such as device and policy names are
never read at all.

Files are recognised by their header columns or their JSON fields and never by
their name. A file of another kind is rejected naming what is missing, and when
the file clearly belongs to another adapter the message says which.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Self

from app.importers.base import FactValue, ImportRejectedError, ParsedFact, ParseResult
from app.importers.framework import (
    DEFAULT_MAX_ROWS,
    Column,
    CsvFile,
    Flags,
    MissingStructureError,
    Rejects,
    RowError,
    as_row,
    check_json_size,
    choice,
    decode_text,
    iso,
    json_capture_time,
    json_records,
    json_rows,
    looks_like_json,
    missing_columns,
    number_text,
    open_csv,
    optional_choice,
    parse_json_text,
    parse_number,
    prefix_choice,
    read_count,
    read_flag,
    read_header,
    read_required_time,
    read_rows,
    read_text,
    read_time,
    require_fields,
    resolve_columns,
    safe_text,
    slug,
    summary_fact,
)

SENSITIVE_FIELDS = frozenset({"imei", "phonenumber", "activationlockbypasscode"})
USER_TYPES = {"member": "member", "guest": "guest"}
COMPLIANCE_STATES = {
    "compliant": "compliant",
    "noncompliant": "noncompliant",
    "ingraceperiod": "in-grace-period",
    "unknown": "unknown",
    "error": "error",
    "conflict": "conflict",
    "configmanager": "config-manager",
}
OWNER_TYPES = {"company": "company", "personal": "personal", "unknown": "unknown"}
OS_PREFIXES = (
    ("windows", "windows"),
    ("macos", "macos"),
    ("ios", "ios"),
    ("ipados", "ios"),
    ("android", "android"),
    ("linux", "linux"),
)
POLICY_STATES = {
    "enabled": "enabled",
    "disabled": "disabled",
    "enabledforreportingbutnotenforced": "report-only",
}
LEGACY_CLIENT_TYPES = frozenset({"exchangeactivesync", "other"})
GLOBAL_ADMIN_ROLES = frozenset({"global administrator", "company administrator"})
VERSION_PATTERN = re.compile(r"\d+(\.\d+){0,4}")


@dataclass(frozen=True)
class Sniffed:
    """What a quick look at a file shows: its header, or its first JSON record."""

    header: tuple[str, ...] | None = None
    record: Mapping[str, object] | None = None


def sniff(data: bytes) -> Sniffed | None:
    """A quick look at a file, or None when it cannot be read at all."""
    try:
        text = decode_text(data)
        if looks_like_json(text):
            check_json_size(data)
            records = json_records(parse_json_text(text, DEFAULT_MAX_ROWS))
            first = records[0] if records else None
            return Sniffed(record=first if isinstance(first, dict) else None)
        return Sniffed(header=tuple(read_header(text)))
    except ImportRejectedError:
        return None


class MicrosoftAdapter:
    """What the five adapters share: kind detection, the wrong-file message and
    the saved mapping of a CSV."""

    source_code: str
    version: str
    prefix: str
    label: str
    columns: tuple[Column, ...] = ()
    json_fields: tuple[str, ...] = ()

    def __init__(self, mapping: Mapping[str, str] | None = None) -> None:
        self.mapping: dict[str, str] = dict(mapping or {})

    def with_mapping(self, mapping: Mapping[str, str]) -> Self:
        """The same adapter reading CSV through a saved column mapping."""
        return type(self)(mapping)

    def matches(self, sniffed: Sniffed) -> bool:
        """Whether a file has the columns or fields this adapter requires."""
        if sniffed.header is not None:
            if not self.columns:
                return False
            try:
                found = resolve_columns(sniffed.header, self.columns)
            except ImportRejectedError:
                return False
            return not missing_columns(self.columns, found)
        record = sniffed.record
        if record is None or not self.json_fields:
            return False
        return all(name in record for name in self.json_fields)

    def parse(self, data: bytes, max_rows: int) -> ParseResult:
        try:
            text = decode_text(data)
            if looks_like_json(text):
                check_json_size(data)
                return self.parse_json(parse_json_text(text, max_rows))
            if not self.columns:
                raise MissingStructureError(
                    "The file must be a JSON file saved from Microsoft Graph "
                    f"({self.label})."
                )
            table = open_csv(text, self.columns, max_rows, self.mapping)
            return self.parse_csv(table)
        except MissingStructureError as error:
            raise MissingStructureError(f"{error}{self._hint(data)}") from None

    def parse_json(self, root: object) -> ParseResult:
        raise NotImplementedError  # pragma: no cover

    def parse_csv(self, table: CsvFile) -> ParseResult:
        raise NotImplementedError  # pragma: no cover

    def _hint(self, data: bytes) -> str:
        """' This looks like ...' when exactly one other adapter fits the file."""
        sniffed = sniff(data)
        if sniffed is None:
            return ""
        others = [
            adapter
            for adapter in ADAPTERS
            if adapter.source_code != self.source_code and adapter.matches(sniffed)
        ]
        if len(others) != 1:
            return ""
        return f" This looks like {others[0].label} (source {others[0].source_code})."

    def finish(
        self,
        facts: Iterable[ParsedFact],
        counts: Mapping[str, FactValue],
        rejects: Rejects,
        flags: Flags,
        captured_at: datetime | None,
    ) -> ParseResult:
        summary = summary_fact(
            self.prefix,
            counts,
            rejects,
            flags,
            capture_in_file=captured_at is not None,
        )
        return ParseResult(
            facts=(*facts, *rejects.facts, summary),
            captured_at=captured_at,
        )


def _count_true(facts: Iterable[ParsedFact], key: str) -> int:
    return sum(1 for fact in facts if fact.value.get(key) is True)


def _count_equal(facts: Iterable[ParsedFact], key: str, word: str) -> int:
    return sum(1 for fact in facts if fact.value.get(key) == word)


# --- 1. Entra authentication-methods registration -------------------------

ENTRA_JSON_NAMES = {
    "upn": "userPrincipalName",
    "mfa_registered": "isMfaRegistered",
    "mfa_capable": "isMfaCapable",
    "passwordless_capable": "isPasswordlessCapable",
    "is_admin": "isAdmin",
    "user_type": "userType",
    "methods": "methodsRegistered",
    "updated": "lastUpdatedDateTime",
}


def count_methods(value: object) -> int | None:
    """How many authentication methods a user has registered."""
    if isinstance(value, list):
        names = [slug(item) for item in value]
    elif isinstance(value, str):
        names = [slug(part) for part in re.split(r"[;,|]", value)]
    else:
        return None
    return sum(1 for name in names if name and name != "none")


class EntraRegistrationAdapter(MicrosoftAdapter):
    """Graph userRegistrationDetails (JSON), or its CSV with these columns."""

    source_code = "entra-registration"
    version = "entra-registration-1"
    prefix = "entra"
    label = "an Entra authentication-methods registration report"
    columns = (
        Column("upn", "User principal name", required=True),
        Column("mfa_capable", "MFA Capable", required=True),
        Column("passwordless_capable", "Passwordless Capable", required=True),
        Column("methods", "Methods registered", required=True),
        Column(
            "updated",
            "Last Updated Time",
            required=True,
            aliases=("lastUpdatedDateTime",),
        ),
        Column("mfa_registered", "MFA Registered"),
        Column("is_admin", "Is Admin"),
        Column("user_type", "User type"),
    )
    json_fields = ("userPrincipalName", "isMfaRegistered", "isMfaCapable")

    def read_user(self, raw: Mapping[str, object], flags: Flags) -> ParsedFact:
        upn = read_text(raw, "upn")
        if upn is None:
            raise RowError("User principal name is empty")
        value: dict[str, FactValue] = {
            "mfa_registered": read_flag(raw, "mfa_registered", "MFA Registered"),
            "mfa_capable": read_flag(raw, "mfa_capable", "MFA Capable", required=True),
            "passwordless_capable": read_flag(
                raw, "passwordless_capable", "Passwordless Capable"
            ),
            "is_admin": read_flag(raw, "is_admin", "Is Admin"),
            "user_type": optional_choice(raw.get("user_type"), USER_TYPES),
            "methods": count_methods(raw.get("methods")),
            "updated": iso(read_time(raw, "updated", "Last Updated Time", flags)),
        }
        return ParsedFact("entra.user", value, {"user": upn})

    def parse_csv(self, table: CsvFile) -> ParseResult:
        flags = Flags()
        rejects = Rejects(self.prefix)
        users = read_rows(table.rows(), self.read_user, flags, rejects)
        return self.finish(users, self._counts(users), rejects, flags, None)

    def parse_json(self, root: object) -> ParseResult:
        records = json_records(root)
        require_fields(records, self.json_fields)
        captured_at, assumed = json_capture_time(root)
        flags = Flags(assumed_utc=assumed)
        rejects = Rejects(self.prefix)
        rows = json_rows(records, ENTRA_JSON_NAMES)
        users = read_rows(rows, self.read_user, flags, rejects)
        counts = self._counts(users)
        return self.finish(users, counts, rejects, flags, captured_at)

    @staticmethod
    def _counts(users: list[ParsedFact]) -> dict[str, FactValue]:
        updated: list[str] = []
        for fact in users:
            stamp = fact.value["updated"]
            if isinstance(stamp, str):
                updated.append(stamp)
        known = all(fact.value["mfa_registered"] is not None for fact in users)
        return {
            "users": len(users),
            "admins": _count_true(users, "is_admin"),
            "guests": _count_equal(users, "user_type", "guest"),
            "mfa_registered": _count_true(users, "mfa_registered"),
            "mfa_registered_known": bool(users) and known,
            "mfa_capable": _count_true(users, "mfa_capable"),
            "passwordless_capable": _count_true(users, "passwordless_capable"),
            "report_updated_at": max(updated, default=None),
        }


# --- 2. Microsoft Secure Score ---------------------------------------------

SCORE_JSON_NAMES = {
    "date": "createdDateTime",
    "score": "currentScore",
    "max_score": "maxScore",
    "licensed": "licensedUserCount",
    "active": "activeUserCount",
    "services": "enabledServices",
    "controls": "controlScores",
}


@dataclass(frozen=True)
class ScoreEntry:
    """One Secure Score reading."""

    created: datetime
    current: Decimal
    maximum: Decimal | None
    licensed_users: int | None
    active_users: int | None
    services: int | None
    controls: tuple[object, ...]


def read_score_entry(raw: Mapping[str, object], flags: Flags) -> ScoreEntry:
    created = read_required_time(raw, "date", "Date", flags)
    try:
        current = parse_number(raw.get("score"))
    except ValueError:
        raise RowError("Score must be a number") from None
    maximum: Decimal | None = None
    if raw.get("max_score") not in (None, ""):
        try:
            maximum = parse_number(raw.get("max_score"))
        except ValueError:
            raise RowError("Max score must be a number") from None
    services = raw.get("services")
    controls = raw.get("controls")
    return ScoreEntry(
        created=created,
        current=current,
        maximum=maximum,
        licensed_users=read_count(raw, "licensed", "licensedUserCount"),
        active_users=read_count(raw, "active", "activeUserCount"),
        services=len(services) if isinstance(services, list) else None,
        controls=tuple(controls) if isinstance(controls, list) else (),
    )


def read_score_control(item: object) -> ParsedFact:
    if not isinstance(item, dict):
        raise RowError("A controlScores entry is not an object")
    name = safe_text(item.get("controlName"))
    if not name:
        raise RowError("controlName of a controlScores entry is empty")
    try:
        score = parse_number(item.get("score"))
    except ValueError:
        raise RowError("score of a controlScores entry must be a number") from None
    category = safe_text(item.get("controlCategory"))
    value: dict[str, FactValue] = {
        "name": name,
        "category": category or None,
        "score": number_text(score),
    }
    return ParsedFact("secure_score.control", value)


class SecureScoreAdapter(MicrosoftAdapter):
    """Graph secureScores (JSON), or a CSV with a score column and a date column.

    The newest reading in the file is the one kept.
    """

    source_code = "secure-score"
    version = "secure-score-1"
    prefix = "secure_score"
    label = "a Microsoft Secure Score export"
    columns = (
        Column(
            "date",
            "Date",
            required=True,
            aliases=("createdDateTime", "Created"),
        ),
        Column("score", "Score", required=True, aliases=("Current score",)),
        Column("max_score", "Max score"),
    )
    json_fields = ("currentScore", "maxScore", "createdDateTime")

    def parse_csv(self, table: CsvFile) -> ParseResult:
        return self._build(table.rows())

    def parse_json(self, root: object) -> ParseResult:
        records = json_records(root)
        require_fields(records, self.json_fields)
        return self._build(json_rows(records, SCORE_JSON_NAMES))

    def _build(
        self,
        rows: Iterable[tuple[int, Mapping[str, object] | RowError]],
    ) -> ParseResult:
        flags = Flags()
        rejects = Rejects(self.prefix)
        entries: list[ScoreEntry] = []
        for number, raw in rows:
            with rejects.row(number):
                entries.append(read_score_entry(as_row(raw), flags))
        rejects.require_usable(len(entries))
        newest = max(entries, key=lambda entry: entry.created, default=None)
        facts: list[ParsedFact] = []
        counts: dict[str, FactValue] = {"entries": len(entries)}
        if newest is not None:
            for number, item in enumerate(newest.controls, start=1):
                with rejects.row(number):
                    facts.append(read_score_control(item))
            counts.update(
                {
                    "current_score": number_text(newest.current),
                    "max_score": (
                        number_text(newest.maximum)
                        if newest.maximum is not None
                        else None
                    ),
                    "licensed_users": newest.licensed_users,
                    "active_users": newest.active_users,
                    "services": newest.services,
                    "controls": len(facts),
                    "score_created_at": iso(newest.created),
                }
            )
        captured_at = newest.created if newest is not None else None
        return self.finish(facts, counts, rejects, flags, captured_at)


# --- 3. Intune devices -------------------------------------------------------

INTUNE_JSON_NAMES = {
    "device_id": "id",
    "compliance": "complianceState",
    "os": "operatingSystem",
    "last_contact": "lastSyncDateTime",
    "management": "managementAgent",
    "owner": "ownerType",
    "os_version": "osVersion",
    "upn": "userPrincipalName",
    "encrypted": "isEncrypted",
}


def clean_version(value: str | None) -> str | None:
    """An operating system version such as 10.0.22631, or None."""
    if value is not None and VERSION_PATTERN.fullmatch(value) and len(value) <= 40:
        return value
    return None


class IntuneDevicesAdapter(MicrosoftAdapter):
    """The Intune export job (CSV), or Graph managedDevices (JSON).

    Device names, serial numbers and the sensitive fields are never read. The
    device id and the user are identifiers and become pseudonyms.
    """

    source_code = "intune-devices"
    version = "intune-devices-1"
    prefix = "intune"
    label = "an Intune devices export"
    columns = (
        Column("device_id", "DeviceId", required=True),
        Column("compliance", "ComplianceState", required=True),
        Column("os", "OS", required=True),
        Column("last_contact", "LastContact", required=True),
        Column("management", "ManagementAgent"),
        Column("owner", "OwnerType"),
        Column("os_version", "OSVersion"),
        Column("upn", "UPN", aliases=("userPrincipalName",)),
        Column("encrypted", "IsEncrypted", aliases=("Encrypted",)),
    )
    json_fields = ("id", "complianceState", "operatingSystem", "lastSyncDateTime")

    def read_device(self, raw: Mapping[str, object], flags: Flags) -> ParsedFact:
        device_id = read_text(raw, "device_id")
        if device_id is None:
            raise RowError("DeviceId is empty")
        compliance = read_text(raw, "compliance")
        if compliance is None:
            raise RowError("ComplianceState is empty")
        system = read_text(raw, "os")
        if system is None:
            raise RowError("OS is empty")
        contact = read_time(raw, "last_contact", "LastContact", flags, required=True)
        value: dict[str, FactValue] = {
            "compliance": choice(compliance, COMPLIANCE_STATES),
            "os": prefix_choice(system, OS_PREFIXES),
            "os_version": clean_version(read_text(raw, "os_version")),
            "management": slug(raw.get("management"))[:40] or None,
            "owner": optional_choice(raw.get("owner"), OWNER_TYPES),
            "encrypted": read_flag(raw, "encrypted", "IsEncrypted"),
            "last_contact": iso(contact),
        }
        identifiers = {"device": device_id}
        user = read_text(raw, "upn")
        if user is not None:
            identifiers["user"] = user
        return ParsedFact("intune.device", value, identifiers)

    def parse_csv(self, table: CsvFile) -> ParseResult:
        dropped = any(slug(cell) in SENSITIVE_FIELDS for cell in table.header)
        flags = Flags()
        rejects = Rejects(self.prefix)
        devices = read_rows(table.rows(), self.read_device, flags, rejects)
        counts = self._counts(devices, dropped)
        return self.finish(devices, counts, rejects, flags, None)

    def parse_json(self, root: object) -> ParseResult:
        records = json_records(root)
        require_fields(records, self.json_fields)
        dropped = any(
            slug(name) in SENSITIVE_FIELDS
            for record in records
            if isinstance(record, dict)
            for name in record
        )
        captured_at, assumed = json_capture_time(root)
        flags = Flags(assumed_utc=assumed)
        rejects = Rejects(self.prefix)
        rows = json_rows(records, INTUNE_JSON_NAMES)
        devices = read_rows(rows, self.read_device, flags, rejects)
        counts = self._counts(devices, dropped)
        return self.finish(devices, counts, rejects, flags, captured_at)

    @staticmethod
    def _counts(devices: list[ParsedFact], dropped: bool) -> dict[str, FactValue]:
        return {
            "devices": len(devices),
            "compliant": _count_equal(devices, "compliance", "compliant"),
            "noncompliant": _count_equal(devices, "compliance", "noncompliant"),
            "windows": _count_equal(devices, "os", "windows"),
            "macos": _count_equal(devices, "os", "macos"),
            "ios": _count_equal(devices, "os", "ios"),
            "android": _count_equal(devices, "os", "android"),
            "personal": _count_equal(devices, "owner", "personal"),
            "with_user": sum(1 for device in devices if "user" in device.identifiers),
            "encryption_known": sum(
                1 for device in devices if device.value["encrypted"] is not None
            ),
            "encrypted": _count_true(devices, "encrypted"),
            "sensitive_fields_dropped": dropped,
        }


# --- 4. Conditional Access policies -----------------------------------------


def _words(value: object) -> list[str]:
    """The strings of a list, lower-cased."""
    if not isinstance(value, list):
        return []
    return [item.strip().lower() for item in value if isinstance(item, str)]


def _size(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _object(value: object) -> Mapping[str, object]:
    return value if isinstance(value, dict) else {}


class ConditionalAccessAdapter(MicrosoftAdapter):
    """Graph conditionalAccess/policies (JSON only).

    Policy names are never read. An empty list is reported as the tenant state
    `security-defaults`, never as a failure.
    """

    source_code = "conditional-access"
    version = "conditional-access-1"
    prefix = "ca"
    label = "a Conditional Access policies export"
    json_fields = ("state", "conditions")

    def read_policy(self, record: object, flags: Flags) -> ParsedFact:
        if not isinstance(record, dict):
            raise RowError("The record is not an object")
        state = record.get("state")
        if not isinstance(state, str) or not state.strip():
            raise RowError("state is empty")
        conditions = record.get("conditions")
        if not isinstance(conditions, dict):
            raise RowError("conditions must be an object")
        users = _object(conditions.get("users"))
        apps = _object(conditions.get("applications"))
        grant = _object(record.get("grantControls"))
        controls = _words(grant.get("builtInControls"))
        clients = set(_words(conditions.get("clientAppTypes")))
        modified = read_time(record, "modifiedDateTime", "modifiedDateTime", flags)
        value: dict[str, FactValue] = {
            "state": choice(state, POLICY_STATES),
            "all_users": "all" in _words(users.get("includeUsers")),
            "all_apps": "all" in _words(apps.get("includeApplications")),
            "requires_mfa": "mfa" in controls,
            "blocks": "block" in controls,
            "targets_roles": _size(users.get("includeRoles")) > 0,
            "exclusions": sum(
                _size(users.get(name))
                for name in ("excludeUsers", "excludeGroups", "excludeRoles")
            ),
            "legacy_clients": bool(clients & LEGACY_CLIENT_TYPES),
            "modified": iso(modified),
        }
        return ParsedFact("ca.policy", value)

    def parse_json(self, root: object) -> ParseResult:
        records = json_records(root)
        require_fields(records, self.json_fields)
        captured_at, assumed = json_capture_time(root)
        flags = Flags(assumed_utc=assumed)
        rejects = Rejects(self.prefix)
        policies: list[ParsedFact] = []
        for number, record in enumerate(records, start=1):
            with rejects.row(number):
                policies.append(self.read_policy(record, flags))
        rejects.require_usable(len(policies))
        tenant_state = "conditional-access" if policies else "security-defaults"
        counts: dict[str, FactValue] = {
            "policies": len(policies),
            "enabled": _count_equal(policies, "state", "enabled"),
            "report_only": _count_equal(policies, "state", "report-only"),
            "disabled": _count_equal(policies, "state", "disabled"),
            "tenant_state": tenant_state,
        }
        return self.finish(policies, counts, rejects, flags, captured_at)


# --- 5. Directory roles -------------------------------------------------------


def _assignment(
    role: str,
    user: str,
    enabled: bool | None,
    permanent: bool | None,
) -> ParsedFact:
    value: dict[str, FactValue] = {
        "role": role,
        "global_admin": role.lower() in GLOBAL_ADMIN_ROLES,
        "enabled": enabled,
        "permanent": permanent,
    }
    return ParsedFact("roles.assignment", value, {"user": user})


class DirectoryRolesAdapter(MicrosoftAdapter):
    """Directory roles with their members (JSON), or a manual list (CSV).

    The JSON is GET /directoryRoles?$expand=members. The CSV is the manual list
    of administrators: User principal name and Role, and optionally Enabled and
    Permanent.
    """

    source_code = "directory-roles"
    version = "directory-roles-1"
    prefix = "roles"
    label = "a directory roles export"
    columns = (
        Column("upn", "User principal name", required=True),
        Column("role", "Role", required=True, aliases=("Role name",)),
        Column("enabled", "Enabled", aliases=("accountEnabled",)),
        Column("permanent", "Permanent", aliases=("Permanent assignment",)),
    )
    json_fields = ("displayName", "members")

    def read_assignment(self, raw: Mapping[str, object], flags: Flags) -> ParsedFact:
        user = read_text(raw, "upn")
        if user is None:
            raise RowError("User principal name is empty")
        role = safe_text(raw.get("role"))
        if not role:
            raise RowError("Role is empty")
        return _assignment(
            role,
            user,
            read_flag(raw, "enabled", "Enabled"),
            read_flag(raw, "permanent", "Permanent"),
        )

    def read_role(self, record: object) -> tuple[list[ParsedFact], int]:
        """The assignments of one role, and how many members were not users."""
        if not isinstance(record, dict):
            raise RowError("The record is not an object")
        role = safe_text(record.get("displayName"))
        if not role:
            raise RowError("displayName is empty")
        members = record.get("members")
        if not isinstance(members, list):
            raise RowError("members must be a list")
        facts: list[ParsedFact] = []
        skipped = 0
        for member in members:
            user = read_text(_object(member), "userPrincipalName")
            if user is None:
                skipped += 1
                continue
            enabled = read_flag(_object(member), "accountEnabled", "accountEnabled")
            facts.append(_assignment(role, user, enabled, None))
        return facts, skipped

    def parse_csv(self, table: CsvFile) -> ParseResult:
        flags = Flags()
        rejects = Rejects(self.prefix)
        facts = read_rows(table.rows(), self.read_assignment, flags, rejects)
        counts = self._counts(facts, 0, "manual-csv")
        return self.finish(facts, counts, rejects, flags, None)

    def parse_json(self, root: object) -> ParseResult:
        records = json_records(root)
        require_fields(records, self.json_fields)
        captured_at, assumed = json_capture_time(root)
        flags = Flags(assumed_utc=assumed)
        rejects = Rejects(self.prefix)
        facts: list[ParsedFact] = []
        skipped = 0
        usable = 0
        for number, record in enumerate(records, start=1):
            with rejects.row(number):
                found, not_users = self.read_role(record)
                facts.extend(found)
                skipped += not_users
                usable += 1
        rejects.require_usable(usable)
        counts = self._counts(facts, skipped, "graph-json")
        return self.finish(facts, counts, rejects, flags, captured_at)

    @staticmethod
    def _counts(
        facts: list[ParsedFact],
        not_users: int,
        input_format: str,
    ) -> dict[str, FactValue]:
        users = {fact.identifiers["user"].lower() for fact in facts}
        admins = {
            fact.identifiers["user"].lower()
            for fact in facts
            if fact.value["global_admin"] is True
        }
        roles = {fact.value["role"] for fact in facts}
        return {
            "assignments": len(facts),
            "roles": len(roles),
            "users": len(users),
            "global_admins": len(admins),
            "non_user_members": not_users,
            "input_format": input_format,
        }


ADAPTERS: tuple[MicrosoftAdapter, ...] = (
    EntraRegistrationAdapter(),
    SecureScoreAdapter(),
    IntuneDevicesAdapter(),
    ConditionalAccessAdapter(),
    DirectoryRolesAdapter(),
)


def detect_source(data: bytes) -> str | None:
    """The source code of the one adapter that fits the file, or None.

    Detection looks at the header columns or the JSON fields only. A file that
    fits no adapter, or more than one, gives None.
    """
    sniffed = sniff(data)
    if sniffed is None:
        return None
    found = [a.source_code for a in ADAPTERS if a.matches(sniffed)]
    return found[0] if len(found) == 1 else None
