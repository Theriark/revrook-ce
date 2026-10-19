"""Fixes from the independent checks of phase 7 (THE-312 and THE-313).

* F1 / NB-1: an apex with more than 50 TXT answers cannot be read in full, so the
  domain is a failed lookup (unknown), not a domain without SPF (a false fail).
* F2: an SPF (or DMARC, or DKIM) record longer than 8192 characters is a failed
  lookup, not a record that reads as neutral. A long text that nothing reads is cut.
* F3: docs/dns-check.md says which neutral result is a domain state and which is the
  control result.
* F5 / NB-2: an include that appears twice counts twice, as a receiver counts it.
* F7 / NB-3: the lookups run before a database transaction opens, and a run has a
  deadline.
* NB-4: a DMARC record the check cannot read is unresolved, not a failed lookup.
* NB-6: the network guard also stops a UDP packet and records what it stopped.
"""

import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import QueuePool

from app.checks.dnscheck import (
    ANSWER_TOO_LARGE,
    FAILURE_REASONS,
    MAX_ANSWERS,
    MAX_TEXT_LENGTH,
    TIMEOUT,
    TOO_MANY_ANSWERS,
    DnsCheck,
    DomainResult,
    LookupFailure,
    run_checks,
)
from app.checks.engine import evaluate_control
from app.checks.library import load_library
from app.checks.model import ControlResult, Evidence, SourceFacts
from app.dns_service import look_up_dns
from dns_helpers import StaticResolver, Zone, resolver_for, zone
from helpers import issue_token

LIBRARY = load_library()
ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "client.example"
AT = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
PROVIDER = "spf.protection.outlook.com"
SPF = f"v=spf1 include:{PROVIDER} -all"
DMARC = "v=DMARC1; p=reject; rua=mailto:dmarc@client.example"
GOOD = zone(DOMAIN, spf=[SPF], dmarc=[DMARC], cnames=["selector1"])


def with_spf(records: list[str]) -> Zone:
    return zone(DOMAIN, spf=records, dmarc=[DMARC], cnames=["selector1"])


def with_dmarc(records: list[str]) -> Zone:
    return zone(DOMAIN, spf=[SPF], dmarc=records, cnames=["selector1"])


def check_of(table: Zone, domains: tuple[str, ...] = (DOMAIN,)) -> DnsCheck:
    return run_checks(resolver_for(table), list(domains), captured_at=AT)


def only(table: Zone) -> DomainResult:
    [result] = check_of(table).domains
    return result


def control(
    table: Zone, control_id: str, domains: tuple[str, ...] = (DOMAIN,)
) -> ControlResult:
    """The control result the real rules give for a run against the table."""
    check = check_of(table, domains)
    rows = [
        ("dns.domain", {**item.fact_value(), "domain": f"p{number}"})
        for number, item in enumerate(check.domains)
    ]
    facts = SourceFacts.from_facts(check.captured_at, rows)
    evidence = Evidence(as_of=AT + timedelta(days=3), sources={"dns-check": facts})
    return evaluate_control(LIBRARY, LIBRARY.control(control_id), evidence)


def filler(count: int) -> list[str]:
    return [f"site-verification={number}" for number in range(count)]


# --- F1: more than 50 answers ------------------------------------------------------


def test_an_spf_record_among_too_many_answers_is_unknown_and_not_a_fail() -> None:
    table = with_spf([*filler(MAX_ANSWERS), SPF])
    domain = only(table)
    assert domain.failure == TOO_MANY_ANSWERS and domain.spf is None
    found = control(table, "PC-EML-01")
    assert (found.status, found.reason) == ("unknown", "lookup_failed")


def test_exactly_the_maximum_number_of_answers_is_still_read() -> None:
    table = with_spf([*filler(MAX_ANSWERS - 1), SPF])
    assert only(table).failure is None
    assert control(table, "PC-EML-01").status == "pass"


def test_too_many_dmarc_answers_are_unknown_too() -> None:
    table = with_dmarc([*filler(MAX_ANSWERS), DMARC])
    assert only(table).failure == TOO_MANY_ANSWERS
    assert control(table, "PC-EML-03").status == "unknown"


def test_the_new_failure_reasons_are_known_to_the_importer() -> None:
    assert {TOO_MANY_ANSWERS, ANSWER_TOO_LARGE} <= FAILURE_REASONS


# --- F2: a record longer than 8192 characters --------------------------------------


def long_spf() -> str:
    return "v=spf1 " + " ".join(f"ip4:10.{n // 250}.{n % 250}.1" for n in range(2000))


