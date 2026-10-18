"""Vectors of the backup, network, logging and governance rules written in words.

Each expected result is written by hand from the rule text of the control file
(tools/make_vectors.py); counts and windows are read from the file. Every maker
takes the entry of its control in the control file.
"""

from collections.abc import Callable, Mapping
from fractions import Fraction
from typing import Any

from tools.vector_support import (
    EMPTY,
    LOS,
    UNRESOLVED,
    Vector,
    ago,
    count_status,
    ev,
    of_hundred,
    one,
    rep,
    vec,
)

Maker = Callable[[Mapping[str, Any]], list[Vector]]
BACKUP = "backup-export"
NETWORK = "network-export"
EXCHANGE = "exchange-export"


def whole(control: Mapping[str, Any], name: str) -> int:
    return int(control["params"][name])


# --- backup ----------------------------------------------------------------------


def job(
    asset: str,
    kind: str,
    days: Mapping[str, int] | None,
    result: str | None,
) -> dict[str, Any]:
    """A backup job of an asset class, restore-tested that long ago (or never)."""
    return {
        "asset": asset,
        "asset_type": kind,
        "restore_test_date": None if days is None else ago(**days),
        "restore_test_result": result,
    }


def jobs(*rows: Any) -> dict[str, Any]:
    return one(BACKUP, "job", *rows)


