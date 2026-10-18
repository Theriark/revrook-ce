"""The generic and administrative source adapters (phase 4).

Six CSV contracts of our own, written so that an MSP can map the export of any
RMM, backup or network product onto them with a saved column mapping:

    device-inventory   devices, patching and antivirus
    backup-export      backup jobs and restore tests
    network-export     firewalls, firewall rules and Wi-Fi networks
    training-csv       security awareness training completions
    leavers-csv        people who left, and whether their account is still on
    exchange-export    Exchange Online settings, one record type per line

Each adapter is a table of fields (`Field`): the column, how to read it, and
whether it is an identifier. Reading follows phase 3: a row that cannot be read
is rejected on its own with a reason that names the column and never repeats
the content; a personal identifier (a user, a device, a mailbox, a mail domain,
a network name) goes into `identifiers` and the evidence store replaces it with
the client's pseudonym; free text such as serial numbers, client names and job
names is never read as text. Dates without a time zone are read as UTC and the
summary says so (`timezone_assumed_utc`).

A CSV file carries no capture time, so the evidence store uses the time given
with the upload (`capture_time_source` is `upload`). A file that starts with
`{` or `[` is refused: these sources have no JSON form.

The tables below are laid out by hand, one field or one count to a line, so the
formatter is switched off around them.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Self

from app.importers.base import FactValue, ImportRejectedError, ParsedFact, ParseResult
from app.importers.framework import (
    Column,
    Flags,
    MissingStructureError,
    Rejects,
    RowError,
    decode_text,
    iso,
    looks_like_json,
    missing_message,
    open_csv,
    optional_choice,
    prefix_choice,
    read_count,
    read_flag,
    read_rows,
    read_text,
    read_time,
    safe_text,
    slug,
    summary_fact,
)
from app.importers.microsoft import OS_PREFIXES, clean_version
from app.pseudonym import normalise_identifier

MAX_IDENTIFIER_LENGTH = 200
MAX_PORT = 65_535
ANY_WORDS = frozenset({"any", "*", "all", "anywhere", "internet", "0.0.0.0/0", "::/0"})
UNREAD_HEADERS = frozenset({"serial", "serialnumber", "clientname"})

Raw = Mapping[str, object]
Reader = Callable[[Raw, str, str, Flags], FactValue]


# --- how one cell is read ---------------------------------------------------


def read_flag_cell(raw: Raw, key: str, label: str, flags: Flags) -> FactValue:
    return read_flag(raw, key, label)


def read_count_cell(raw: Raw, key: str, label: str, flags: Flags) -> FactValue:
    return read_count(raw, key, label)


def read_time_cell(raw: Raw, key: str, label: str, flags: Flags) -> FactValue:
    return iso(read_time(raw, key, label, flags))


def read_text_cell(raw: Raw, key: str, label: str, flags: Flags) -> FactValue:
    return safe_text(raw.get(key), label=label) or None


def read_version_cell(raw: Raw, key: str, label: str, flags: Flags) -> FactValue:
    return clean_version(read_text(raw, key))


def read_system_cell(raw: Raw, key: str, label: str, flags: Flags) -> FactValue:
    text = read_text(raw, key)
    return prefix_choice(text, OS_PREFIXES) if text is not None else None


def read_configured_cell(raw: Raw, key: str, label: str, flags: Flags) -> FactValue:
    """Whether a column has a value, never the value (a host name or address).

    Unknown (None) when the file has no such column at all.
    """
    if key not in raw:
        return None
    return read_text(raw, key) is not None


def read_source_cell(raw: Raw, key: str, label: str, flags: Flags) -> FactValue:
    """`any` when a rule's source is the whole internet, else `restricted`."""
    text = read_text(raw, key)
    if text is None:
        return None
    return "any" if text.lower() in ANY_WORDS else "restricted"


