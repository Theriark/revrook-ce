"""The backup and recovery rules, PC-BCK-01 and PC-BCK-03 to PC-BCK-05.

PC-BCK-02 needs the licensed mailbox and site counts and is unknown by
`automatic_unavailable`; PC-BCK-06 is a manual artefact. A backup asset is joined
to a device of the RMM inventory by their pseudonyms (the same name gives the same
pseudonym). PC-BCK-01 reads the servers of the inventory as the in-scope assets:
the licensed mailboxes are not imported in CE, so mailboxes are not in scope.
"""

from datetime import UTC, datetime
from fractions import Fraction

from app.checks.model import EMPTY_POPULATION, UNRESOLVED, Outcome, Row
from app.checks.support import (
    Context,
    absent,
    active_rows,
    count_of,
    decided,
    flag_of,
    no_source,
    oldest,
    parse_time,
    share_of_known,
    share_outcome,
    text_of,
    unknown,
    within,
    within_hours,
)

BACKUP = "backup-export"
INVENTORY = "device-inventory"
EARLIEST = datetime.min.replace(tzinfo=UTC)


def _tested_at(row: Row) -> datetime:
    return parse_time(row.get("restore_test_date")) or EARLIEST


def _by_asset(rows: tuple[Row, ...]) -> dict[str, list[Row]]:
    jobs: dict[str, list[Row]] = {}
    for row in rows:
        asset = text_of(row.get("asset"))
        if asset is not None:
            jobs.setdefault(asset, []).append(row)
    return jobs


def bck_01(ctx: Context) -> Outcome:
    """Share of in-scope servers with a recent successful backup (a GATE control)."""
    backup, inventory = ctx.source(BACKUP), ctx.source(INVENTORY)
    if backup is None or inventory is None:
        return no_source(BACKUP, INVENTORY)
    control = ctx.control
    at = oldest([backup.captured_at, inventory.captured_at])
    devices = inventory.rows("device")
    if all(text_of(row.get("form_factor")) is None for row in devices):
        return absent("The inventory does not say which devices are servers.")
    days = control.whole("active_days")
    servers: set[str] = set()
    for row in active_rows(inventory, "device", "last_seen", days):
        key = text_of(row.get("device"))
        if key is not None and row.get("form_factor") == "server":
            servers.add(key)
    if not servers:
        return unknown(EMPTY_POPULATION, "No active server in the inventory.", at)
    jobs = _by_asset(backup.rows("job"))
    schedules = [count_of(row.get("schedule_hours")) for row in backup.rows("job")]
    if all(schedule is None for schedule in schedules):
        return absent("The backup export has no schedule in hours.")
    factor = Fraction(control.number("schedule_factor"))

    def recent_success(row: Row) -> bool:
        hours = count_of(row.get("schedule_hours"))
        if hours is None or row.get("last_result") != "success":
            return False
        window = factor * hours
        return within_hours(backup.captured_at, row.get("last_success"), window) is True

    protected = sum(
        1
        for server in servers
        if any(recent_success(row) for row in jobs.get(server, []))
    )
    what = "in-scope servers have a recent backup"
    return share_outcome(control, protected, len(servers), at, what)


def bck_03(ctx: Context) -> Outcome:
    """A restore test: every class of backup has a successful test in the window."""
    backup = ctx.source(BACKUP)
    if backup is None:
        return no_source(BACKUP)
    at = backup.captured_at
    window = ctx.control.whole("restore_days")
    classes: dict[str, list[Row]] = {}
    for row in backup.rows("job"):
        classes.setdefault(text_of(row.get("asset_type")) or "other", []).append(row)
    tests = {
        name: [row for row in rows if parse_time(row.get("restore_test_date"))]
        for name, rows in classes.items()
    }
    if not any(tests.values()):
        return absent("No restore test is recorded in the backup export.")
    passed = failed = unresolved = 0
    for tested in tests.values():
        if not tested:
            continue
        latest = max(tested, key=_tested_at)
        outcome = text_of(latest.get("restore_test_result"))
        if outcome is None:
            unresolved += 1
        elif outcome != "success":
            failed += 1
        elif within(at, latest.get("restore_test_date"), window) is True:
            passed += 1
    total = len(classes)
    detail = f"{passed} of {total} backup classes have a restore test in {window} days"
    if failed:
        return decided("fail", detail, at, passed, total)
    if unresolved:
        return unknown(UNRESOLVED, detail, at)
    if passed == total:
        return decided("pass", detail, at, passed, total)
    return decided("partial" if passed else "fail", detail, at, passed, total)


def _any_flag(rows: list[Row], column: str) -> bool | None:
    """True when a job has the flag; False when every job says no; else unknown."""
    flags = [flag_of(row.get(column)) for row in rows]
    if any(flag is True for flag in flags):
        return True
    return False if flags and all(flag is False for flag in flags) else None


def bck_04(ctx: Context) -> Outcome:
    """Share of assets with an immutable copy, else with an off-site copy."""
    backup = ctx.source(BACKUP)
    if backup is None:
        return no_source(BACKUP)
    at = backup.captured_at
    assets = _by_asset(backup.rows("job"))
    immutable = [_any_flag(rows, "immutable") for rows in assets.values()]
    offsite = [_any_flag(rows, "offsite") for rows in assets.values()]
    known = [flag for flag in immutable if flag is not None]
    if not known:
        return absent("The backup export does not say which copies are immutable.")
    needed = Fraction(ctx.control.number("share"))
    protected = sum(1 for flag in known if flag)
    detail = f"{protected} of {len(known)} assets immutable"
    if Fraction(protected, len(known)) >= needed:
        return decided("pass", detail, at, protected, len(known))
    away = [flag for flag in offsite if flag is not None]
    if away and Fraction(sum(1 for flag in away if flag), len(away)) >= needed:
        detail += "; the copies are off site"
        return decided("partial", detail, at, protected, len(known))
    return decided("fail", detail, at, protected, len(known))


def bck_05(ctx: Context) -> Outcome:
    """Share of jobs that are encrypted and kept at least the minimum days."""
    backup = ctx.source(BACKUP)
    if backup is None:
        return no_source(BACKUP)
    minimum = ctx.control.whole("min_retention_days")

    def good(row: Row) -> bool | None:
        encrypted = flag_of(row.get("encrypted"))
        kept = count_of(row.get("retention_days"))
        if encrypted is False or (kept is not None and kept < minimum):
            return False
        if encrypted is None or kept is None:
            return None
        return True

    return share_of_known(
        ctx.control,
        backup.rows("job"),
        good,
        backup.captured_at,
        "backup jobs encrypted and kept long enough",
    )