def test_an_spf_record_over_the_maximum_length_is_unknown_and_not_neutral() -> None:
    record = long_spf() + " -all"
    assert len(record) > MAX_TEXT_LENGTH
    table = with_spf([record])
    domain = only(table)
    assert domain.failure == ANSWER_TOO_LARGE and domain.spf is None
    found = control(table, "PC-EML-01")
    assert (found.status, found.reason) == ("unknown", "lookup_failed")


def test_an_spf_record_at_the_maximum_length_is_read_whole() -> None:
    padding = " ip4:192.0.2.1" * ((MAX_TEXT_LENGTH - 60) // 14)
    record = f"v=spf1 include:{PROVIDER}{padding} -all"
    assert MAX_TEXT_LENGTH - 100 < len(record) <= MAX_TEXT_LENGTH
    table = with_spf([record])
    assert only(table).failure is None
    assert control(table, "PC-EML-01").status == "pass"


def test_a_long_text_nothing_reads_is_cut_and_the_spf_record_counts() -> None:
    table = with_spf(["x" * (MAX_TEXT_LENGTH + 500), SPF])
    assert only(table).failure is None
    assert control(table, "PC-EML-01").status == "pass"


def test_a_dmarc_record_over_the_maximum_length_is_unknown() -> None:
    record = DMARC + "; ruf=" + ",".join(["mailto:a@client.example"] * 500)
    assert len(record) > MAX_TEXT_LENGTH
    assert only(with_dmarc([record])).failure == ANSWER_TOO_LARGE


# --- F3: the neutral wording of the documentation ----------------------------------


def test_the_documentation_tells_a_domain_state_from_the_control_result() -> None:
    text = (ROOT / "docs" / "dns-check.md").read_text(encoding="utf-8")
    assert "| Domain state |" in text
    assert "PC-EML-01 counts only the domains that pass" in text
    neutral = next(line for line in text.splitlines() if "`?all`" in line)
    assert neutral.rstrip().endswith("| partial |")


# --- F5 / NB-2: a repeated include -------------------------------------------------


def spf_zone(record: str, nested: dict[str, str] | None = None) -> Zone:
    """The domain with `record`, and the SPF records of the names in `nested`."""
    table = zone(DOMAIN, spf=[record], dmarc=[DMARC], cnames=["selector1"])
    for name, text in (nested or {}).items():
        table[(name, "TXT")] = [text]
    return table


def spf_of(table: Zone) -> tuple[int | None, bool | None, StaticResolver]:
    resolver = resolver_for(table)
    [domain] = run_checks(resolver, [DOMAIN], captured_at=AT).domains
    assert domain.spf is not None
    return domain.spf.lookups, domain.spf.over_limit, resolver


def test_an_include_that_appears_twice_counts_twice_and_is_asked_once() -> None:
    table = spf_zone(
        "v=spf1 include:a.example.net include:a.example.net -all",
        {"a.example.net": "v=spf1 a mx ptr -all"},
    )
    lookups, over, resolver = spf_of(table)
    assert (lookups, over) == (8, False)
    assert resolver.queries.count(("a.example.net", "TXT")) == 1


def test_a_repeated_include_can_take_a_record_over_the_limit() -> None:
    table = spf_zone(
        "v=spf1 include:a.example.net include:a.example.net -all",
        {"a.example.net": "v=spf1 a mx a mx a mx -all"},
    )
    lookups, over, _ = spf_of(table)
    assert (lookups, over) == (11, True)


def test_an_include_found_in_two_included_records_counts_in_each() -> None:
    table = spf_zone(
        "v=spf1 include:a.example.net include:b.example.net -all",
        {
            "a.example.net": "v=spf1 include:c.example.net -all",
            "b.example.net": "v=spf1 include:c.example.net -all",
            "c.example.net": "v=spf1 ip4:192.0.2.0/24 mx -all",
        },
    )
    lookups, over, resolver = spf_of(table)
    # a and b, c in each, and the mx of c in each
    assert (lookups, over) == (6, False)
    assert resolver.queries.count(("c.example.net", "TXT")) == 1


def test_two_records_that_include_each_other_end_the_walk() -> None:
    table = spf_zone(
        "v=spf1 include:a.example.net -all",
        {
            "a.example.net": "v=spf1 include:b.example.net -all",
            "b.example.net": "v=spf1 include:a.example.net -all",
        },
    )
    lookups, over, _ = spf_of(table)
    assert (lookups, over) == (3, False)


def test_an_include_of_the_apex_itself_is_a_loop() -> None:
    lookups, over, resolver = spf_of(spf_zone(f"v=spf1 include:{DOMAIN} -all"))
    assert (lookups, over) == (1, False)
    assert resolver.queries.count((DOMAIN, "TXT")) == 1


# --- F7 / NB-3: the deadline and the transaction -----------------------------------


class SlowResolver(StaticResolver):
    """Every question takes `step` seconds of a fake clock."""

    def __init__(self, step: float) -> None:
        super().__init__()
        self.now = 0.0
        self.step = step

    def lookup(self, name: str, rdtype: str) -> tuple[str, ...]:
        self.now += self.step
        return super().lookup(name, rdtype)


def test_a_run_has_a_deadline_after_which_every_domain_times_out() -> None:
    resolver = SlowResolver(step=30.0)
    domains = [f"d{number}.example" for number in range(5)]
    check = run_checks(
        resolver,
        domains,
        captured_at=AT,
        max_seconds=60.0,
        clock=lambda: resolver.now,
    )
    assert [item.failure for item in check.domains] == [TIMEOUT] * 5
    assert len(resolver.queries) == 2, "nothing is asked once the deadline has passed"


def test_a_run_inside_its_deadline_is_not_cut() -> None:
    check = run_checks(
        resolver_for(GOOD),
        [DOMAIN],
        captured_at=AT,
        max_seconds=60.0,
        clock=lambda: 0.0,
    )
    assert check.domains[0].failure is None


class PoolProbe(StaticResolver):
    """Notes how many database connections are checked out at each question."""

    def __init__(self, engine: AsyncEngine, answers: Zone) -> None:
        super().__init__(answers)
        pool = engine.sync_engine.pool
        assert isinstance(pool, QueuePool)
        self.pool = pool
        self.checked_out: list[int] = []

    def lookup(self, name: str, rdtype: str) -> tuple[str, ...]:
        self.checked_out.append(self.pool.checkedout())
        return super().lookup(name, rdtype)


def path_of(client_id: int) -> str:
    return f"/api/v1/clients/{client_id}/dns-check"


async def new_client(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> tuple[dict[str, str], int]:
    token = {"Authorization": f"Bearer {await issue_token(db_engine)}"}
    created = await client.post(
        "/api/v1/clients", headers=token, json={"name": "Dns Client Ltd"}
    )
    return token, created.json()["id"]


async def test_no_database_connection_is_held_while_the_dns_answers(
    client: httpx.AsyncClient, db_engine: AsyncEngine, web_app: FastAPI
) -> None:
    token, client_id = await new_client(client, db_engine)
    probe = PoolProbe(db_engine, GOOD)
    web_app.state.dns_resolver = probe
    posted = await client.post(
        path_of(client_id), headers=token, json={"domains": [DOMAIN]}
    )
    assert posted.status_code == 201
    assert probe.checked_out and set(probe.checked_out) == {0}


async def test_look_up_dns_needs_no_database_and_refuses_a_naive_time() -> None:
    check = await look_up_dns(resolver_for(GOOD), [DOMAIN], now=AT)
    assert check.domains[0].failure is None
    with pytest.raises(ValueError, match="timezone"):
        await look_up_dns(
            resolver_for(GOOD), [DOMAIN], now=datetime(2026, 10, 18, 9, 0)
        )


# --- NB-4: a DMARC record that cannot be read --------------------------------------


@pytest.mark.parametrize(
    "record",
    ["v=DMARC1; p=bogus", "v=DMARC1; p=reject; pct=abc"],
    ids=["policy", "percentage"],
)
def test_a_malformed_dmarc_record_is_unresolved_not_a_failed_lookup(
    record: str,
) -> None:
    found = control(with_dmarc([record]), "PC-EML-03")
    assert (found.status, found.reason) == ("unknown", "unresolved_values")


def test_a_failed_lookup_stays_a_failed_lookup_next_to_a_malformed_record() -> None:
    table = {
        **with_dmarc(["v=DMARC1; p=bogus"]),
        **zone("other.example", spf=[SPF], dmarc=[DMARC]),
        ("_dmarc.other.example", "TXT"): LookupFailure(TIMEOUT),
    }
    found = control(table, "PC-EML-03", (DOMAIN, "other.example"))
    assert (found.status, found.reason) == ("unknown", "lookup_failed")


# --- NB-6: the network guard -------------------------------------------------------


def test_a_udp_packet_to_a_public_address_is_blocked_and_recorded(
    forbid_real_network: list[str],
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        with pytest.raises(RuntimeError, match="blocked in tests: 192.0.2.7"):
            sock.sendto(b"x", ("192.0.2.7", 53))
    assert forbid_real_network == ["192.0.2.7"]


def test_a_udp_packet_to_loopback_is_not_blocked(
    forbid_real_network: list[str],
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(b"x", ("127.0.0.1", 9))
    assert forbid_real_network == []