def read_port_cell(raw: Raw, key: str, label: str, flags: Flags) -> FactValue:
    """A port number, a range such as 1024-2048, or `any`."""
    text = read_text(raw, key)
    if text is None:
        return None
    if text.lower() in ANY_WORDS:
        return "any"
    first, dash, last = text.partition("-")
    parts = [first, last] if dash else [first]
    if all(p.isdecimal() and len(p) <= 5 and int(p) <= MAX_PORT for p in parts):
        return f"{int(first)}-{int(last)}" if dash else int(first)
    raise RowError(f"{label} must be a port number, a range or any")


def word_reader(allowed: Mapping[str, str]) -> Reader:
    """A word of a fixed list (`other` for any other word); None when empty."""

    def read(raw: Raw, key: str, label: str, flags: Flags) -> FactValue:
        return optional_choice(raw.get(key), allowed)

    return read


def read_nothing(raw: Raw, key: str, label: str, flags: Flags) -> FactValue:
    """The reader of a field that no record type reads (the record_type column)."""
    return None  # pragma: no cover


# --- the table ---------------------------------------------------------------


@dataclass(frozen=True)
class Field:
    """One column of a contract and what becomes of it.

    `target` makes it an identifier: the cell is named in `identifiers` under
    that name and never in a value. `required` is a row rule: an empty cell
    rejects the row (for an identifier, when no column of the same target has a
    value). Whether the column must be in the header is `column.required`.
    `kinds` limits the field to some record types (None: every record).
    """

    column: Column
    read: Reader = read_nothing
    target: str | None = None
    required: bool = False
    kinds: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Count:
    """One number of the summary: the facts that match, counted.

    op `rows` counts the facts; `equals` those whose value `key` is `arg`;
    `known` those whose value is not None; `positive` those above zero.
    `where` adds conditions on other values of the same fact.
    """

    name: str
    op: str
    key: str = ""
    arg: FactValue = None
    kind: str | None = None
    where: tuple[tuple[str, FactValue], ...] = ()


def columns_of(fields: Sequence[Field]) -> tuple[Column, ...]:
    """The columns of a contract, in the order of its fields."""
    return tuple(item.column for item in fields)


def counts_as(fact: ParsedFact, count: Count) -> bool:
    if count.kind is not None and not fact.key.endswith(f".{count.kind}"):
        return False
    if any(fact.value.get(key) != wanted for key, wanted in count.where):
        return False
    if count.op == "rows":
        return True
    value = fact.value.get(count.key)
    if count.op == "known":
        return value is not None
    if count.op == "positive":
        return isinstance(value, int) and not isinstance(value, bool) and value > 0
    return value is not None and value == count.arg and type(value) is type(count.arg)


