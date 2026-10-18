"""The logging and governance rules: PC-LOG-01 to 04 and 06, PC-GOV-03 and 04.

PC-LOG-05, PC-GOV-01, 02, 05 and 07 are manual artefacts; PC-GOV-06 needs a
permission outside the verified list and is unknown by `automatic_unavailable`.
"""

from app.checks.model import EMPTY_POPULATION, UNRESOLVED, Outcome, Row, Status
from app.checks.support import (
    Context,
    absent,
    active_rows,
    count_of,
    count_outcome,
    decided,
    flag_of,
    no_source,
    oldest,
    share_of_known,
    share_outcome,
    text_of,
    unknown,
    within,
    worst_of,
)

EXCHANGE = "exchange-export"
NETWORK = "network-export"
INVENTORY = "device-inventory"
ENTRA = "entra-registration"
TRAINING = "training-csv"
LEAVERS = "leavers-csv"


def log_01(ctx: Context) -> Outcome:
    """Audit logging: ingestion on and auditing not disabled."""
    exchange = ctx.source(EXCHANGE)
    if exchange is None:
        return no_source(EXCHANGE)
    rows = exchange.rows("audit")
    if not rows:
        return absent("The Exchange export has no audit settings.")

    def state(row: Row) -> Status | None:
        ingestion = flag_of(row.get("unified_audit_log_enabled"))
        disabled = flag_of(row.get("audit_disabled"))
        if ingestion is False or disabled is True:
            return "fail"
        return "pass" if ingestion is True and disabled is False else None

    states = [state(row) for row in rows]
    return worst_of(states, exchange.captured_at, "audit settings are on")


def log_02(ctx: Context) -> Outcome:
    """The longer of the licence default and a declared archive, in days."""
    item = ctx.evidence.manual.get(ctx.control.id)
    declared = None if item is None else item.value
    licence = ctx.evidence.licence_log_retention_days
    found = [days for days in (licence, declared) if days is not None]
    if not found:
        return absent("Neither a licence default nor a declared archive is known.")
    days = max(found)
    detail = f"Logs are kept {days} days"
    control = ctx.control
    status: Status = "fail"
    if days >= control.whole("pass_days"):
        status = "pass"
    elif days >= control.whole("partial_days"):
        status = "partial"
    # A declared archive that decides the result carries the manual quality.
    from_manual = declared is not None and (licence is None or declared >= licence)
    return Outcome(status, None, detail, manual=from_manual)


def log_03(ctx: Context) -> Outcome:
    """An enabled alert policy with a recipient, and a recent acknowledgement."""
    exchange = ctx.source(EXCHANGE)
    if exchange is None:
        return no_source(EXCHANGE)
    at = exchange.captured_at
    alerts = exchange.rows("alert")
    recipients = [count_of(row.get("recipient_count")) for row in alerts]
    if all(found is None for found in recipients):
        return absent("The Exchange export has no alert with a recipient count.")
    window = ctx.control.whole("ack_days")
    routed = [
        row
        for row in alerts
        if row.get("disabled") is False
        and (count_of(row.get("recipient_count")) or 0) > 0
    ]
    if not routed:
        unresolved = any(
            row.get("disabled") is None or row.get("recipient_count") is None
            for row in alerts
        )
        if unresolved:
            return unknown(UNRESOLVED, "Some alerts cannot be told.", at)
        return decided("fail", "No enabled alert has a recipient.", at)
    if any(within(at, row.get("last_acknowledged"), window) is True for row in alerts):
        return decided("pass", "Alerts reach a person who acknowledges them.", at)
    return decided("partial", "No alert was acknowledged in the window.", at)


def log_04(ctx: Context) -> Outcome:
    """The required kinds of alert that are enabled (pass: all; partial: some)."""
    exchange = ctx.source(EXCHANGE)
    if exchange is None:
        return no_source(EXCHANGE)
    at = exchange.captured_at
    alerts = [row for row in exchange.rows("alert") if text_of(row.get("alert_kind"))]
    if not alerts:
        return absent("The Exchange export has no alert of a required kind.")
    required = ctx.control.whole("required_alerts")
    enabled = {row.get("alert_kind") for row in alerts if row.get("disabled") is False}
    maybe = {
        row.get("alert_kind") for row in alerts if row.get("disabled") is None
    } - enabled

    def status(count: int) -> Status:
        if count >= required:
            return "pass"
        return "partial" if count else "fail"

    detail = f"{len(enabled)} of {required} required alerts are enabled"
    if status(len(enabled)) != status(len(enabled) + len(maybe)):
        return unknown(UNRESOLVED, detail, at)
    return decided(status(len(enabled)), detail, at, len(enabled), required)


def log_06(ctx: Context) -> Outcome:
    """Share of perimeter devices and servers that send their logs to a target."""
    network, inventory = ctx.source(NETWORK), ctx.source(INVENTORY)
    if network is None and inventory is None:
        return no_source(NETWORK, INVENTORY)
    rows: list[Row] = []
    if network is not None:
        for device in network.rows("device"):
            if device.get("perimeter") is True:
                rows.append({"sent": flag_of(device.get("syslog_target"))})
    if inventory is not None:
        days = ctx.control.whole("active_days")
        for device in active_rows(inventory, "device", "last_seen", days):
            if device.get("form_factor") == "server":
                rows.append({"sent": flag_of(device.get("log_forwarding"))})
    at = oldest(
        [
            network.captured_at if network is not None else None,
            inventory.captured_at if inventory is not None else None,
        ]
    )
    return share_of_known(
        ctx.control,
        rows,
        lambda row: flag_of(row.get("sent")),
        at,
        "perimeter devices and servers send logs",
    )


def gov_03(ctx: Context) -> Outcome:
    """Share of member users with a training completion in the window."""
    training, entra = ctx.source(TRAINING), ctx.source(ENTRA)
    if training is None or entra is None:
        return no_source(TRAINING, ENTRA)
    at = oldest([training.captured_at, entra.captured_at])
    members = {
        user
        for row in entra.rows("user")
        if row.get("user_type") != "guest" and (user := text_of(row.get("user")))
    }
    if not members:
        return unknown(EMPTY_POPULATION, "The registration report has no members.", at)
    window = ctx.control.whole("training_days")
    trained = {
        user
        for row in training.rows("completion")
        if (user := text_of(row.get("user")))
        and within(training.captured_at, row.get("completed_utc"), window) is True
    }
    done = len(members & trained)
    return share_outcome(
        ctx.control, done, len(members), at, "member users completed training"
    )


def gov_04(ctx: Context) -> Outcome:
    """Leavers whose account is still enabled after the grace days: none is wanted."""
    leavers = ctx.source(LEAVERS)
    if leavers is None:
        return no_source(LEAVERS)
    at = leavers.captured_at
    rows = leavers.rows("leaver")
    if all(flag_of(row.get("account_enabled")) is None for row in rows):
        return absent("The leavers list does not say if the accounts are still on.")
    grace = ctx.control.whole("grace_days")
    overdue = [row for row in rows if within(at, row.get("leave_date"), grace) is False]
    flags = [flag_of(row.get("account_enabled")) for row in overdue]
    enabled = sum(1 for flag in flags if flag)
    unresolved = sum(1 for flag in flags if flag is None)
    what = "leavers are still enabled after the grace period"
    return count_outcome(ctx.control, enabled, unresolved, at, what, len(overdue))
