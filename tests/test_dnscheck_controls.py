"""What the controls PC-EML-01 to PC-EML-03 make of a DNS check (phase 7).

The check engine reads the facts in the shape `app/checks/email.py` documents. These
tests run the real check (against a fake resolver) and give its columns to the real
rules, one record shape at a time, so the documented results are the ones the whole
chain gives, and a failed lookup can be seen never to turn a pass into a fail.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.checks.dnscheck import (
    RESOLVER_ERROR,
    SERVFAIL,
    TIMEOUT,
    DnsCheck,
    LookupFailure,
    run_checks,
)
from app.checks.engine import evaluate_control
from app.checks.library import load_library
from app.checks.model import ControlResult, Evidence, SourceFacts
from dns_helpers import Zone, resolver_for, zone

LIBRARY = load_library()
DOMAIN = "client.example"
AT = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
AS_OF = AT + timedelta(days=3)
PROVIDER = "spf.protection.outlook.com"
SPF = f"v=spf1 include:{PROVIDER} -all"
DMARC = "v=DMARC1; p=reject; rua=mailto:dmarc@client.example"
EML = ("PC-EML-01", "PC-EML-02", "PC-EML-03")


def good_zone() -> Zone:
    return zone(DOMAIN, spf=[SPF], dmarc=[DMARC], cnames=["selector1"])


def check_of(table: Zone, domains: tuple[str, ...] = (DOMAIN,)) -> DnsCheck:
    return run_checks(resolver_for(table), list(domains), captured_at=AT)


def evidence_of(check: DnsCheck, enabled: bool | None = True) -> Evidence:
    """The stored facts of a run, and the Exchange DKIM rows for the same domains."""
    rows = [
        ("dns.domain", {**item.fact_value(), "domain": f"p{number}"})
        for number, item in enumerate(check.domains)
    ]
    sources = {"dns-check": SourceFacts.from_facts(check.captured_at, rows)}
    if enabled is not None:
        dkim = [
            ("exchange.dkim", {"domain": f"p{number}", "enabled": enabled})
            for number, _ in enumerate(check.domains)
        ]
        sources["exchange-export"] = SourceFacts.from_facts(AT, dkim)
    return Evidence(as_of=AS_OF, sources=sources)


def results(evidence: Evidence) -> dict[str, ControlResult]:
    return {
        control_id: evaluate_control(LIBRARY, LIBRARY.control(control_id), evidence)
        for control_id in EML
    }


def status_of(table: Zone, control_id: str) -> str:
    return results(evidence_of(check_of(table)))[control_id].status


def with_spf(record: list[str]) -> Zone:
    return zone(DOMAIN, spf=record, dmarc=[DMARC], cnames=["selector1"])


def with_dmarc(record: list[str]) -> Zone:
    return zone(DOMAIN, spf=[SPF], dmarc=record, cnames=["selector1"])


# --- PC-EML-01: SPF -------------------------------------------------------------------

SPF_RESULTS = [
    ("hard-fail-with-provider", [SPF], "pass"),
    ("soft-fail-with-provider", [f"v=spf1 include:{PROVIDER} ~all"], "pass"),
    ("fail-without-provider", ["v=spf1 ip4:192.0.2.0/24 -all"], "fail"),
    ("pass-all", [f"v=spf1 include:{PROVIDER} +all"], "fail"),
    ("missing", [], "fail"),
    ("two-records", [SPF, "v=spf1 -all"], "fail"),
]


@pytest.mark.parametrize(
    ("record", "status"),
    [(item[1], item[2]) for item in SPF_RESULTS],
    ids=[item[0] for item in SPF_RESULTS],
)
def test_pc_eml_01_follows_the_spf_record(record: list[str], status: str) -> None:
    assert status_of(with_spf(record), "PC-EML-01") == status


@pytest.mark.parametrize(
    "record",
    [f"v=spf1 include:{PROVIDER} ?all", f"v=spf1 include:{PROVIDER}"],
    ids=["neutral", "no-all"],
)
def test_a_neutral_spf_record_never_passes_pc_eml_01(record: str) -> None:
    result = results(evidence_of(check_of(with_spf([record]))))["PC-EML-01"]
    assert result.status != "pass"
    assert (result.numerator, result.denominator) == (0, 1)


def test_pc_eml_01_is_unknown_when_the_provider_could_not_be_checked() -> None:
    table = with_spf(["v=spf1 include:mail.other.example -all"])
    table[("mail.other.example", "TXT")] = LookupFailure(TIMEOUT)
    result = results(evidence_of(check_of(table)))["PC-EML-01"]
    assert (result.status, result.reason) == ("unknown", "lookup_failed")


def test_eleven_includes_are_reported_and_leave_the_result_to_the_rule() -> None:
    includes = " ".join(f"include:s{n}.example.net" for n in range(11))
    check = check_of(with_spf([f"v=spf1 {includes} -all"]))
    [domain] = check.domains
    assert domain.fact_value()["spf_lookups"] == 11
    assert domain.fact_value()["spf_over_limit"] is True
    result = results(evidence_of(check))["PC-EML-01"]
    assert (result.status, result.reason) == ("unknown", "lookup_failed")


# --- PC-EML-03: DMARC -----------------------------------------------------------------

RUA = "rua=mailto:dmarc@client.example"
DMARC_RESULTS = [
    ("none-with-rua", f"v=DMARC1; p=none; {RUA}", "partial"),
    ("none-without-rua", "v=DMARC1; p=none", "fail"),
    ("quarantine-at-50-percent", f"v=DMARC1; p=quarantine; pct=50; {RUA}", "partial"),
    ("quarantine", f"v=DMARC1; p=quarantine; {RUA}", "pass"),
    ("quarantine-without-rua", "v=DMARC1; p=quarantine", "partial"),
    ("reject", f"v=DMARC1; p=reject; {RUA}", "pass"),
    ("reject-at-90-percent", f"v=DMARC1; p=reject; pct=90; {RUA}", "partial"),
]


@pytest.mark.parametrize(
    ("record", "status"),
    [(item[1], item[2]) for item in DMARC_RESULTS],
    ids=[item[0] for item in DMARC_RESULTS],
)
def test_pc_eml_03_follows_the_dmarc_record(record: str, status: str) -> None:
    assert status_of(with_dmarc([record]), "PC-EML-03") == status


def test_pc_eml_03_fails_for_a_missing_or_a_doubled_record() -> None:
    assert status_of(with_dmarc([]), "PC-EML-03") == "fail"
    assert status_of(with_dmarc([DMARC, "v=DMARC1; p=none"]), "PC-EML-03") == "fail"


def test_pc_eml_03_is_unknown_for_a_policy_or_percentage_it_cannot_read() -> None:
    for record in ("v=DMARC1; p=bogus; " + RUA, "v=DMARC1; p=reject; pct=abc; " + RUA):
        result = results(evidence_of(check_of(with_dmarc([record]))))["PC-EML-03"]
        assert (result.status, result.reason) == ("unknown", "lookup_failed"), record


# --- PC-EML-02: DKIM ------------------------------------------------------------------


def test_pc_eml_02_needs_signing_on_and_the_selector_published() -> None:
    check = check_of(good_zone())
    assert results(evidence_of(check, enabled=True))["PC-EML-02"].status == "pass"
    assert results(evidence_of(check, enabled=False))["PC-EML-02"].status == "fail"
    bare = check_of(zone(DOMAIN, spf=[SPF], dmarc=[DMARC]))
    assert results(evidence_of(bare, enabled=True))["PC-EML-02"].status == "fail"


def test_pc_eml_02_is_unknown_without_the_exchange_export() -> None:
    result = results(evidence_of(check_of(good_zone()), enabled=None))["PC-EML-02"]
    assert (result.status, result.reason) == ("unknown", "licence_or_scope")


# --- a resolver failure never turns a pass into a fail --------------------------------

FAILING = [
    ("apex", (DOMAIN, "TXT")),
    ("dmarc", (f"_dmarc.{DOMAIN}", "TXT")),
    ("selector-cname", (f"selector1._domainkey.{DOMAIN}", "CNAME")),
    ("selector-key", (f"selector2._domainkey.{DOMAIN}", "TXT")),
]


def test_the_baseline_is_a_pass_on_all_three_controls() -> None:
    found = results(evidence_of(check_of(good_zone())))
    assert {key: item.status for key, item in found.items()} == {
        "PC-EML-01": "pass",
        "PC-EML-02": "pass",
        "PC-EML-03": "pass",
    }


@pytest.mark.parametrize("reason", [TIMEOUT, SERVFAIL, RESOLVER_ERROR])
@pytest.mark.parametrize(("where", "key"), FAILING, ids=[item[0] for item in FAILING])
def test_a_failed_lookup_is_unknown_with_a_reason_and_never_a_fail(
    reason: str, where: str, key: tuple[str, str]
) -> None:
    table = good_zone()
    table[key] = LookupFailure(reason)
    found = results(evidence_of(check_of(table)))
    for control_id, result in found.items():
        assert result.status == "unknown", (control_id, result)
        assert result.reason == "lookup_failed", (control_id, result)


def test_a_failed_domain_cannot_lift_or_sink_the_others() -> None:
    table = {**good_zone(), ("down.example", "TXT"): LookupFailure(TIMEOUT)}
    check = check_of(table, (DOMAIN, "down.example"))
    found = results(evidence_of(check))
    assert found["PC-EML-03"].status == "unknown"
    assert found["PC-EML-01"].status == "unknown"


def test_a_failed_domain_next_to_a_failing_one_is_still_a_fail() -> None:
    """A certain failure stays a failure; only the unknown part stays unknown."""
    table = {
        **zone("weak.example", spf=["v=spf1 -all"], dmarc=["v=DMARC1; p=none"]),
        ("down.example", "TXT"): LookupFailure(TIMEOUT),
    }
    check = check_of(table, ("weak.example", "down.example"))
    assert results(evidence_of(check))["PC-EML-03"].status == "fail"


# --- results carry the capture time ---------------------------------------------------


def test_the_results_carry_the_capture_time_and_its_age() -> None:
    found = results(evidence_of(check_of(good_zone())))
    for control_id in ("PC-EML-01", "PC-EML-03"):
        assert found[control_id].evidence_at == AT
        assert found[control_id].age_days == 3
        assert found[control_id].assurance == "automatic-export"


def test_without_a_dns_check_the_three_controls_stay_unknown() -> None:
    evidence = Evidence(as_of=AS_OF)
    found = results(evidence)
    for result in found.values():
        assert (result.status, result.reason) == ("unknown", "licence_or_scope")


def test_old_dns_results_go_stale_at_the_maximum_age_of_the_control() -> None:
    check = check_of(good_zone())
    limit = LIBRARY.control("PC-EML-03").max_age_days.automatic
    assert limit is not None
    late: Any = evidence_of(check)
    stale = Evidence(as_of=AT + timedelta(days=limit + 1), sources=late.sources)
    assert results(stale)["PC-EML-03"].stale is True
    fresh = Evidence(as_of=AT + timedelta(days=limit), sources=late.sources)
    assert results(fresh)["PC-EML-03"].stale is False