def bck_03(control: Mapping[str, Any]) -> list[Vector]:
    window = whole(control, "restore_days")
    server = job("s1", "server", {"days": 30}, "success")
    mail = job("e1", "exchange", {"days": 30}, "success")
    never = job("e1", "exchange", None, None)
    failed = job("s1", "server", {"days": 30}, "failed")
    at_window = job("s1", "server", {"days": window}, "success")
    over = job("s1", "server", {"days": window, "seconds": 1}, "success")
    unclear = job("s1", "server", {"days": 30}, None)
    old_fail = job("s1", "server", {"days": 80}, "failed")
    new_pass = job("s2", "server", {"days": 20}, "success")
    old_pass = job("s1", "server", {"days": 80}, "success")
    new_fail = job("s2", "server", {"days": 20}, "failed")
    return [
        vec("all-classes-tested-recently", jobs(server, mail), "pass"),
        vec("tested-exactly-at-the-window", jobs(at_window), "pass"),
        vec("tested-a-second-past-the-window", jobs(over), "fail"),
        vec("one-class-never-tested", jobs(server, never), "partial"),
        vec("latest-test-failed", jobs(failed), "fail"),
        vec("newer-pass-replaces-older-fail", jobs(old_fail, new_pass), "pass"),
        vec("newer-fail-replaces-older-pass", jobs(old_pass, new_fail), "fail"),
        vec("test-result-unknown", jobs(unclear), "unknown", UNRESOLVED),
        vec("unknown-none-recorded", jobs(never), "unknown", LOS),
        vec("empty-no-job", jobs(), "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]


def assets(count: int, start: int = 0, **kw: Any) -> dict[str, Any]:
    row = {"immutable": True, "offsite": True, **kw}
    return rep(count, row, "asset", "a", start)


def bck_04(control: Mapping[str, Any]) -> list[Vector]:
    top = of_hundred(Fraction(control["params"]["share"]))
    short = 100 - top + 1
    two_jobs = jobs(
        assets(99, 1),
        {"asset": "a0", "immutable": True, "offsite": True},
        {"asset": "a0", "immutable": False, "offsite": False},
    )
    at_share = jobs(assets(top), assets(100 - top, top, immutable=False))
    all_off = jobs(assets(top - 1), assets(short, top - 1, immutable=False))
    not_off = jobs(
        assets(top - 1),
        assets(short, top - 1, immutable=False, offsite=False),
    )
    off_only = jobs(assets(100, immutable=False))
    neither = jobs(assets(100, immutable=False, offsite=False))
    unreported = jobs(assets(5, immutable=None))
    return [
        vec("all-assets-immutable", jobs(assets(100)), "pass", None, 100, 100),
        vec("immutable-at-the-share", at_share, "pass", None, top, 100),
        vec(
            "just-below-the-share-all-off-site",
            all_off,
            "partial",
            None,
            top - 1,
            100,
        ),
        vec(
            "just-below-the-share-off-site-short",
            not_off,
            "fail",
            None,
            top - 1,
            100,
        ),
        vec("off-site-but-not-immutable", off_only, "partial"),
        vec("neither-immutable-nor-off-site", neither, "fail"),
        vec("one-immutable-job-is-enough", two_jobs, "pass", None, 100, 100),
        vec("unknown-immutable-not-reported", unreported, "unknown", LOS),
        vec("empty-no-job", jobs(), "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]


# --- network ---------------------------------------------------------------------


def devices(*rows: Any) -> dict[str, Any]:
    return one(NETWORK, "device", *rows)


def firewall(days: Mapping[str, int] | None, name: str = "f1", **kw: Any) -> Any:
    row = {
        "device": name,
        "perimeter": True,
        "firmware_release_date": None if days is None else ago(**days),
        "end_of_support_date": None,
    }
    return {**row, **kw}


def net_01(control: Mapping[str, Any]) -> list[Vector]:
    first = whole(control, "pass_days")
    second = whole(control, "partial_days")
    recent = firewall({"days": 100})
    no_support = firewall({"days": 10}, end_of_support_date=ago(days=1))
    no_date = firewall(None, end_of_support_date=ago(days=1))
    supported = firewall({"days": 10}, end_of_support_date=ago(days=-30))
    aged = firewall({"days": second + 10}, "f2")
    mid = firewall({"days": first + 10}, "f2")
    at_first = devices(firewall({"days": first}))
    past_first = devices(firewall({"days": first, "seconds": 1}))
    at_second = devices(firewall({"days": second}))
    past_second = devices(firewall({"days": second, "seconds": 1}))
    inside = devices(firewall({"days": 1}, perimeter=False))
    unreported = devices(firewall({"days": 1}, perimeter=None))
    return [
        vec("firmware-recent", devices(recent), "pass"),
        vec("firmware-exactly-at-the-pass-age", at_first, "pass"),
        vec("firmware-a-second-past-the-pass-age", past_first, "partial"),
        vec("firmware-exactly-at-the-partial-age", at_second, "partial"),
        vec("firmware-a-second-past-the-partial-age", past_second, "fail"),
        vec("past-end-of-support", devices(no_support), "fail"),
        vec("past-end-of-support-release-date-unknown", devices(no_date), "fail"),
        vec("end-of-support-still-ahead", devices(supported), "pass"),
        vec("one-old-firewall-fails-the-control", devices(recent, aged), "fail"),
        vec("a-pass-and-a-partial", devices(recent, mid), "partial"),
        vec("release-date-unknown", devices(firewall(None)), "unknown", UNRESOLVED),
        vec("empty-no-perimeter-device", inside, "unknown", EMPTY),
        vec("unknown-perimeter-not-reported", unreported, "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]


def rules(*rows: Any) -> dict[str, Any]:
    return one(NETWORK, "rule", *rows)


def open_rule(**kw: Any) -> dict[str, Any]:
    row = {
        "rule_enabled": True,
        "direction": "inbound",
        "action": "allow",
        "source": "any",
        "destination_port": 3389,
    }
    return {**row, **kw}


def net_02(control: Mapping[str, Any]) -> list[Vector]:
    rule = control["rule"]
    safe = open_rule(destination_port=443)
    one_open = rules(open_rule(), safe)
    two_open = rules(open_rule(), open_rule(destination_port=445))
    unreadable = open_rule(source=None)
    hit = count_status(rule, 1)
    any_port = rules(open_rule(destination_port="any"))
    ranged = rules(open_rule(destination_port="400-500"))
    ssh = rules(open_rule(destination_port=22))
    restricted = rules(open_rule(source="restricted"))
    disabled = rules(open_rule(rule_enabled=False))
    outbound = rules(open_rule(direction="outbound"))
    denied = rules(open_rule(action="deny"))
    mixed = rules(open_rule(), unreadable)
    failing = rules(open_rule(), open_rule(destination_port=445), unreadable)
    return [
        vec("no-risky-rule", rules(safe), "pass", None, 0, 1),
        vec("one-open-rdp", one_open, hit, None, 1, 2),
        vec("two-open-rules", two_open, count_status(rule, 2), None, 2, 2),
        vec("any-port-counts", any_port, hit, None, 1, 1),
        vec("a-range-with-a-risky-port-counts", ranged, hit, None, 1, 1),
        vec("ssh-open-to-everyone-counts", ssh, hit, None, 1, 1),
        vec("restricted-source-does-not-count", restricted, "pass", None, 0, 1),
        vec("disabled-rule-does-not-count", disabled, "pass", None, 0, 1),
        vec("outbound-rule-does-not-count", outbound, "pass", None, 0, 1),
        vec("deny-rule-does-not-count", denied, "pass", None, 0, 1),
        vec("unreadable-source", rules(unreadable), "unknown", UNRESOLVED),
        vec("one-open-one-unreadable", mixed, "unknown", UNRESOLVED),
        vec("failing-either-way", failing, "fail", None, 2, 3),
        vec("empty-no-rule", rules(), "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]


def edge(name: str = "f1", **kw: Any) -> dict[str, Any]:
    row = {
        "device": name,
        "perimeter": True,
        "wan_admin_enabled": False,
        "default_credentials_flag": False,
    }
    return {**row, **kw}


def net_03(control: Mapping[str, Any]) -> list[Vector]:
    inside = edge("f2", perimeter=False, wan_admin_enabled=True)
    exposed = devices(edge(wan_admin_enabled=True))
    default_login = devices(edge(default_credentials_flag=True))
    unclear = devices(edge(wan_admin_enabled=None))
    mixed = devices(
        edge(wan_admin_enabled=True),
        edge("f2", default_credentials_flag=None),
    )
    no_perimeter = devices(edge(perimeter=False))
    unreported = devices(edge(perimeter=None))
    return [
        vec("clean-perimeter-devices", devices(edge(), edge("f2")), "pass", None, 2, 2),
        vec("management-open-to-the-internet", exposed, "fail"),
        vec("default-login-kept", default_login, "fail"),
        vec("flag-unknown", unclear, "unknown", UNRESOLVED),
        vec("a-failure-beats-an-unknown", mixed, "fail"),
        vec("other-devices-are-ignored", devices(edge(), inside), "pass", None, 1, 1),
        vec("empty-no-perimeter-device", no_perimeter, "unknown", EMPTY),
        vec("unknown-perimeter-not-reported", unreported, "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]


def wifi_rows(*rows: Any) -> dict[str, Any]:
    return one(NETWORK, "ssid", *rows)


def wifi(name: str = "s1", **kw: Any) -> dict[str, Any]:
    row = {
        "ssid": name,
        "security_mode": "wpa2",
        "guest_ssid": False,
        "guest_isolated": None,
    }
    return {**row, **kw}


def net_04(control: Mapping[str, Any]) -> list[Vector]:
    guest = {"guest_ssid": True, "guest_isolated": True}
    plain = [wifi(), wifi("g", security_mode="wpa3", **guest)]
    modern = [
        wifi(security_mode="wpa2-wpa3"),
        wifi("s2", security_mode="wpa3-enterprise"),
    ]
    open_guest = wifi("g", guest_ssid=True, guest_isolated=False)
    unsure_guest = wifi_rows(wifi("g", guest_ssid=True))
    unsure_mode = wifi_rows(wifi(), wifi("s2", security_mode=None))
    # A mode the importer did not recognise is stored as `other`.
    other_mode = wifi_rows(wifi(security_mode="other"))
    return [
        vec("encrypted-and-guests-isolated", wifi_rows(*plain), "pass", None, 2, 2),
        vec("modern-modes-pass", wifi_rows(*modern), "pass"),
        vec("open-network", wifi_rows(wifi(security_mode="open")), "fail"),
        vec("wep-network", wifi_rows(wifi(security_mode="wep")), "fail"),
        vec("wpa1-network", wifi_rows(wifi(security_mode="wpa")), "fail"),
        vec("guest-not-isolated", wifi_rows(open_guest), "fail"),
        vec("guest-isolation-unknown", unsure_guest, "unknown", UNRESOLVED),
        vec("mode-unknown", unsure_mode, "unknown", UNRESOLVED),
        vec("unrecognised-mode", other_mode, "unknown", UNRESOLVED),
        vec("empty-no-wifi-network", wifi_rows(), "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]


# --- logging ---------------------------------------------------------------------


def audit(*rows: Any) -> dict[str, Any]:
    return one(EXCHANGE, "audit", *rows)


def settings(ingestion: bool | None, disabled: bool | None) -> dict[str, Any]:
    return {"unified_audit_log_enabled": ingestion, "audit_disabled": disabled}


def log_01(control: Mapping[str, Any]) -> list[Vector]:
    flag_unknown = audit(settings(True, None))
    mixed = audit(settings(True, False), settings(False, False))
    return [
        vec("ingestion-on-auditing-on", audit(settings(True, False)), "pass"),
        vec("ingestion-off", audit(settings(False, False)), "fail"),
        vec("auditing-disabled", audit(settings(True, True)), "fail"),
        vec("auditing-flag-unknown", flag_unknown, "unknown", UNRESOLVED),
        vec("ingestion-unknown", audit(settings(None, False)), "unknown", UNRESOLVED),
        vec("one-failing-setting-fails", mixed, "fail"),
        vec("empty-no-audit-record", audit(), "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]


def retention(licence: int | None, declared: int | None, note: bool) -> dict[str, Any]:
    """Evidence with a licence default and a manual item (with a number or not)."""
    manual: dict[str, Any] = {}
    if note:
        item = {
            "assurance": "manual-artefact",
            "outcome": None,
            "reviewed_on": "2026-10-01",
            "sha256": "a" * 64,
            "value": declared,
        }
        manual = {"manual": {"PC-LOG-02": item}}
    return ev({}, licence_log_retention_days=licence, **manual)


def licence(days: int | None) -> dict[str, Any]:
    return retention(days, None, False)


def log_02(control: Mapping[str, Any]) -> list[Vector]:
    top = whole(control, "pass_days")
    low = whole(control, "partial_days")
    no_number = retention(None, None, True)
    return [
        vec("licence-at-the-pass-days", licence(top), "pass"),
        vec("licence-one-day-short", licence(top - 1), "partial"),
        vec("licence-at-the-partial-days", licence(low), "partial"),
        vec("licence-one-day-below-partial", licence(low - 1), "fail"),
        vec("declared-archive-is-longer", retention(30, top * 2, True), "pass"),
        vec("licence-is-longer", retention(top * 2, 10, True), "pass"),
        vec("empty-nothing-known", licence(None), "unknown", LOS),
        vec("empty-archive-without-number", no_number, "unknown", LOS),
    ]


def alerts(*rows: Any) -> dict[str, Any]:
    return one(EXCHANGE, "alert", *rows)


def alert(**kw: Any) -> dict[str, Any]:
    row = {
        "alert_kind": "admin-role",
        "disabled": False,
        "recipient_count": 2,
        "last_acknowledged": ago(days=10),
    }
    return {**row, **kw}


def log_03(control: Mapping[str, Any]) -> list[Vector]:
    window = whole(control, "ack_days")
    exact = alert(last_acknowledged=ago(days=window))
    late = alert(last_acknowledged=ago(days=window, seconds=1))
    unreported = alerts(alert(recipient_count=None))
    return [
        vec("routed-and-acknowledged", alerts(alert()), "pass"),
        vec("acknowledged-exactly-at-the-window", alerts(exact), "pass"),
        vec("acknowledged-a-second-late", alerts(late), "partial"),
        vec("never-acknowledged", alerts(alert(last_acknowledged=None)), "partial"),
        vec("no-recipient", alerts(alert(recipient_count=0)), "fail"),
        vec("disabled-alert-does-not-count", alerts(alert(disabled=True)), "fail"),
        vec("alert-state-unknown", alerts(alert(disabled=None)), "unknown", UNRESOLVED),
        vec("unknown-recipients-not-reported", unreported, "unknown", LOS),
        vec("empty-no-alert", alerts(), "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]


KINDS = ("admin-role", "forwarding-rule", "risky-sign-in")


def kinds(*states: bool | None) -> dict[str, Any]:
    pairs = zip(KINDS, states, strict=True)
    return alerts(*[alert(alert_kind=kind, disabled=state) for kind, state in pairs])


def log_04(control: Mapping[str, Any]) -> list[Vector]:
    need = whole(control, "required_alerts")
    twice = alerts(
        alert(alert_kind="admin-role"),
        alert(alert_kind="admin-role"),
        alert(alert_kind="forwarding-rule", disabled=True),
    )
    all_on = kinds(False, False, False)
    could_pass = kinds(False, False, None)
    could_lift = kinds(True, True, None)
    return [
        vec("all-required-alerts-enabled", all_on, "pass", None, need, need),
        vec("two-enabled", kinds(False, False, True), "partial", None, 2, need),
        vec("one-enabled", kinds(False, True, True), "partial", None, 1, need),
        vec("none-enabled", kinds(True, True, True), "fail", None, 0, need),
        vec("duplicates-count-once", twice, "partial", None, 1, need),
        vec("unknown-could-reach-the-pass", could_pass, "unknown", UNRESOLVED),
        vec("unknown-could-lift-a-fail", could_lift, "unknown", UNRESOLVED),
        vec("empty-no-alert-kind", alerts(alert(alert_kind=None)), "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]


# --- governance ------------------------------------------------------------------


def leavers(*rows: Any) -> dict[str, Any]:
    return one("leavers-csv", "leaver", *rows)


def leaver(name: str, days: Mapping[str, int], enabled: bool | None) -> dict[str, Any]:
    return {"user": name, "leave_date": ago(**days), "account_enabled": enabled}


def gov_04(control: Mapping[str, Any]) -> list[Vector]:
    rule = control["rule"]
    grace = whole(control, "grace_days")
    gone = {"days": 10}
    three_off = [leaver(f"p{n}", gone, False) for n in range(3)]
    at_grace = leaver("p1", {"days": grace}, True)
    past = leaver("p1", {"days": grace, "seconds": 1}, True)
    future = leaver("p1", {"days": -5}, True)
    hit = count_status(rule, 1)
    on_time = leavers(at_grace)
    late = leavers(past)
    one_on = leavers(leaver("p1", gone, True), *three_off[:2])
    two_on = leavers(
        leaver("p1", gone, True),
        leaver("p2", gone, True),
        leaver("p3", gone, False),
    )
    ahead = leavers(future, leaver("p2", gone, False))
    unclear = leavers(leaver("p1", gone, None), leaver("p2", gone, False))
    unreported = leavers(leaver("p1", gone, None))
    return [
        vec("all-leavers-disabled", leavers(*three_off), "pass", None, 0, 3),
        vec("nobody-is-past-the-grace-period-yet", on_time, "pass", None, 0, 0),
        vec("a-second-past-the-grace-period", late, hit, None, 1, 1),
        vec("one-still-enabled", one_on, hit, None, 1, 3),
        vec("two-still-enabled", two_on, count_status(rule, 2), None, 2, 3),
        vec("a-future-leave-date-is-ignored", ahead, "pass", None, 0, 1),
        vec("account-state-unknown", unclear, "unknown", UNRESOLVED),
        vec("unknown-account-state-not-reported", unreported, "unknown", LOS),
        vec("empty-no-leaver", leavers(), "unknown", LOS),
        vec("unknown-source-missing", ev(), "unknown", LOS),
    ]


RULE_VECTORS: dict[str, Maker] = {
    "PC-BCK-03": bck_03,
    "PC-BCK-04": bck_04,
    "PC-NET-01": net_01,
    "PC-NET-02": net_02,
    "PC-NET-03": net_03,
    "PC-NET-04": net_04,
    "PC-LOG-01": log_01,
    "PC-LOG-02": log_02,
    "PC-LOG-03": log_03,
    "PC-LOG-04": log_04,
    "PC-GOV-04": gov_04,
}