class CsvAdapter:
    """What the six adapters share: a CSV read through a table of fields."""

    source_code: str
    version: str
    prefix: str
    label: str
    fields: tuple[Field, ...] = ()
    columns: tuple[Column, ...] = ()
    kinds: tuple[str, ...] = ("row",)
    kind_key: str | None = None
    kind_words: Mapping[str, str] | None = None
    kind_default: str | None = None
    any_of: tuple[tuple[str, ...], ...] = ()
    counts: tuple[Count, ...] = ()
    distinct: tuple[tuple[str, str], ...] = ()
    newest: tuple[tuple[str, str], ...] = ()

    def __init__(self, mapping: Mapping[str, str] | None = None) -> None:
        self.mapping: dict[str, str] = dict(mapping or {})

    def with_mapping(self, mapping: Mapping[str, str]) -> Self:
        """The same adapter reading a CSV through a saved column mapping."""
        return type(self)(mapping)

    def parse(self, data: bytes, max_rows: int) -> ParseResult:
        text = decode_text(data)
        if looks_like_json(text):
            raise ImportRejectedError(f"The file must be a CSV file ({self.label}).")
        table = open_csv(text, self.columns, max_rows, self.mapping)
        for group in self.any_of:
            if not any(key in table.positions for key in group):
                labels = [c.label for c in self.columns if c.key in group]
                raise MissingStructureError(missing_message([" or ".join(labels)]))
        flags = Flags()
        rejects = Rejects(self.prefix)
        facts = read_rows(table.rows(), self.read_row, flags, rejects)
        counts = self.summarise(facts, table.header)
        summary = summary_fact(
            self.prefix, counts, rejects, flags, capture_in_file=False
        )
        return ParseResult(facts=(*facts, *rejects.facts, summary))

    def kind_of(self, raw: Raw) -> str:
        """The record type of a row (the only one, for a single-kind contract)."""
        if self.kind_key is None or self.kind_words is None:
            return self.kinds[0]
        word = read_text(raw, self.kind_key)
        if word is None:
            if self.kind_default is None:
                raise RowError(f"{self.kind_key} is empty")
            return self.kind_default
        found = self.kind_words.get(slug(word))
        if found is None:
            listed = ", ".join(self.kinds)
            raise RowError(f"{self.kind_key} must be one of {listed}")
        return found

    def read_row(self, raw: Raw, flags: Flags) -> ParsedFact:
        kind = self.kind_of(raw)
        value: dict[str, FactValue] = {}
        identifiers: dict[str, str] = {}
        needed: dict[str, list[str]] = {}
        for item in self.fields:
            if item.kinds is not None and kind not in item.kinds:
                continue
            key, label = item.column.key, item.column.label
            if item.target is not None:
                if item.required:
                    needed.setdefault(item.target, []).append(label)
                text = read_text(raw, key)
                if text is not None and len(text) > MAX_IDENTIFIER_LENGTH:
                    raise RowError(f"{label} is too long")
                if text is not None:
                    identifiers.setdefault(item.target, text)
                continue
            cell = item.read(raw, key, label, flags)
            if cell is None and item.required:
                raise RowError(f"{label} is empty")
            value[key] = cell
        for target, labels in needed.items():
            if target not in identifiers:
                raise RowError(f"{' or '.join(labels)} is empty")
        return ParsedFact(f"{self.prefix}.{kind}", value, identifiers)

    def summarise(
        self, facts: Sequence[ParsedFact], header: Iterable[str]
    ) -> dict[str, FactValue]:
        """The counts of one file, in the order the contract lists them."""
        summary: dict[str, FactValue] = {}
        for count in self.counts:
            summary[count.name] = sum(1 for f in facts if counts_as(f, count))
        for name, target in self.distinct:
            people = {
                normalise_identifier(fact.identifiers[target])
                for fact in facts
                if target in fact.identifiers
            }
            summary[name] = len(people)
        for name, key in self.newest:
            stamps: list[str] = []
            for fact in facts:
                stamp = fact.value.get(key)
                if isinstance(stamp, str):
                    stamps.append(stamp)
            summary[name] = max(stamps, default=None)
        unread = any(slug(cell) in UNREAD_HEADERS for cell in header)
        summary["unread_columns_present"] = unread
        return summary


# --- 6. device inventory, patch and antivirus --------------------------------

FORM_FACTORS = {
    "server": "server",
    "workstation": "workstation",
    "desktop": "workstation",
    "laptop": "workstation",
    "mobile": "mobile",
    "phone": "mobile",
    "tablet": "mobile",
}
PATCH_STATES = {
    "uptodate": "up_to_date",
    "current": "up_to_date",
    "pending": "pending",
    "unknown": "unknown",
}
AV_STATES = {"protected": "protected", "disabled": "disabled", "unknown": "unknown"}


