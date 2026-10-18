"""Vectors of the controls whose rule is written out in words (tools/make_vectors.py).

Each expected result is written by hand from the rule text of the control file.
Identity, devices and email are here; the other domains are in tools/vector_rules.py.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from tools import vector_rules, vector_shares
from tools.vector_support import (
    EMPTY,
    LOOKUP,
    LOS,
    RECENT,
    UNRESOLVED,
    Vector,
    count_status,
    ev,
    one,
    rep,
    src,
    vec,
)

Maker = Callable[[Mapping[str, Any]], list[Vector]]
ENTRA = "entra-registration"
POLICIES = "conditional-access"
ROLES = "directory-roles"
EXCHANGE = "exchange-export"
DNS = "dns-check"
NO_PERMANENT = "no_permanent_assignment"


def user(name: str = "u1", **kw: Any) -> dict[str, Any]:
    row = {
        "user": name,
        "user_type": "member",
        "is_admin": False,
        "mfa_registered": True,
        "mfa_capable": True,
    }
    return {**row, **kw}


def policy(**kw: Any) -> dict[str, Any]:
    row = {
        "state": "enabled",
        "all_users": True,
        "all_apps": True,
        "requires_mfa": True,
        "blocks": False,
        "targets_roles": False,
        "exclusions": 0,
        "legacy_clients": False,
    }
    return {**row, **kw}


def policies(rows: Sequence[Any], tenant: str | None = "conditional-access") -> Any:
    summary = {} if tenant is None else {"tenant_state": tenant}
    return ev({POLICIES: src({"policy": list(rows)}, summary)})


def entra(*rows: Any) -> dict[str, Any]:
    return one(ENTRA, "user", *rows)


def acc_02(control: Mapping[str, Any]) -> list[Vector]:
    rule = control["rule"]
    admin = {"is_admin": True}
    three = [user(f"a{n}", **admin) for n in range(3)]
    one_bad = [user("a1", **admin), user("a2", **admin, mfa_registered=False)]
    two_bad = [user(f"a{n}", **admin, mfa_registered=False) for n in range(2)]
    unknown = user("a1", **admin, mfa_registered=None)
    no_flag = [user("u1", is_admin=None), user("u2", is_admin=None)]
    hit = count_status(rule, 1)
    two_of_three = entra(*two_bad, user("a3", **admin))
    return [
        vec("no-admin-without-mfa", entra(*three, user("u9")), "pass", None, 0, 3),
        vec("no-administrator-at-all", entra(user("u1")), "pass", None, 0, 0),
        vec("one-admin-without-mfa", entra(*one_bad), hit, None, 1, 2),
        vec("two-admins-without-mfa", two_of_three, "fail", None, 2, 3),
        vec("admin-mfa-unknown", entra(unknown), "unknown", UNRESOLVED),
        vec("admin-flag-absent", entra(*no_flag), "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
        vec("empty-no-users", entra(), "unknown", EMPTY),
    ]


def acc_03(control: Mapping[str, Any]) -> list[Vector]:
    admins_only = policies([policy(all_users=False, targets_roles=True)])
    return [
        vec("security-defaults", policies([], "security-defaults"), "pass"),
        vec("enforced-policy", policies([policy()]), "pass"),
        vec("exclusions-at-the-limit", policies([policy(exclusions=2)]), "pass"),
        vec("exclusions-over-the-limit", policies([policy(exclusions=3)]), "fail"),
        vec("report-only", policies([policy(state="report-only")]), "partial"),
        vec("admins-only", admins_only, "partial"),
        vec("no-mfa-grant", policies([policy(requires_mfa=False)]), "fail"),
        vec("disabled-policy", policies([policy(state="disabled")]), "fail"),
        vec("empty-policies-no-defaults", policies([], None), "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]


def acc_04(control: Mapping[str, Any]) -> list[Vector]:
    block = {"blocks": True, "legacy_clients": True, "requires_mfa": False}
    some_users = policies([policy(**block, all_users=False)])
    report_only = policies([policy(**block, state="report-only")])
    disabled = policies([policy(**block, state="disabled")])
    return [
        vec("security-defaults", policies([], "security-defaults"), "pass"),
        vec("blocking-for-all-users", policies([policy(**block)]), "pass"),
        vec("blocking-some-users", some_users, "partial"),
        vec("report-only-block", report_only, "partial"),
        vec("no-block", policies([policy()]), "fail"),
        vec("disabled-block", disabled, "fail"),
        vec("empty-policies-no-defaults", policies([], None), "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]


def assignments(count: int, **kw: Any) -> dict[str, Any]:
    row = {
        "role": "Global Administrator",
        "global_admin": True,
        "enabled": True,
        "permanent": True,
    }
    return rep(count, {**row, **kw}, "user", "p")


def roles(*rows: Any) -> dict[str, Any]:
    return one(ROLES, "assignment", *rows)


def acc_05(control: Mapping[str, Any]) -> list[Vector]:
    found: list[Vector] = []
    cases = (
        ("one-permanent-admin", 1, "partial"),
        ("two-permanent-admins", 2, "pass"),
        ("four-permanent-admins", 4, "pass"),
        ("five-permanent-admins", 5, "partial"),
        ("six-permanent-admins", 6, "partial"),
        ("seven-permanent-admins", 7, "fail"),
    )
    for name, count, status in cases:
        found.append(vec(name, roles(assignments(count)), status, None, count))
    other = {"global_admin": False, "role": "Exchange Administrator", "user": "x1"}
    mixed = roles(
        assignments(3),
        assignments(2, permanent=False),
        assignments(2, enabled=False),
    )
    twice = roles(assignments(1), assignments(1, role="Company Administrator"))
    unreported = roles(assignments(3, permanent=None))
    found += [
        vec("empty-no-global-admin", roles(other), "unknown", NO_PERMANENT),
        vec("only-permanent-enabled-count", mixed, "pass", None, 3),
        vec("one-user-in-two-rows-counts-once", twice, "partial", None, 1),
        vec("permanent-not-reported", unreported, "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]
    return found


# --- devices ---------------------------------------------------------------------


def dev_03(control: Mapping[str, Any]) -> list[Vector]:
    windows = {"os": "windows"}
    old = {**windows, "version_prefix": "10.0.19", "end_of_support": "2025-10-14"}
    new = {**windows, "version_prefix": "10.0.22", "end_of_support": "2030-01-01"}
    base = {"os": "windows", "form_factor": "workstation", "last_seen": RECENT}

    def fleet(past: int, current: int, **extra: Any) -> dict[str, Any]:
        rows = [
            rep(past, {**base, "os_build": "10.0.19045"}, "device", "o"),
            rep(current, {**base, "os_build": "10.0.22631"}, "device", "n"),
        ]
        return ev({"device-inventory": src({"device": rows})}, **extra)

    table = {"lifecycle": [old, new]}
    today = {"lifecycle": [{**old, "end_of_support": "2026-10-17"}, new]}
    yesterday = {"lifecycle": [{**old, "end_of_support": "2026-10-16"}, new]}
    linux = [rep(10, {**base, "os": "linux", "os_build": "6.1"}, "device", "l")]
    no_match = ev({"device-inventory": src({"device": linux})}, **table)
    no_device = ev({"device-inventory": src({"device": []})}, **table)
    on_day = fleet(10, 0, **today)
    day_after = fleet(10, 0, **yesterday)
    return [
        vec("pass-none-past-support", fleet(0, 100, **table), "pass", None, 0, 100),
        vec("partial-5-percent-past", fleet(5, 95, **table), "partial", None, 5, 100),
        vec("fail-6-percent-past", fleet(6, 94, **table), "fail", None, 6, 100),
        vec("end-of-support-today-is-not-past", on_day, "pass", None, 0, 10),
        vec("end-of-support-yesterday-is-past", day_after, "fail", None, 10, 10),
        vec("unknown-no-lifecycle-table", fleet(0, 10), "unknown", LOS),
        vec("unknown-no-device-matches", no_match, "unknown", LOS),
        vec("unknown-source-missing", ev(**table), "unknown", LOS),
        vec("empty-no-device", no_device, "unknown", EMPTY),
    ]


# --- email -----------------------------------------------------------------------


def dns_row(name: str, **kw: Any) -> dict[str, Any]:
    row = {
        "domain": name,
        "lookup_failed": False,
        "spf_records": 1,
        "spf_ending": "softfail",
        "spf_provider": True,
        "dkim_selectors": True,
        "dmarc_records": 1,
        "dmarc_policy": "reject",
        "dmarc_pct": 100,
        "dmarc_rua": True,
    }
    return {**row, **kw}


def domains(*rows: Any) -> dict[str, Any]:
    return one(DNS, "domain", *rows)


def eml_01(control: Mapping[str, Any]) -> list[Vector]:
    ok = [dns_row("m1"), dns_row("m2"), dns_row("m3")]
    half = [
        dns_row("m1"),
        dns_row("m2"),
        dns_row("m3", spf_records=0),
        dns_row("m4", spf_records=2),
    ]
    third = [dns_row("m1"), dns_row("m2", spf_records=0), dns_row("m3", spf_records=2)]
    hard_fail = domains(dns_row("m1", spf_ending="fail"))
    no_provider = domains(dns_row("m1", spf_provider=False))
    neutral = [dns_row("m1"), dns_row("m2", spf_ending="neutral")]
    down = dns_row("m4", lookup_failed=True)
    fails = [dns_row(f"m{n}", spf_records=0) for n in range(3)]
    return [
        vec("all-domains-pass", domains(*ok), "pass", None, 3, 3),
        vec("hard-fail-record-passes", hard_fail, "pass"),
        vec("half-of-the-domains-pass", domains(*half), "partial", None, 2, 4),
        vec("just-below-half", domains(*third), "fail", None, 1, 3),
        vec("neutral-is-not-a-pass", domains(*neutral), "partial", None, 1, 2),
        vec("two-records-fail", domains(dns_row("m1", spf_records=2)), "fail"),
        vec("no-record-fails", domains(dns_row("m1", spf_records=0)), "fail"),
        vec("provider-not-included-fails", no_provider, "fail"),
        vec("open-ending-fails", domains(dns_row("m1", spf_ending="pass")), "fail"),
        vec("lookup-failure-is-unknown", domains(*ok, down), "unknown", LOOKUP),
        vec("lookup-failure-cannot-save-a-fail", domains(*fails, down), "fail"),
        vec("empty-no-mail-domain", ev({DNS: src({"domain": []})}), "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]


def dkim_rows(*rows: Any) -> dict[str, Any]:
    return src({"dkim": list(rows)})


def eml_02(control: Mapping[str, Any]) -> list[Vector]:
    def dkim(name: str, enabled: bool | None = True) -> dict[str, Any]:
        return {"domain": name, "enabled": enabled}

    def both(signing: Sequence[Any], selectors: Sequence[Any]) -> dict[str, Any]:
        return ev(
            {EXCHANGE: dkim_rows(*signing), DNS: src({"domain": list(selectors)})}
        )

    two = [dkim("m1"), dkim("m2")]
    three = [dkim("m1"), dkim("m2"), dkim("m3")]
    yes = [dns_row("m1"), dns_row("m2")]
    mixed = [dns_row("m1"), dns_row("m2", dkim_selectors=False)]
    one_of_three = [
        dns_row("m1"),
        dns_row("m2", dkim_selectors=False),
        dns_row("m3", dkim_selectors=False),
    ]
    down = [dns_row("m1"), dns_row("m2", lookup_failed=True)]
    disabled = both([dkim("m1"), dkim("m2", False)], yes)
    return [
        vec("all-domains-sign", both(two, yes), "pass", None, 2, 2),
        vec("one-without-selectors", both(two, mixed), "partial", None, 1, 2),
        vec("one-of-three", both(three, one_of_three), "fail", None, 1, 3),
        vec("disabled-in-exchange", disabled, "partial", None, 1, 2),
        vec("selector-lookup-failed", both(two, down), "unknown", LOOKUP),
        vec("selectors-not-checked", ev({EXCHANGE: dkim_rows(*two)}), "unknown", LOS),
        vec("exchange-export-missing", ev({DNS: src({"domain": yes})}), "unknown", LOS),
        vec("empty-no-dkim-record", both([], yes), "unknown", LOS),
    ]


def eml_03(control: Mapping[str, Any]) -> list[Vector]:
    def one_domain(**kw: Any) -> dict[str, Any]:
        return domains(dns_row("m1", **kw))

    passing = [dns_row("m1"), dns_row("m2")]
    mixed = [dns_row("m1"), dns_row("m2", dmarc_pct=50)]
    broken = [dns_row("m1"), dns_row("m2", dmarc_records=0)]
    down = dns_row("m3", lookup_failed=True)
    quarantine = one_domain(dmarc_policy="quarantine")
    half_quarantine = one_domain(dmarc_policy="quarantine", dmarc_pct=50)
    bare_none = one_domain(dmarc_policy="none", dmarc_rua=False)
    return [
        vec("reject-at-100-with-rua", one_domain(), "pass"),
        vec("quarantine-at-100-with-rua", quarantine, "pass"),
        vec("quarantine-at-50-percent", half_quarantine, "partial"),
        vec("reject-without-rua", one_domain(dmarc_rua=False), "partial"),
        vec("none-with-rua", one_domain(dmarc_policy="none"), "partial"),
        vec("none-without-rua", bare_none, "fail"),
        vec("no-record", one_domain(dmarc_records=0), "fail"),
        vec("two-records", one_domain(dmarc_records=2), "fail"),
        vec("a-pass-and-a-partial", domains(*mixed), "partial", None, 1, 2),
        vec("a-pass-and-a-fail", domains(*broken), "fail", None, 1, 2),
        vec("lookup-failure-is-unknown", domains(*passing, down), "unknown", LOOKUP),
        vec("lookup-failure-cannot-save-a-fail", domains(*broken, down), "fail"),
        vec("empty-no-mail-domain", ev({DNS: src({"domain": []})}), "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]


def filters(**state: bool | None) -> dict[str, Any]:
    rows = [{"policy_type": name, "enabled": on} for name, on in state.items()]
    return ev({EXCHANGE: src({"policy": rows})})


def eml_04(control: Mapping[str, Any]) -> list[Vector]:
    anti = "anti-phish"
    links = "safe-links"
    files = "safe-attachments"
    all_on = filters(**{anti: True, links: True, files: True})
    anti_only = filters(**{anti: True, links: False, files: False})
    no_files = filters(**{anti: True, links: True, files: False})
    all_off = filters(**{anti: False, links: False, files: False})
    no_anti = filters(**{anti: False, links: True})
    return [
        vec("all-three-enabled", all_on, "pass"),
        vec("preset-only", filters(preset=True, **{anti: False}), "pass"),
        vec("anti-phishing-only", anti_only, "partial"),
        vec("links-without-attachments", no_files, "partial"),
        vec("nothing-enabled", all_off, "fail"),
        vec("safe-links-without-anti-phishing", no_anti, "fail"),
        vec("unknown-state-not-reported", filters(**{anti: None}), "unknown", LOS),
        vec("empty-no-policy", ev({EXCHANGE: src({"policy": []})}), "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]


def forwarding(mode: str | None, flags: Sequence[bool | None]) -> dict[str, Any]:
    policy_row = {"policy_type": "outbound-spam", "auto_forwarding_mode": mode}
    boxes = [
        {"mailbox": f"b{n}", "forwarding_external": flag}
        for n, flag in enumerate(flags)
    ]
    return ev({EXCHANGE: src({"policy": [policy_row], "mailbox": boxes})})


def eml_05(control: Mapping[str, Any]) -> list[Vector]:
    no_policy = ev({EXCHANGE: src({"mailbox": [{"forwarding_external": False}]})})
    nobody = forwarding("off", [False] * 3)
    one = forwarding("off", [True, False, False])
    two = forwarding("off", [True, True, False])
    state_unknown = forwarding("off", [False, None])
    one_unknown = forwarding("off", [True, None])
    return [
        vec("off-and-nobody-forwards", nobody, "pass", None, 0, 3),
        vec("off-one-forwards", one, "partial", None, 1, 3),
        vec("off-two-forward", two, "fail", None, 2, 3),
        vec("forwarding-on", forwarding("on", [False]), "fail"),
        vec("forwarding-automatic", forwarding("automatic", [False]), "fail"),
        vec("mailbox-state-unknown", state_unknown, "unknown", UNRESOLVED),
        vec("one-forwards-one-unknown", one_unknown, "unknown", UNRESOLVED),
        vec("no-outbound-policy", no_policy, "unknown", LOS),
        vec("empty-no-mailbox", forwarding("off", []), "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]


def mailboxes(*states: bool | None, shared: bool = True) -> dict[str, Any]:
    kind = "shared" if shared else "user"
    rows = [
        {"mailbox": f"b{n}", "recipient_type": kind, "account_enabled": state}
        for n, state in enumerate(states)
    ]
    return ev({EXCHANGE: src({"mailbox": rows})})


def eml_06(control: Mapping[str, Any]) -> list[Vector]:
    rule = control["rule"]
    no_type = ev({EXCHANGE: src({"mailbox": [{"mailbox": "b1"}]})})
    quiet = mailboxes(False, False, False)
    one_in = mailboxes(True, False)
    two_in = mailboxes(True, True, False)
    no_shared = mailboxes(True, shared=False)
    return [
        vec("no-shared-mailbox-signs-in", quiet, "pass", None, 0, 3),
        vec("no-shared-mailbox-at-all", no_shared, "pass", None, 0, 0),
        vec("one-can-sign-in", one_in, count_status(rule, 1), None, 1, 2),
        vec("two-can-sign-in", two_in, count_status(rule, 2), None, 2, 3),
        vec("state-unknown", mailboxes(False, None), "unknown", UNRESOLVED),
        vec("one-enabled-one-unknown", mailboxes(True, None), "unknown", UNRESOLVED),
        vec("recipient-type-not-reported", no_type, "unknown", LOS),
        vec("empty-no-mailbox", ev({EXCHANGE: src({"mailbox": []})}), "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]


STATE_VECTORS: dict[str, Maker] = {
    "PC-ACC-02": acc_02,
    "PC-ACC-03": acc_03,
    "PC-ACC-04": acc_04,
    "PC-ACC-05": acc_05,
    "PC-DEV-01": vector_shares.dev_01,
    "PC-DEV-03": dev_03,
    "PC-EML-01": eml_01,
    "PC-EML-02": eml_02,
    "PC-EML-03": eml_03,
    "PC-EML-04": eml_04,
    "PC-EML-05": eml_05,
    "PC-EML-06": eml_06,
    "PC-BCK-01": vector_shares.bck_01,
    "PC-GOV-03": vector_shares.gov_03,
    **vector_rules.RULE_VECTORS,
}
