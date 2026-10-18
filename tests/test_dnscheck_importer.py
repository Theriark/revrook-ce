"""The adapter that turns one DNS check run into facts (phase 7)."""

import copy
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from app.checks.dnscheck import LookupFailure, render_document, run_checks
from app.importers.base import ImportRejectedError
from app.importers.dnscheck import PREFIX, DnsCheckImporter
from dns_helpers import resolver_for, zone

AT = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
IMPORTER = DnsCheckImporter()
GOOD = zone(
    "client.example",
    spf=["v=spf1 include:spf.protection.outlook.com -all"],
    dmarc=["v=DMARC1; p=reject; rua=mailto:dmarc@client.example"],
    cnames=["selector1"],
)
BAD = {**zone("down.example"), ("down.example", "TXT"): LookupFailure("timeout")}


def document() -> dict[str, Any]:
    check = run_checks(
        resolver_for(GOOD, BAD), ["client.example", "down.example"], captured_at=AT
    )
    loaded: dict[str, Any] = json.loads(render_document(check))
    return loaded


def parse(data: dict[str, Any] | bytes) -> Any:
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    return IMPORTER.parse(raw, 200_000)


def test_the_source_code_and_version_name_the_adapter() -> None:
    assert (IMPORTER.source_code, IMPORTER.version) == ("dns-check", "dns-check-1")
    assert PREFIX == "dns"


def test_a_run_becomes_one_fact_per_domain_and_a_summary() -> None:
    result = parse(document())
    assert result.captured_at == AT
    keys = [fact.key for fact in result.facts]
    assert keys == ["dns.domain", "dns.domain", "dns.summary"]
    first, second, summary = result.facts
    assert first.identifiers == {"domain": "client.example"}
    assert "domain" not in first.value, "the domain is an identifier, not a value"
    assert first.value["spf_ending"] == "fail"
    assert first.value["dmarc_policy"] == "reject"
    assert second.identifiers == {"domain": "down.example"}
    assert second.value["lookup_failed"] is True
    assert second.value["lookup_reason"] == "timeout"
    assert second.value["spf_records"] is None
    assert summary.value == {
        "domains": 2,
        "lookups_failed": 1,
        "rows_rejected": 0,
        "capture_time_source": "file",
        "timezone_assumed_utc": False,
    }


def test_the_facts_hold_exactly_the_columns_the_email_rules_read() -> None:
    [first, *_] = parse(document()).facts
    assert set(first.value) == {
        "lookup_failed",
        "lookup_reason",
        "spf_records",
        "spf_ending",
        "spf_provider",
        "spf_lookups",
        "spf_over_limit",
        "dkim_selectors",
        "dkim_checked",
        "dkim_found",
        "dmarc_records",
        "dmarc_policy",
        "dmarc_pct",
        "dmarc_rua",
    }


def test_a_capture_time_without_a_zone_is_read_as_utc_and_flagged() -> None:
    data = document()
    data["capturedAt"] = "2026-10-18T09:00:00"
    result = parse(data)
    assert result.captured_at == AT
    assert result.facts[-1].value["timezone_assumed_utc"] is True


def mutate(change: Any) -> dict[str, Any]:
    data = copy.deepcopy(document())
    change(data)
    return data


BROKEN = [
    ("not-json", b"{nope", "not valid JSON"),
    ("a-list", b"[]", "no capturedAt"),
    ("no-time", mutate(lambda d: d.pop("capturedAt")), "no capturedAt"),
    ("bad-time", mutate(lambda d: d.update(capturedAt="soon")), "capturedAt"),
    ("no-domains", mutate(lambda d: d.pop("domains")), "1 to 20 domains"),
    ("empty", mutate(lambda d: d.update(domains=[])), "1 to 20 domains"),
    ("not-a-list", mutate(lambda d: d.update(domains={})), "1 to 20 domains"),
    (
        "too-many",
        mutate(lambda d: d.update(domains=d["domains"][:1] * 21)),
        "1 to 20 domains",
    ),
    ("listed-twice", mutate(lambda d: d["domains"].append(d["domains"][0])), "twice"),
    ("not-an-object", mutate(lambda d: d["domains"].append(5)), "Domain 3 is not an"),
    ("no-name", mutate(lambda d: d["domains"][0].pop("domain")), "Domain 1 is not a"),
    (
        "number-as-name",
        mutate(lambda d: d["domains"][0].update(domain=7)),
        "Domain 1 is not a valid",
    ),
    (
        "bad-name",
        mutate(lambda d: d["domains"][0].update(domain="not a domain")),
        "Domain 1 is not a valid",
    ),
    ("missing-field", mutate(lambda d: d["domains"][0].pop("spf_ending")), "lacks"),
    (
        "failed-is-null",
        mutate(lambda d: d["domains"][0].update(lookup_failed=None)),
        "invalid lookup_failed",
    ),
    (
        "flag-as-text",
        mutate(lambda d: d["domains"][0].update(spf_provider="yes")),
        "invalid spf_provider",
    ),
    (
        "count-as-flag",
        mutate(lambda d: d["domains"][0].update(spf_records=True)),
        "invalid spf_records",
    ),
    (
        "negative-count",
        mutate(lambda d: d["domains"][0].update(dmarc_pct=-1)),
        "invalid dmarc_pct",
    ),
    (
        "huge-count",
        mutate(lambda d: d["domains"][0].update(spf_lookups=10**6)),
        "invalid spf_lookups",
    ),
    (
        "unknown-word",
        mutate(lambda d: d["domains"][0].update(spf_ending="maybe")),
        "invalid spf_ending",
    ),
    (
        "unknown-reason",
        mutate(lambda d: d["domains"][1].update(lookup_reason="boom")),
        "invalid lookup_reason",
    ),
    (
        "email-as-word",
        mutate(lambda d: d["domains"][0].update(dmarc_policy="a@b.example")),
        "invalid dmarc_policy",
    ),
]


@pytest.mark.parametrize(
    ("data", "message"),
    [(item[1], item[2]) for item in BROKEN],
    ids=[item[0] for item in BROKEN],
)
def test_a_document_that_is_not_a_dns_check_result_is_refused(
    data: dict[str, Any] | bytes, message: str
) -> None:
    with pytest.raises(ImportRejectedError, match=message):
        parse(data)


def test_a_refusal_never_repeats_what_the_file_said() -> None:
    data = mutate(lambda d: d["domains"][0].update(domain="secret client name"))
    with pytest.raises(ImportRejectedError) as caught:
        parse(data)
    assert "secret" not in str(caught.value)