class DeviceInventoryAdapter(CsvAdapter):
    """Device inventory with patch and antivirus state (CSV).

    One row per device. The serial number and the client name are never read.
    The device (a host name or an id) and the user are identifiers.
    """

    source_code = "device-inventory"
    version = "device-inventory-1"
    prefix = "inventory"
    label = "a device inventory, patch and antivirus export"
    kinds = ("device",)
    # fmt: off
    fields = (
        Field(Column("device_id", "device_id", False, ("Device Id", "Asset id")),
              target="device", required=True),
        Field(Column("hostname", "hostname", False, ("Computer name", "Device name")),
              target="device", required=True),
        Field(Column("os", "os", True), read_system_cell, required=True),
        Field(Column("form_factor", "form_factor"), word_reader(FORM_FACTORS)),
        Field(Column("os_build", "os_build"), read_version_cell),
        Field(Column("last_seen", "last_seen", True, ("last_seen_utc",)),
              read_time_cell, required=True),
        Field(Column("patch_status", "patch_status", True), word_reader(PATCH_STATES)),
        Field(Column("pending_critical_updates", "pending_critical_updates", True,
                     ("pending_critical",)), read_count_cell),
        Field(Column("last_patch", "last_patch", False, ("last_patch_utc",)),
              read_time_cell),
        Field(Column("av_product", "av_product", True), read_text_cell),
        Field(Column("av_status", "av_status", True), word_reader(AV_STATES)),
        Field(Column("av_signature_date", "av_signature_date", True,
                     ("av_def_date_utc",)), read_time_cell),
        Field(Column("disk_encrypted", "disk_encrypted", True), read_flag_cell),
        Field(Column("local_admin_count", "local_admin_count"), read_count_cell),
        Field(Column("tamper_protection", "tamper_protection"), read_flag_cell),
        Field(Column("dns_filter_active", "dns_filter_active"), read_flag_cell),
        Field(Column("log_forwarding", "log_forwarding"), read_flag_cell),
        Field(Column("user", "user", False, ("UPN", "user_principal_name")),
              target="user"),
    )
    columns = columns_of(fields)
    any_of = (("device_id", "hostname"),)
    counts = (
        Count("devices", "rows"),
        Count("windows", "equals", "os", "windows"),
        Count("macos", "equals", "os", "macos"),
        Count("ios", "equals", "os", "ios"),
        Count("android", "equals", "os", "android"),
        Count("linux", "equals", "os", "linux"),
        Count("servers", "equals", "form_factor", "server"),
        Count("patch_up_to_date", "equals", "patch_status", "up_to_date"),
        Count("patch_pending", "equals", "patch_status", "pending"),
        Count("with_pending_critical", "positive", "pending_critical_updates"),
        Count("pending_critical_known", "known", "pending_critical_updates"),
        Count("last_patch_known", "known", "last_patch"),
        Count("av_protected", "equals", "av_status", "protected"),
        Count("av_disabled", "equals", "av_status", "disabled"),
        Count("encrypted", "equals", "disk_encrypted", True),
        Count("encryption_known", "known", "disk_encrypted"),
        Count("local_admin_known", "known", "local_admin_count"),
        Count("tamper_protected", "equals", "tamper_protection", True),
        Count("tamper_known", "known", "tamper_protection"),
        Count("dns_filtered", "equals", "dns_filter_active", True),
        Count("dns_filter_known", "known", "dns_filter_active"),
        Count("log_forwarded", "equals", "log_forwarding", True),
        Count("log_forwarding_known", "known", "log_forwarding"),
    )
    newest = (("last_seen_newest", "last_seen"),)
    # fmt: on

    def summarise(
        self, facts: Sequence[ParsedFact], header: Iterable[str]
    ) -> dict[str, FactValue]:
        summary = super().summarise(facts, header)
        summary["with_user"] = sum(1 for fact in facts if "user" in fact.identifiers)
        return summary


# --- 7. backup jobs and restore tests ------------------------------------------

BACKUP_RESULTS = {
    "success": "success",
    "ok": "success",
    "warning": "warning",
    "failed": "failed",
    "failure": "failed",
    "error": "failed",
}
RESTORE_RESULTS = {
    "success": "success",
    "passed": "success",
    "pass": "success",
    "failed": "failed",
    "fail": "failed",
}
ASSET_TYPES = {
    "server": "server",
    "workstation": "workstation",
    "database": "database",
    "exchange": "exchange",
    "onedrive": "onedrive",
    "sharepoint": "sharepoint",
    "teams": "teams",
}


