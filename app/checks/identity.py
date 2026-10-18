"""The identity and MFA rules, PC-ACC-01 to PC-ACC-05.

PC-ACC-06 and PC-ACC-07 need a licence tier or a permission outside the verified
list and are unknown by `automatic_unavailable`; PC-ACC-08 is a manual artefact.
"""

from app.checks.model import (
    EMPTY_POPULATION,
    NO_PERMANENT_ASSIGNMENT,
    Outcome,
    Row,
)
from app.checks.support import (
    Context,
    absent,
    count_of,
    count_outcome,
    decided,
    flag_of,
    no_source,
    share_of_known,
    text_of,
    unknown,
)

ENTRA = "entra-registration"
POLICIES = "conditional-access"
ROLES = "directory-roles"


def acc_01(ctx: Context) -> Outcome:
    """Share of member users registered and capable of MFA (guests are not staff)."""
    source = ctx.source(ENTRA)
    if source is None:
        return no_source(ENTRA)
    members = [row for row in source.rows("user") if row.get("user_type") != "guest"]

    def with_mfa(row: Row) -> bool | None:
        registered = flag_of(row.get("mfa_registered"))
        capable = flag_of(row.get("mfa_capable"))
        # One flag that is False settles it, whatever the other one says.
        if registered is False or capable is False:
            return False
        if registered is None or capable is None:
            return None
        return True

    return share_of_known(
        ctx.control, members, with_mfa, source.captured_at, "member users with MFA"
    )


def acc_02(ctx: Context) -> Outcome:
    """Administrators without MFA: none is wanted; an unknown one is not a pass."""
    source = ctx.source(ENTRA)
    if source is None:
        return no_source(ENTRA)
    at = source.captured_at
    rows = source.rows("user")
    if not rows:
        return unknown(EMPTY_POPULATION, "The registration report has no users.", at)
    flags = [flag_of(row.get("is_admin")) for row in rows]
    if all(flag is None for flag in flags):
        return absent("The registration report does not say who is an administrator.")
    admins = [row for row, flag in zip(rows, flags, strict=True) if flag]
    unresolved = sum(1 for flag in flags if flag is None)
    without = 0
    for row in admins:
        registered = flag_of(row.get("mfa_registered"))
        if registered is None:
            unresolved += 1
        elif not registered:
            without += 1
    what = "administrators without MFA"
    return count_outcome(ctx.control, without, unresolved, at, what, len(admins))


def _covers_everyone(row: Row) -> bool:
    return row.get("all_users") is True and row.get("all_apps") is True


def acc_03(ctx: Context) -> Outcome:
    """MFA enforced by policy: security defaults, or a Conditional Access policy."""
    source = ctx.source(POLICIES)
    if source is None:
        return no_source(POLICIES)
    at = source.captured_at
    if source.summary.get("tenant_state") == "security-defaults":
        return decided("pass", "Security defaults are on.", at)
    policies = source.rows("policy")
    if not policies:
        return absent("The export has no policies and does not say security defaults.")
    limit = ctx.control.whole("max_exclusions")

    def enforced(row: Row) -> bool:
        exclusions = count_of(row.get("exclusions"))
        return (
            row.get("state") == "enabled"
            and _covers_everyone(row)
            and row.get("requires_mfa") is True
            and exclusions is not None
            and exclusions <= limit
        )

    if any(enforced(row) for row in policies):
        return decided("pass", "An enabled policy requires MFA for everyone.", at)
    for row in policies:
        reporting = row.get("state") == "report-only"
        admins_only = row.get("state") == "enabled" and row.get("targets_roles") is True
        if row.get("requires_mfa") is True and (
            (reporting and _covers_everyone(row)) or admins_only
        ):
            return decided("partial", "MFA is in report-only mode or admins only.", at)
    return decided("fail", "No policy enforces MFA for everyone.", at)


def acc_04(ctx: Context) -> Outcome:
    """Legacy sign-in methods blocked: security defaults, or a blocking policy."""
    source = ctx.source(POLICIES)
    if source is None:
        return no_source(POLICIES)
    at = source.captured_at
    if source.summary.get("tenant_state") == "security-defaults":
        return decided("pass", "Security defaults are on.", at)
    policies = source.rows("policy")
    if not policies:
        return absent("The export has no policies and does not say security defaults.")
    blocking = [
        row
        for row in policies
        if row.get("blocks") is True and row.get("legacy_clients") is True
    ]
    for row in blocking:
        if row.get("state") == "enabled" and row.get("all_users") is True:
            return decided("pass", "An enabled policy blocks legacy sign-in.", at)
    for row in blocking:
        if row.get("state") in ("enabled", "report-only"):
            return decided("partial", "Legacy sign-in is blocked in part only.", at)
    return decided("fail", "No policy blocks legacy sign-in.", at)


def acc_05(ctx: Context) -> Outcome:
    """Distinct enabled users with a permanent Global Administrator assignment."""
    source = ctx.source(ROLES)
    if source is None:
        return no_source(ROLES)
    at = source.captured_at
    assignments = [
        row for row in source.rows("assignment") if row.get("global_admin") is True
    ]
    if not assignments:
        return unknown(NO_PERMANENT_ASSIGNMENT, "No Global Administrator found.", at)
    if all(flag_of(row.get("permanent")) is None for row in assignments):
        return absent("The export does not say which assignments are permanent.")
    users = {
        text_of(row.get("user"))
        for row in assignments
        if row.get("permanent") is True and row.get("enabled") is not False
    } - {None}
    found = len(users)
    control = ctx.control
    detail = f"{found} permanent Global Administrators"
    if found < control.whole("partial_min"):
        detail = "No permanent Global Administrator."
        return unknown(NO_PERMANENT_ASSIGNMENT, detail, at)
    low, high = control.whole("pass_min"), control.whole("pass_max")
    if low <= found <= high:
        return decided("pass", detail, at, found)
    below_pass = found < low
    above_pass = high < found <= control.whole("partial_max")
    if below_pass or above_pass:
        return decided("partial", detail, at, found)
    return decided("fail", detail, at, found)
