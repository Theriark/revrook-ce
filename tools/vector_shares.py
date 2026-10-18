"""Vectors of the share controls (see tools/make_vectors.py).

A share control is a population of 100 with `good` rows that meet the rule, so every
threshold of the file (all of them whole percents) is hit exactly, one below it and
one above it.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from tools.vector_support import (
    EMPTY,
    LOS,
    RECENT,
    Vector,
    ago,
    at_least,
    ev,
    of_hundred,
    rep,
    share_status,
    src,
    vec,
)

Make = Callable[[int, int, int], dict[str, Any]]


@dataclass(frozen=True)
class Spec:
    """A share control over rows of one kind: three kinds of row."""

    adapter: str
    kind: str
    id_column: str
    base: Mapping[str, Any]
    good: Mapping[str, Any]
    bad: Mapping[str, Any]
    unknown: Mapping[str, Any]


RMM = {"os": "windows", "form_factor": "workstation", "last_seen": RECENT}

SPECS: dict[str, Spec] = {
    "PC-ACC-01": Spec(
        adapter="entra-registration",
        kind="user",
        id_column="user",
        base={"user_type": "member"},
        good={"mfa_registered": True, "mfa_capable": True},
        bad={"mfa_registered": False, "mfa_capable": True},
        unknown={"mfa_registered": None, "mfa_capable": None},
    ),
    "PC-DEV-02": Spec(
        adapter="device-inventory",
        kind="device",
        id_column="device",
        base=RMM,
        good={"pending_critical_updates": 0, "last_patch": ago(days=1)},
        bad={"pending_critical_updates": 2, "last_patch": ago(days=60)},
        unknown={"pending_critical_updates": None, "last_patch": None},
    ),
    "PC-DEV-04": Spec(
        adapter="device-inventory",
        kind="device",
        id_column="device",
        base=RMM,
        good={"disk_encrypted": True},
        bad={"disk_encrypted": False},
        unknown={"disk_encrypted": None},
    ),
    "PC-DEV-05": Spec(
        adapter="intune-devices",
        kind="device",
        id_column="device",
        base={"os": "windows", "last_contact": RECENT},
        good={"compliance": "compliant"},
        bad={"compliance": "noncompliant"},
        unknown={"compliance": None},
    ),
    "PC-DEV-07": Spec(
        adapter="device-inventory",
        kind="device",
        id_column="device",
        base=RMM,
        good={"local_admin_count": 2},
        bad={"local_admin_count": 3},
        unknown={"local_admin_count": None},
    ),
    "PC-END-01": Spec(
        adapter="device-inventory",
        kind="device",
        id_column="device",
        base=RMM,
        good={"av_status": "protected"},
        bad={"av_status": "disabled"},
        unknown={"av_status": None},
    ),
    "PC-END-02": Spec(
        adapter="device-inventory",
        kind="device",
        id_column="device",
        base=RMM,
        good={"av_signature_date": ago(days=3)},
        bad={"av_signature_date": ago(days=3, seconds=1)},
        unknown={"av_signature_date": None},
    ),
    "PC-END-04": Spec(
        adapter="device-inventory",
        kind="device",
        id_column="device",
        base=RMM,
        good={"tamper_protection": True},
        bad={"tamper_protection": False},
        unknown={"tamper_protection": None},
    ),
    "PC-NET-05": Spec(
        adapter="device-inventory",
        kind="device",
        id_column="device",
        base=RMM,
        good={"dns_filter_active": True},
        bad={"dns_filter_active": False},
        unknown={"dns_filter_active": None},
    ),
    "PC-BCK-05": Spec(
        adapter="backup-export",
        kind="job",
        id_column="asset",
        base={},
        good={"encrypted": True, "retention_days": 30},
        bad={"encrypted": True, "retention_days": 29},
        unknown={"encrypted": None, "retention_days": None},
    ),
    "PC-LOG-06": Spec(
        adapter="network-export",
        kind="device",
        id_column="device",
        base={"perimeter": True},
        good={"syslog_target": True},
        bad={"syslog_target": False},
        unknown={"syslog_target": None},
    ),
}


def population(spec: Spec, good: int, bad: int, unknown: int) -> dict[str, Any]:
    """Evidence with that many rows of each kind (none at all: an empty source)."""
    rows: list[Any] = []
    parts = ((good, "g", spec.good), (bad, "b", spec.bad), (unknown, "u", spec.unknown))
    for count, prefix, extra in parts:
        if count:
            row = {**spec.base, **extra}
            rows.append(rep(count, row, spec.id_column, prefix))
    return ev({spec.adapter: src({spec.kind: rows})})


def share_vectors(
    rule: Mapping[str, Any],
    make: Make,
    absent_reason: str = LOS,
) -> list[Vector]:
    """The vectors of a share rule; `make(good, bad, unknown)` builds the evidence.

    Rows that cannot be told are left out of the share; a population of nothing
    but such rows is an absent field; no row at all is an empty population.
    """
    top = of_hundred(at_least(rule, "pass"))
    low = of_hundred(at_least(rule, "partial"))
    cases = [
        ("pass-at-threshold", top),
        ("pass-all", 100),
        ("partial-just-below-pass", top - 1),
        ("partial-at-threshold", low),
        ("fail-just-below-partial", low - 1),
        ("fail-none", 0),
    ]
    found: list[Vector] = []
    for name, good in cases:
        status = share_status(rule, good, 100)
        found.append(vec(name, make(good, 100 - good, 0), status, None, good, 100))
    status = share_status(rule, top, 100)
    left_out = make(top, 100 - top, 10)
    found += [
        vec("unknown-rows-left-out", left_out, status, None, top, 100),
        vec("unknown-field-absent", make(0, 0, 5), "unknown", absent_reason),
        vec("unknown-source-missing", ev(), "unknown", absent_reason),
        vec("empty-population", make(0, 0, 0), "unknown", EMPTY),
    ]
    return found


def spec_vectors(control_id: str, rule: Mapping[str, Any]) -> list[Vector]:
    spec = SPECS[control_id]

    def make(good: int, bad: int, unknown: int) -> dict[str, Any]:
        if good == bad == unknown == 0:
            return ev({spec.adapter: src({spec.kind: []})})
        return population(spec, good, bad, unknown)

    return share_vectors(rule, make)


# --- PC-DEV-01: devices in both exports -------------------------------------------


def dev_01(control: Mapping[str, Any]) -> list[Vector]:
    rule = control["rule"]

    def devices(both: int, rmm_only: int, stale: int) -> dict[str, Any]:
        rmm = [
            rep(both, {"last_seen": RECENT}, "device", "d"),
            rep(rmm_only, {"last_seen": RECENT}, "device", "x"),
        ]
        stale_row = {"last_contact": ago(days=15)}
        mdm = [
            rep(both, {"last_contact": RECENT}, "device", "d"),
            rep(stale, stale_row, "device", "s"),
        ]
        return ev(
            {
                "device-inventory": src({"device": rmm}),
                "intune-devices": src({"device": mdm}),
            }
        )

    def make(good: int, bad: int, unknown: int) -> dict[str, Any]:
        if good == bad == unknown == 0:
            empty = src({"device": []})
            return ev({"device-inventory": empty, "intune-devices": empty})
        if unknown and not (good or bad):
            return ev({"device-inventory": src({"device": [rep(5, {}, "device")]})})
        return devices(good, bad, 0)

    found = share_vectors(rule, make)
    found += [
        vec("inactive-not-counted", devices(95, 0, 5), "pass", None, 95, 95),
        vec("empty-no-active-device", devices(0, 0, 0), "unknown", EMPTY),
    ]
    return found


# --- PC-BCK-01: in-scope servers with a recent successful backup ------------------

JOB = {"schedule_hours": 24, "last_result": "success", "last_success": ago(hours=1)}
SERVER = {"form_factor": "server", "last_seen": RECENT}


def servers(protected: int, job: Mapping[str, Any] = JOB) -> dict[str, Any]:
    """100 active servers, `protected` of them with a backup job (as `job` says)."""
    inventory = [rep(100, SERVER, "device", "s")]
    jobs = [rep(protected, job, "asset", "s"), rep(1, JOB, "asset", "other")]
    return ev(
        {
            "device-inventory": src({"device": inventory}),
            "backup-export": src({"job": jobs}),
        }
    )


def bck_01(control: Mapping[str, Any]) -> list[Vector]:
    rule = control["rule"]
    hours = 24 * Fraction(control["params"]["schedule_factor"])
    assert hours.denominator == 1, "the schedule factor must give whole hours"

    def make(good: int, bad: int, unknown: int) -> dict[str, Any]:
        if good == bad == unknown == 0:
            empty = [rep(3, {"form_factor": "workstation", "last_seen": RECENT})]
            return ev(
                {
                    "device-inventory": src({"device": empty}),
                    "backup-export": src({"job": [rep(1, JOB, "asset", "o")]}),
                }
            )
        if unknown and not (good or bad):
            return ev({"backup-export": src({"job": [rep(5, JOB, "asset", "o")]})})
        return servers(good)

    found = share_vectors(rule, make)
    # A schedule of 24 hours times the factor of the file is the longest age.
    limit = int(hours)
    exact = {**JOB, "last_success": ago(hours=limit)}
    late = {**JOB, "last_success": ago(hours=limit, minutes=1)}
    failed = {**JOB, "last_result": "failed"}
    idle = {**SERVER, "last_seen": ago(days=15)}
    inventory = [rep(90, SERVER, "device", "s"), rep(10, idle, "device", "o")]
    stale = ev(
        {
            "device-inventory": src({"device": inventory}),
            "backup-export": src({"job": [rep(90, JOB, "asset", "s")]}),
        }
    )
    no_schedule = {**JOB, "schedule_hours": None}
    unscheduled = ev(
        {
            "device-inventory": src({"device": [rep(100, SERVER, "device", "s")]}),
            "backup-export": src({"job": [rep(100, no_schedule, "asset", "s")]}),
        }
    )
    unlabelled = [rep(5, {"last_seen": RECENT}, "device")]
    no_form = ev(
        {
            "device-inventory": src({"device": unlabelled}),
            "backup-export": src({"job": [rep(1, JOB, "asset", "o")]}),
        }
    )
    found += [
        vec("success-at-1.5-schedules", servers(100, exact), "pass", None, 100, 100),
        vec("success-a-minute-too-old", servers(100, late), "fail", None, 0, 100),
        vec("last-backup-failed", servers(100, failed), "fail", None, 0, 100),
        vec("inactive-servers-not-in-scope", stale, "pass", None, 90, 90),
        vec("unknown-no-schedule", unscheduled, "unknown", LOS),
        vec("unknown-no-form-factor", no_form, "unknown", LOS),
    ]
    return found


# --- PC-GOV-03: members trained within the window ---------------------------------


def trained(good: int, completed: Mapping[str, Any], guests: int = 0) -> dict[str, Any]:
    """100 members, `good` of them with a completion (and some untrained guests)."""
    users = [rep(100, {"user_type": "member"}, "user", "u")]
    if guests:
        users.append(rep(guests, {"user_type": "guest"}, "user", "g"))
    done = [rep(good, completed, "user", "u")]
    return ev(
        {
            "entra-registration": src({"user": users}),
            "training-csv": src({"completion": done}),
        }
    )


def gov_03(control: Mapping[str, Any]) -> list[Vector]:
    rule = control["rule"]
    window = int(control["params"]["training_days"])
    recent = {"completed_utc": ago(days=10)}

    def make(good: int, bad: int, unknown: int) -> dict[str, Any]:
        if good == bad == unknown == 0:
            nobody = src({"user": []})
            return ev({"entra-registration": nobody, "training-csv": src({})})
        if unknown and not (good or bad):
            return ev({"training-csv": src({"completion": [rep(5, recent, "user")]})})
        return trained(good, recent)

    found = share_vectors(rule, make)
    exact = {"completed_utc": ago(days=window)}
    late = {"completed_utc": ago(days=window, seconds=1)}
    twice = [rep(100, recent, "user", "u"), rep(100, recent, "user", "u")]
    users = [rep(100, {"user_type": "member"}, "user", "u")]
    both = ev(
        {
            "entra-registration": src({"user": users}),
            "training-csv": src({"completion": twice}),
        }
    )
    found += [
        vec("completion-365-days-ago", trained(100, exact), "pass", None, 100, 100),
        vec("completion-a-second-too-old", trained(100, late), "fail", None, 0, 100),
        vec("guests-are-not-staff", trained(100, recent, 20), "pass", None, 100, 100),
        vec("two-courses-count-once", both, "pass", None, 100, 100),
    ]
    return found


# --- evidence with every source, for the controls CE cannot measure ----------------


def rich_evidence() -> dict[str, Any]:
    """A little of every source: no unavailable control may change because of it."""
    members = rep(2, {"user_type": "member"}, "user")
    windows = rep(2, {"os": "windows"}, "device", "d")
    mailboxes = rep(2, {"recipient_type": "user"}, "mailbox")
    admin = rep(1, {"global_admin": True}, "user")
    return ev(
        {
            "entra-registration": src({"user": [members]}),
            "device-inventory": src({"device": [rep(2, RMM, "device", "d")]}),
            "intune-devices": src({"device": [windows]}),
            "exchange-export": src({"mailbox": [mailboxes]}),
            "network-export": src({"device": [rep(1, {"perimeter": True}, "device")]}),
            "backup-export": src({"job": [rep(2, JOB, "asset")]}),
            "training-csv": src({"completion": [rep(2, {}, "user")]}),
            "leavers-csv": src({"leaver": [rep(1, {}, "user")]}),
            "conditional-access": src(
                {"policy": []}, {"tenant_state": "security-defaults"}
            ),
            "directory-roles": src({"assignment": [admin]}),
        }
    )