class BackupAdapter(CsvAdapter):
    """Backup jobs, with the extra columns of the control library (CSV).

    One row per backup job. The system and the job are identifiers: they are
    counted but never stored by name.
    """

    source_code = "backup-export"
    version = "backup-export-1"
    prefix = "backup"
    label = "a backup jobs export"
    kinds = ("job",)
    # fmt: off
    fields = (
        Field(Column("system_or_device", "system_or_device", True,
                     ("asset_id", "System", "Device")),
              target="asset", required=True),
        Field(Column("backup_job", "backup_job", True, ("job_name", "Job")),
              target="job"),
        Field(Column("last_success", "last_success", True, ("last_success_utc",)),
              read_time_cell),
        Field(Column("last_result", "last_result", True, ("last_status", "Result")),
              word_reader(BACKUP_RESULTS)),
        Field(Column("retention_days", "retention_days", True), read_count_cell),
        Field(Column("restore_test_date", "restore_test_date", True,
                     ("last_restore_test_utc",)), read_time_cell),
        Field(Column("asset_type", "asset_type"), word_reader(ASSET_TYPES)),
        Field(Column("schedule_hours", "schedule_hours"), read_count_cell),
        Field(Column("encrypted", "encrypted"), read_flag_cell),
        Field(Column("immutable", "immutable"), read_flag_cell),
        Field(Column("offsite", "offsite"), read_flag_cell),
        Field(Column("restore_test_result", "restore_test_result"),
              word_reader(RESTORE_RESULTS)),
    )
    columns = columns_of(fields)
    counts = (
        Count("jobs", "rows"),
        Count("success", "equals", "last_result", "success"),
        Count("warning", "equals", "last_result", "warning"),
        Count("failed", "equals", "last_result", "failed"),
        Count("schedule_known", "known", "schedule_hours"),
        Count("retention_known", "known", "retention_days"),
        Count("encrypted", "equals", "encrypted", True),
        Count("encryption_known", "known", "encrypted"),
        Count("immutable", "equals", "immutable", True),
        Count("immutable_known", "known", "immutable"),
        Count("offsite", "equals", "offsite", True),
        Count("offsite_known", "known", "offsite"),
        Count("restore_tested", "known", "restore_test_date"),
        Count("restore_passed", "equals", "restore_test_result", "success"),
        Count("restore_failed", "equals", "restore_test_result", "failed"),
        Count("exchange", "equals", "asset_type", "exchange"),
        Count("onedrive", "equals", "asset_type", "onedrive"),
        Count("sharepoint", "equals", "asset_type", "sharepoint"),
        Count("teams", "equals", "asset_type", "teams"),
    )
    distinct = (("assets", "asset"),)
    newest = (("last_success_newest", "last_success"),)
    # fmt: on


# --- network export --------------------------------------------------------------

NETWORK_KINDS = {
    "device": "device",
    "firewall": "device",
    "rule": "rule",
    "firewallrule": "rule",
    "ssid": "ssid",
    "wifi": "ssid",
    "wireless": "ssid",
}
DIRECTIONS = {
    "inbound": "inbound",
    "in": "inbound",
    "ingress": "inbound",
    "incoming": "inbound",
    "outbound": "outbound",
    "out": "outbound",
}
ACTIONS = {
    "allow": "allow",
    "accept": "allow",
    "permit": "allow",
    "deny": "deny",
    "drop": "deny",
    "block": "deny",
    "reject": "deny",
}
SECURITY_MODES = {
    "open": "open",
    "none": "open",
    "wep": "wep",
    "wpa": "wpa",
    "wpapsk": "wpa",
    "wpa2": "wpa2",
    "wpa2psk": "wpa2",
    "wpa2personal": "wpa2",
    "wpa2enterprise": "wpa2-enterprise",
    "wpa3": "wpa3",
    "wpa3personal": "wpa3",
    "wpa3sae": "wpa3",
    "wpa3enterprise": "wpa3-enterprise",
    "wpa2wpa3": "wpa2-wpa3",
    "owe": "owe",
}
DEVICE = ("device",)
RULE = ("rule",)
SSID = ("ssid",)


