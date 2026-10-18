"""The device and endpoint rules, PC-DEV-01 to 05, PC-DEV-07, PC-END-01, 02 and 04.

The population DV is the devices seen within `active_days` of the capture time of
their export (the RMM inventory and the Intune export are each measured from
their own capture time). PC-DEV-06, PC-END-03 and PC-END-05 are unknown by
`automatic_unavailable` and are not in this module.
"""

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

from app.checks.model import (
    ABSENT,
    EMPTY_POPULATION,
    LifecycleEntry,
    Outcome,
    Row,
)
from app.checks.support import (
    Context,
    active_rows,
    count_of,
    decided,
    flag_of,
    no_source,
    oldest,
    share_of_known,
    share_outcome,
    text_of,
    unknown,
    within,
)

INVENTORY = "device-inventory"
INTUNE = "intune-devices"
DAYS = "active_days"


@dataclass(frozen=True)
class Device:
    """One active device, from the RMM inventory, Intune or both."""

    key: str
    os: str | None
    version: str | None
    encrypted: bool | None


def _either(first: bool | None, second: bool | None) -> bool | None:
    """Encrypted when either source says so; unknown only when neither says."""
    if first is True or second is True:
        return True
    if first is False or second is False:
        return False
    return None


def merged_devices(ctx: Context) -> tuple[list[Device], datetime | None] | None:
    """The active devices of both sources, one entry per pseudonymous device id.

    None when neither source was imported.
    """
    days = ctx.control.whole(DAYS)
    inventory, intune = ctx.source(INVENTORY), ctx.source(INTUNE)
    if inventory is None and intune is None:
        return None
    found: dict[str, Device] = {}
    sources = (
        (inventory, "last_seen", "os_build", "disk_encrypted"),
        (intune, "last_contact", "os_version", "encrypted"),
    )
    for source, time_column, version_column, flag_column in sources:
        if source is None:
            continue
        for row in active_rows(source, "device", time_column, days):
            key = text_of(row.get("device"))
            if key is None:
                continue
            before = found.get(key)
            os_name = text_of(row.get("os"))
            version = text_of(row.get(version_column))
            encrypted = flag_of(row.get(flag_column))
            if before is not None:
                os_name = before.os or os_name
                version = before.version or version
                encrypted = _either(before.encrypted, encrypted)
            found[key] = Device(key, os_name, version, encrypted)
    at = oldest(
        [
            inventory.captured_at if inventory is not None else None,
            intune.captured_at if intune is not None else None,
        ]
    )
    return list(found.values()), at


def dev_01(ctx: Context) -> Outcome:
    """Devices in both the RMM inventory and Intune, over the active in either."""
    days = ctx.control.whole(DAYS)
    inventory, intune = ctx.source(INVENTORY), ctx.source(INTUNE)
    if inventory is None or intune is None:
        return no_source(INVENTORY, INTUNE)

    def keys(source_rows: tuple[Row, ...]) -> set[str]:
        return {key for row in source_rows if (key := text_of(row.get("device")))}

    seen_rmm = keys(active_rows(inventory, "device", "last_seen", days))
    seen_mdm = keys(active_rows(intune, "device", "last_contact", days))
    either = seen_rmm | seen_mdm
    at = oldest([inventory.captured_at, intune.captured_at])
    if not either:
        return unknown(EMPTY_POPULATION, "No device was active in either export.", at)
    both = seen_rmm & seen_mdm
    return share_outcome(
        ctx.control, len(both), len(either), at, "active devices are in both exports"
    )


def dev_02(ctx: Context) -> Outcome:
    """No pending critical update, or a patch within the window."""
    inventory = ctx.source(INVENTORY)
    if inventory is None:
        return no_source(INVENTORY)
    control = ctx.control
    rows = active_rows(inventory, "device", "last_seen", control.whole(DAYS))
    patch_days = control.whole("patch_days")

    def patched(row: Row) -> bool | None:
        pending = count_of(row.get("pending_critical_updates"))
        recent = within(inventory.captured_at, row.get("last_patch"), patch_days)
        if pending == 0 or recent is True:
            return True
        if pending is None and recent is None:
            return None
        return False

    return share_of_known(
        control, rows, patched, inventory.captured_at, "active devices patched"
    )


def _lifecycle_end(
    table: tuple[LifecycleEntry, ...], device: Device
) -> LifecycleEntry | None:
    """The entry of the longest version prefix that matches the device."""
    best: LifecycleEntry | None = None
    for entry in table:
        if entry.os != device.os:
            continue
        if not (device.version or "").startswith(entry.version_prefix):
            continue
        if best is None or len(entry.version_prefix) > len(best.version_prefix):
            best = entry
    return best


