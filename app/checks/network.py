"""The network rules, PC-NET-01 to PC-NET-05.

The perimeter devices are the `device` rows of the network export flagged
`perimeter`. A population that is empty is not a pass: PC-NET-01 and PC-NET-03 are
unknown with the reason empty_population, and PC-NET-04 for an export without Wi-Fi
networks is absent (a named reviewer may mark it not applicable).
"""

from collections.abc import Collection

from app.checks.model import (
    EMPTY_POPULATION,
    UNRESOLVED,
    Outcome,
    Row,
    SourceFacts,
    Status,
    Value,
)
from app.checks.support import (
    Context,
    absent,
    active_rows,
    count_outcome,
    decided,
    flag_of,
    no_source,
    parse_time,
    share_of_known,
    text_of,
    unknown,
    within,
    worst_of,
)

NETWORK = "network-export"
INVENTORY = "device-inventory"


def perimeter_devices(source: SourceFacts) -> tuple[Row, ...] | None:
    """The perimeter devices; None when the export does not say which they are."""
    devices = source.rows("device")
    flags = [flag_of(row.get("perimeter")) for row in devices]
    if all(flag is None for flag in flags):
        return None
    return tuple(row for row, flag in zip(devices, flags, strict=True) if flag)


def net_01(ctx: Context) -> Outcome:
    """Perimeter firewall firmware: recent enough and not past end of support."""
    source = ctx.source(NETWORK)
    if source is None:
        return no_source(NETWORK)
    at = source.captured_at
    devices = perimeter_devices(source)
    if devices is None:
        return absent("The network export does not say which devices are perimeter.")
    if not devices:
        return unknown(EMPTY_POPULATION, "The export lists no perimeter firewall.", at)
    pass_days = ctx.control.whole("pass_days")
    partial_days = ctx.control.whole("partial_days")

    def state(row: Row) -> Status | None:
        released = within(at, row.get("firmware_release_date"), partial_days)
        if released is None:
            return None
        support_ends = parse_time(row.get("end_of_support_date"))
        if released is False or (support_ends is not None and support_ends < at):
            return "fail"
        recent = within(at, row.get("firmware_release_date"), pass_days)
        return "pass" if recent else "partial"

    states = [state(row) for row in devices]
    return worst_of(states, at, "perimeter firewalls have supported, recent firmware")


def _port_hits(value: Value, risky: Collection[int]) -> bool | None:
    """Whether a rule's destination port covers a risky port."""
    if value is None:
        return None
    if value == "any":
        return True
    if isinstance(value, int) and not isinstance(value, bool):
        return value in risky
    if isinstance(value, str):
        first, _, last = value.partition("-")
        if first.isdecimal() and last.isdecimal():
            return any(int(first) <= port <= int(last) for port in risky)
    return None


def _rule_hits(row: Row, risky: Collection[int]) -> bool | None:
    """Whether a rule is enabled, inbound, allowing, from any source, to a risky port.

    False as soon as one condition is known not to hold; None when no condition is
    known to fail and one cannot be told.
    """
    enabled = flag_of(row.get("rule_enabled"))
    direction = text_of(row.get("direction"))
    action = text_of(row.get("action"))
    scope = text_of(row.get("source"))
    conditions = [
        enabled,
        None if direction is None else direction == "inbound",
        None if action is None else action == "allow",
        None if scope is None else scope == "any",
        _port_hits(row.get("destination_port"), risky),
    ]
    if any(condition is False for condition in conditions):
        return False
    if any(condition is None for condition in conditions):
        return None
    return True


def net_02(ctx: Context) -> Outcome:
    """Enabled inbound allow rules from anywhere to a risky port: none is wanted."""
    source = ctx.source(NETWORK)
    if source is None:
        return no_source(NETWORK)
    rules = source.rows("rule")
    if not rules:
        return absent("The network export has no firewall rules.")
    risky = ctx.control.whole_list("risk_ports")
    hits = [_rule_hits(row, risky) for row in rules]
    found = sum(1 for hit in hits if hit)
    unresolved = sum(1 for hit in hits if hit is None)
    what = "rules open a risky port to the whole internet"
    return count_outcome(
        ctx.control, found, unresolved, source.captured_at, what, len(rules)
    )


def net_03(ctx: Context) -> Outcome:
    """No perimeter device exposes its management or keeps a default login."""
    source = ctx.source(NETWORK)
    if source is None:
        return no_source(NETWORK)
    at = source.captured_at
    devices = perimeter_devices(source)
    if devices is None:
        return absent("The network export does not say which devices are perimeter.")
    if not devices:
        return unknown(EMPTY_POPULATION, "The export lists no perimeter firewall.", at)
    flags = [
        flag
        for row in devices
        for flag in (
            flag_of(row.get("wan_admin_enabled")),
            flag_of(row.get("default_credentials_flag")),
        )
    ]
    detail = f"{len(devices)} perimeter devices checked"
    if any(flag is True for flag in flags):
        return decided("fail", detail + "; one is exposed or has a default login", at)
    if any(flag is None for flag in flags):
        return unknown(UNRESOLVED, detail + "; some flags are missing", at)
    return decided("pass", detail, at, len(devices), len(devices))


def net_04(ctx: Context) -> Outcome:
    """Wi-Fi: no open or obsolete network, and every guest network isolated."""
    source = ctx.source(NETWORK)
    if source is None:
        return no_source(NETWORK)
    at = source.captured_at
    networks = source.rows("ssid")
    modes = [text_of(row.get("security_mode")) for row in networks]
    if all(mode is None for mode in modes):
        return absent("The network export has no Wi-Fi network.")
    obsolete = ctx.control.words("obsolete_modes")
    guests = [row for row in networks if row.get("guest_ssid") is True]
    isolated = [flag_of(row.get("guest_isolated")) for row in guests]
    detail = f"{len(networks)} Wi-Fi networks checked"
    open_network = any(mode in obsolete for mode in modes)
    if open_network or any(flag is False for flag in isolated):
        return decided("fail", detail + "; one is open or not separated", at)
    if any(mode is None for mode in modes) or any(flag is None for flag in isolated):
        return unknown(UNRESOLVED, detail + "; some values are missing", at)
    return decided("pass", detail, at, len(networks), len(networks))


def net_05(ctx: Context) -> Outcome:
    """Share of active devices where web or DNS filtering is on."""
    inventory = ctx.source(INVENTORY)
    if inventory is None:
        return no_source(INVENTORY)
    days = ctx.control.whole("active_days")
    rows = active_rows(inventory, "device", "last_seen", days)
    return share_of_known(
        ctx.control,
        rows,
        lambda row: flag_of(row.get("dns_filter_active")),
        inventory.captured_at,
        "active devices with DNS filtering",
    )