class NetworkAdapter(CsvAdapter):
    """Network export: devices, firewall rules and Wi-Fi networks (CSV).

    One file holds three kinds of line, told apart by the column record_type,
    which the file must have (`device`, `rule` or `ssid`; an empty cell means
    `device`). The network name (SSID) and the device are identifiers; the
    syslog target is reduced to whether one is set.
    """

    source_code = "network-export"
    version = "network-export-1"
    prefix = "network"
    label = "a network export"
    kinds = ("device", "rule", "ssid")
    kind_key = "record_type"
    kind_words = NETWORK_KINDS
    kind_default = "device"
    # fmt: off
    fields = (
        Field(Column("record_type", "record_type", True, ("Type", "Record")),
              kinds=()),
        Field(Column("device_id", "device_id", False, ("Device", "Hostname")),
              target="device", required=True, kinds=DEVICE),
        Field(Column("perimeter", "perimeter", False, ("is_perimeter",)),
              read_flag_cell, kinds=DEVICE),
        Field(Column("firmware_release_date", "firmware_release_date", False,
                     ("firmware_release_utc",)), read_time_cell, kinds=DEVICE),
        Field(Column("end_of_support_date", "end_of_support_date"),
              read_time_cell, kinds=DEVICE),
        Field(Column("wan_admin_enabled", "wan_admin_enabled"),
              read_flag_cell, kinds=DEVICE),
        Field(Column("default_credentials_flag", "default_credentials_flag"),
              read_flag_cell, kinds=DEVICE),
        Field(Column("syslog_target", "syslog_target"),
              read_configured_cell, kinds=DEVICE),
        Field(Column("rule_enabled", "rule_enabled", False, ("enabled",)),
              read_flag_cell, required=True, kinds=RULE),
        Field(Column("direction", "direction"),
              word_reader(DIRECTIONS), required=True, kinds=RULE),
        Field(Column("action", "action"),
              word_reader(ACTIONS), required=True, kinds=RULE),
        Field(Column("source", "source"), read_source_cell, kinds=RULE),
        Field(Column("destination_port", "destination_port", False, ("port",)),
              read_port_cell, kinds=RULE),
        Field(Column("ssid", "ssid"), target="ssid", required=True, kinds=SSID),
        Field(Column("security_mode", "security_mode"),
              word_reader(SECURITY_MODES), required=True, kinds=SSID),
        Field(Column("guest_isolated", "guest_isolated"),
              read_flag_cell, kinds=SSID),
        Field(Column("guest_ssid", "guest_ssid"), read_flag_cell, kinds=SSID),
    )
    columns = columns_of(fields)
    any_of = (("device_id", "rule_enabled", "ssid"),)
    counts = (
        Count("devices", "rows", kind="device"),
        Count("perimeter_devices", "equals", "perimeter", True, "device"),
        Count("wan_admin_enabled", "equals", "wan_admin_enabled", True, "device"),
        Count("default_credentials", "equals", "default_credentials_flag", True,
              "device"),
        Count("syslog_configured", "equals", "syslog_target", True, "device"),
        Count("rules", "rows", kind="rule"),
        Count("rules_enabled", "equals", "rule_enabled", True, "rule"),
        Count("rules_inbound", "equals", "direction", "inbound", "rule"),
        Count("rules_allow", "equals", "action", "allow", "rule"),
        Count("rules_any_source", "equals", "source", "any", "rule"),
        Count("ssids", "rows", kind="ssid"),
        Count("ssids_open", "equals", "security_mode", "open", "ssid"),
        Count("ssids_guest", "equals", "guest_ssid", True, "ssid"),
        Count("ssids_guest_isolated", "equals", "guest_isolated", True, "ssid"),
    )
    newest = (("firmware_newest", "firmware_release_date"),)
    # fmt: on


# --- training and leavers --------------------------------------------------------