def dev_03(ctx: Context) -> Outcome:
    """Devices past vendor support, from the shipped lifecycle table."""
    merged = merged_devices(ctx)
    if merged is None:
        return no_source(INVENTORY, INTUNE)
    devices, at = merged
    table = tuple(ctx.evidence.lifecycle)
    if not table:
        return unknown(
            ABSENT, "The lifecycle table of vendor end-of-support dates is empty.", at
        )
    if not devices:
        return unknown(EMPTY_POPULATION, "No device was active.", at)
    today = ctx.evidence.as_of.date()
    matched = past = 0
    for device in devices:
        entry = _lifecycle_end(table, device)
        if entry is None:
            continue
        matched += 1
        if entry.end_of_support < today:
            past += 1
    if not matched:
        return unknown(ABSENT, "No device matches the lifecycle table.", at)
    detail = f"{past} of {matched} devices are past vendor support"
    if matched < len(devices):
        detail += f"; {len(devices) - matched} are not in the table"
    if past == 0:
        return decided("pass", detail, at, past, matched)
    if Fraction(past, matched) <= Fraction(ctx.control.number("partial_share")):
        return decided("partial", detail, at, past, matched)
    return decided("fail", detail, at, past, matched)


def dev_04(ctx: Context) -> Outcome:
    """Share of active devices with disk encryption on (Intune or the RMM)."""
    merged = merged_devices(ctx)
    if merged is None:
        return no_source(INVENTORY, INTUNE)
    devices, at = merged
    rows: list[Row] = [{"encrypted": device.encrypted} for device in devices]
    return share_of_known(
        ctx.control,
        rows,
        lambda row: flag_of(row.get("encrypted")),
        at,
        "active devices encrypted",
    )


def dev_05(ctx: Context) -> Outcome:
    """Share of active Intune devices that are compliant (unknown state is not)."""
    intune = ctx.source(INTUNE)
    if intune is None:
        return no_source(INTUNE)
    rows = active_rows(intune, "device", "last_contact", ctx.control.whole(DAYS))

    def compliant(row: Row) -> bool | None:
        state = text_of(row.get("compliance"))
        return None if state is None else state == "compliant"

    return share_of_known(
        ctx.control, rows, compliant, intune.captured_at, "active devices compliant"
    )


def dev_07(ctx: Context) -> Outcome:
    """Share of active devices with at most the allowed local administrators."""
    inventory = ctx.source(INVENTORY)
    if inventory is None:
        return no_source(INVENTORY)
    control = ctx.control
    rows = active_rows(inventory, "device", "last_seen", control.whole(DAYS))
    limit = control.whole("max_local_admins")

    def few_admins(row: Row) -> bool | None:
        found = count_of(row.get("local_admin_count"))
        return None if found is None else found <= limit

    return share_of_known(
        control, rows, few_admins, inventory.captured_at, "active devices"
    )


def end_01(ctx: Context) -> Outcome:
    """Share of active Windows devices with anti-malware protection running."""
    inventory = ctx.source(INVENTORY)
    if inventory is None:
        return no_source(INVENTORY)
    days = ctx.control.whole(DAYS)
    rows = [
        row
        for row in active_rows(inventory, "device", "last_seen", days)
        if row.get("os") == "windows"
    ]

    def protected(row: Row) -> bool | None:
        state = text_of(row.get("av_status"))
        return None if state is None else state == "protected"

    return share_of_known(
        ctx.control, rows, protected, inventory.captured_at, "active Windows devices"
    )


def end_02(ctx: Context) -> Outcome:
    """Share of active devices whose protection signatures are recent."""
    inventory = ctx.source(INVENTORY)
    if inventory is None:
        return no_source(INVENTORY)
    control = ctx.control
    rows = active_rows(inventory, "device", "last_seen", control.whole(DAYS))
    window = control.whole("signature_days")

    def current(row: Row) -> bool | None:
        return within(inventory.captured_at, row.get("av_signature_date"), window)

    what = "active devices with current signatures"
    return share_of_known(control, rows, current, inventory.captured_at, what)


def end_04(ctx: Context) -> Outcome:
    """Share of active devices where tamper protection is on."""
    inventory = ctx.source(INVENTORY)
    if inventory is None:
        return no_source(INVENTORY)
    rows = active_rows(inventory, "device", "last_seen", ctx.control.whole(DAYS))
    return share_of_known(
        ctx.control,
        rows,
        lambda row: flag_of(row.get("tamper_protection")),
        inventory.captured_at,
        "active devices with tamper protection",
    )