class TrainingAdapter(CsvAdapter):
    """Security awareness training completions (CSV): who, which course, when."""

    source_code = "training-csv"
    version = "training-csv-1"
    prefix = "training"
    label = "a training completions export"
    kinds = ("completion",)
    # fmt: off
    fields = (
        Field(Column("user_id", "user_id", True, ("User principal name", "UPN")),
              target="user", required=True),
        Field(Column("course", "course", True, ("Course name", "Training")),
              read_text_cell),
        Field(Column("completed_utc", "completed_utc", True,
                     ("completed", "Completed on", "Completion date")),
              read_time_cell, required=True),
    )
    columns = columns_of(fields)
    counts = (Count("completions", "rows"),)
    distinct = (("users", "user"),)
    newest = (("completed_newest", "completed_utc"),)
    # fmt: on


class LeaversAdapter(CsvAdapter):
    """People who left (CSV): who, when, and optionally whether the account is on."""

    source_code = "leavers-csv"
    version = "leavers-csv-1"
    prefix = "leavers"
    label = "a leavers list"
    kinds = ("leaver",)
    # fmt: off
    fields = (
        Field(Column("user_id", "user_id", True, ("User principal name", "UPN")),
              target="user", required=True),
        Field(Column("leave_date", "leave_date", True,
                     ("Leaving date", "Last working day")),
              read_time_cell, required=True),
        Field(Column("account_enabled", "account_enabled", False, ("accountEnabled",)),
              read_flag_cell),
    )
    columns = columns_of(fields)
    counts = (
        Count("leavers", "rows"),
        Count("account_state_known", "known", "account_enabled"),
        Count("still_enabled", "equals", "account_enabled", True),
    )
    distinct = (("users", "user"),)
    newest = (("leave_newest", "leave_date"),)
    # fmt: on


# --- Exchange Online -----------------------------------------------------------------

EXCHANGE_KINDS = {
    "dkim": "dkim",
    "policy": "policy",
    "mailbox": "mailbox",
    "audit": "audit",
    "alert": "alert",
}
POLICY_TYPES = {
    "antiphish": "anti-phish",
    "safelinks": "safe-links",
    "safeattachments": "safe-attachments",
    "preset": "preset",
    "outboundspam": "outbound-spam",
}
FORWARDING_MODES = {"off": "off", "on": "on", "automatic": "automatic"}
RECIPIENT_TYPES = {
    "usermailbox": "user",
    "user": "user",
    "sharedmailbox": "shared",
    "shared": "shared",
    "roommailbox": "room",
    "equipmentmailbox": "equipment",
}
ALERT_KINDS = {
    "adminrole": "admin-role",
    "adminroleassignment": "admin-role",
    "newadminroleassignment": "admin-role",
    "forwardingrule": "forwarding-rule",
    "mailforwardingrule": "forwarding-rule",
    "newmailforwardingrule": "forwarding-rule",
    "riskysignin": "risky-sign-in",
}
DKIM = ("dkim",)
POLICY = ("policy",)
MAILBOX = ("mailbox",)
AUDIT = ("audit",)
ALERT = ("alert",)


class ExchangeAdapter(CsvAdapter):
    """Exchange Online settings (CSV), one record type per line.

    The column record_type says what a line is: `dkim` (a mail domain and
    whether signing is on), `policy` (anti-phishing, safe links, safe
    attachments, a preset or the outbound spam policy), `mailbox`, `audit` (the
    audit settings of the tenant) or `alert` (a protection alert). Domains and
    mailboxes are identifiers.
    """

    source_code = "exchange-export"
    version = "exchange-export-1"
    prefix = "exchange"
    label = "an Exchange Online settings export"
    kinds = ("dkim", "policy", "mailbox", "audit", "alert")
    kind_key = "record_type"
    kind_words = EXCHANGE_KINDS
    # fmt: off
    fields = (
        Field(Column("record_type", "record_type", True, ("Type",)), kinds=()),
        Field(Column("domain", "domain", False, ("Domain",)),
              target="domain", required=True, kinds=DKIM),
        Field(Column("enabled", "enabled", False, ("Enabled",)),
              read_flag_cell, required=True, kinds=(*DKIM, *POLICY)),
        Field(Column("policy_type", "policy_type", False, ("Policy",)),
              word_reader(POLICY_TYPES), required=True, kinds=POLICY),
        Field(Column("auto_forwarding_mode", "auto_forwarding_mode"),
              word_reader(FORWARDING_MODES), kinds=POLICY),
        Field(Column("mailbox", "mailbox", False, ("Mailbox id", "Identity")),
              target="mailbox", required=True, kinds=MAILBOX),
        Field(Column("recipient_type", "recipient_type"),
              word_reader(RECIPIENT_TYPES), required=True, kinds=MAILBOX),
        Field(Column("forwarding_external", "forwarding_external"),
              read_flag_cell, kinds=MAILBOX),
        Field(Column("account_enabled", "account_enabled"),
              read_flag_cell, kinds=MAILBOX),
        Field(Column("unified_audit_log_enabled", "unified_audit_log_enabled"),
              read_flag_cell, required=True, kinds=AUDIT),
        Field(Column("audit_disabled", "audit_disabled"),
              read_flag_cell, kinds=AUDIT),
        Field(Column("alert_kind", "alert_kind"),
              word_reader(ALERT_KINDS), required=True, kinds=ALERT),
        Field(Column("disabled", "disabled", False, ("Disabled",)),
              read_flag_cell, kinds=ALERT),
        Field(Column("recipient_count", "recipient_count"),
              read_count_cell, kinds=ALERT),
        Field(Column("last_acknowledged", "last_acknowledged"),
              read_time_cell, kinds=ALERT),
    )
    columns = columns_of(fields)
    counts = (
        Count("dkim_domains", "rows", kind="dkim"),
        Count("dkim_enabled", "equals", "enabled", True, "dkim"),
        Count("policies", "rows", kind="policy"),
        Count("anti_phish_enabled", "equals", "enabled", True, "policy",
              (("policy_type", "anti-phish"),)),
        Count("safe_links_enabled", "equals", "enabled", True, "policy",
              (("policy_type", "safe-links"),)),
        Count("safe_attachments_enabled", "equals", "enabled", True, "policy",
              (("policy_type", "safe-attachments"),)),
        Count("preset_enabled", "equals", "enabled", True, "policy",
              (("policy_type", "preset"),)),
        Count("auto_forwarding_off", "equals", "auto_forwarding_mode", "off", "policy",
              (("policy_type", "outbound-spam"),)),
        Count("mailboxes", "rows", kind="mailbox"),
        Count("shared_mailboxes", "equals", "recipient_type", "shared", "mailbox"),
        Count("shared_mailboxes_enabled", "equals", "account_enabled", True, "mailbox",
              (("recipient_type", "shared"),)),
        Count("forwarding_external", "equals", "forwarding_external", True, "mailbox"),
        Count("audit_records", "rows", kind="audit"),
        Count("audit_ingestion_enabled", "equals", "unified_audit_log_enabled", True,
              "audit"),
        Count("alerts", "rows", kind="alert"),
        Count("alerts_with_recipient", "positive", "recipient_count", None, "alert"),
        Count("alert_admin_role_enabled", "equals", "disabled", False, "alert",
              (("alert_kind", "admin-role"),)),
        Count("alert_forwarding_rule_enabled", "equals", "disabled", False, "alert",
              (("alert_kind", "forwarding-rule"),)),
        Count("alert_risky_sign_in_enabled", "equals", "disabled", False, "alert",
              (("alert_kind", "risky-sign-in"),)),
    )
    newest = (("alert_acknowledged_newest", "last_acknowledged"),)
    # fmt: on


ADAPTERS: tuple[CsvAdapter, ...] = (
    DeviceInventoryAdapter(),
    BackupAdapter(),
    NetworkAdapter(),
    TrainingAdapter(),
    LeaversAdapter(),
    ExchangeAdapter(),
)
