"""The public DNS check of phase 7: the parsing and the lookups, with a fake resolver.

Nothing here reaches the network (the conftest guard fails any test that tries): the
check is given a StaticResolver. What the control rules make of these results is in
tests/test_dnscheck_controls.py.
"""

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.checks import dnscheck
from app.checks.dnscheck import (
    MAX_ANSWERS,
    MAX_TEXT_LENGTH,
    QUERY_LIMIT,
    RESOLVER_ERROR,
    SERVFAIL,
    SPF_LOOKUP_LIMIT,
    TIMEOUT,
    DomainResult,
    LookupFailure,
    Queries,
    SpfResult,
    evaluate_spf,
    run_checks,
)
from dns_helpers import StaticResolver, Zone, resolver_for, zone

DOMAIN = "client.example"
AT = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
PROVIDER = "spf.protection.outlook.com"
GOOD_DMARC = "v=DMARC1; p=reject; rua=mailto:dmarc@client.example"
GOOD_SPF = f"v=spf1 include:{PROVIDER} -all"
KEY = "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC"


def run(*tables: Zone, **options: object) -> DomainResult:
    check = run_checks(
        resolver_for(*tables),
        [DOMAIN],
        captured_at=AT,
        **options,  # type: ignore[arg-type]
    )
    [result] = check.domains
    return result


def spf_of(*tables: Zone) -> SpfResult:
    result = run(*tables)
    assert result.spf is not None, result
    return result.spf


def spf_zone(record: str, **more: Zone) -> Zone:
    table = zone(DOMAIN, spf=[record])
    for extra in more.values():
        table.update(extra)
    return table


def includes(count: int, start: int = 0) -> str:
    return " ".join(f"include:s{n}.example.net" for n in range(start, start + count))


# --- SPF: every shape of a record ----------------------------------------------------

SPF_SHAPES = [
    (f"v=spf1 include:{PROVIDER} -all", "fail", True, 1, False),
    (f"v=spf1 include:{PROVIDER} ~all", "softfail", True, 1, False),
    (f"v=spf1 include:{PROVIDER} ?all", "neutral", True, 1, False),
    (f"v=spf1 include:{PROVIDER} +all", "pass", True, 1, False),
    (f"v=spf1 include:{PROVIDER} all", "pass", True, 1, False),
    (f"v=spf1 include:{PROVIDER}", "neutral", True, 1, False),
    (f"v=spf1 include:sub.{PROVIDER} -all", "fail", True, 1, False),
    (f"V=SPF1 INCLUDE:{PROVIDER.upper()} -ALL", "fail", True, 1, False),
    ("v=spf1 ip4:192.0.2.0/24 ip6:2001:db8::/32 -all", "fail", False, 0, False),
    ("v=spf1 include:mail.other.example -all", "fail", False, 1, False),
    ("v=spf1 a mx ptr exists:probe.example.net -all", "fail", False, 4, False),
    ("v=spf1 a:host.example.net/24 mx:mx.example.net -all", "fail", False, 2, False),
    (f"v=spf1 -all include:{PROVIDER}", "fail", False, 0, False),
    ("v=spf1", "neutral", False, 0, False),
]


@pytest.mark.parametrize(
    ("record", "ending", "provider", "lookups", "over"),
    SPF_SHAPES,
    ids=[shape[0] for shape in SPF_SHAPES],
)
def test_every_spf_record_shape_is_read(
    record: str, ending: str, provider: bool, lookups: int, over: bool
) -> None:
    assert spf_of(spf_zone(record)) == SpfResult(
        records=1, ending=ending, provider=provider, lookups=lookups, over_limit=over
    )


def test_a_missing_spf_record_is_a_fact_not_a_failure() -> None:
    result = run(zone(DOMAIN))
    assert result.failure is None
    assert result.spf == SpfResult(records=0)


def test_two_spf_records_are_counted_and_nothing_else_is_read() -> None:
    table = zone(DOMAIN, spf=["v=spf1 -all", "v=spf1 ~all"])
    assert spf_of(table) == SpfResult(records=2)


def test_other_text_records_at_the_apex_are_not_spf_records() -> None:
    others = ["google-site-verification=abc", "v=spf10 -all"]
    table = zone(DOMAIN, spf=[*others, GOOD_SPF])
    assert spf_of(table).records == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("v=spf1", True),
        ("v=spf1 -all", True),
        ("V=SPF1\t-all", True),
        ("v=spf10 -all", False),
        (" v=spf1 -all", False),
        ("spf2.0/pra -all", False),
        ("", False),
    ],
)
def test_what_is_an_spf_record(text: str, expected: bool) -> None:
    assert dnscheck.is_spf(text) is expected


# --- SPF: the ten lookup limit -------------------------------------------------------


def test_eleven_includes_exceed_the_lookup_limit_and_are_reported() -> None:
    spf = spf_of(spf_zone(f"v=spf1 {includes(11)} -all"))
    assert SPF_LOOKUP_LIMIT == 10
    assert (spf.lookups, spf.over_limit) == (11, True)
    assert spf.ending == "fail", "the ending is read from the record, not the walk"
    assert spf.provider is None, "the walk stopped, so a missing provider is unknown"


def test_the_walk_stops_at_the_eleventh_lookup() -> None:
    resolver = resolver_for(spf_zone(f"v=spf1 {includes(30)} -all"))
    check = run_checks(resolver, [DOMAIN], captured_at=AT)
    assert check.domains[0].spf == SpfResult(
        records=1, ending="fail", provider=None, lookups=11, over_limit=True
    )
    asked = [name for name, _ in resolver.queries if name.endswith(".example.net")]
    assert len(asked) == 10, "ten includes were followed, the eleventh was not"


def test_ten_includes_are_within_the_limit() -> None:
    spf = spf_of(spf_zone(f"v=spf1 {includes(10)} -all"))
    assert (spf.lookups, spf.over_limit, spf.provider) == (10, False, False)


def test_a_provider_include_is_found_even_when_the_limit_is_exceeded() -> None:
    record = f"v=spf1 include:{PROVIDER} {includes(10)} -all"
    spf = spf_of(spf_zone(record))
    assert (spf.over_limit, spf.provider) == (True, True)


def test_lookups_inside_included_records_count_toward_the_limit() -> None:
    nested = {("a.example.net", "TXT"): [f"v=spf1 {includes(10)} -all"]}
    table = spf_zone("v=spf1 include:a.example.net -all", nested=nested)
    assert spf_of(table).over_limit is True
    nested = {("a.example.net", "TXT"): [f"v=spf1 {includes(9)} -all"]}
    table = spf_zone("v=spf1 include:a.example.net -all", nested=nested)
    spf = spf_of(table)
    assert (spf.lookups, spf.over_limit) == (10, False)


def test_an_include_that_includes_itself_is_followed_once() -> None:
    nested = {("a.example.net", "TXT"): ["v=spf1 include:a.example.net -all"]}
    resolver = resolver_for(
        spf_zone("v=spf1 include:a.example.net -all", nested=nested)
    )
    check = run_checks(resolver, [DOMAIN], captured_at=AT)
    spf = check.domains[0].spf
    assert spf is not None
    assert (spf.lookups, spf.over_limit) == (2, False)
    assert resolver.queries.count(("a.example.net", "TXT")) == 1


def test_an_include_with_two_spf_records_or_none_is_not_followed_further() -> None:
    nested = {("a.example.net", "TXT"): ["v=spf1 -all", "v=spf1 ~all"]}
    record = "v=spf1 include:a.example.net include:b.example.net -all"
    spf = spf_of(spf_zone(record, n=nested))
    assert (spf.lookups, spf.over_limit, spf.provider) == (2, False, False)


def test_a_term_after_all_is_never_counted() -> None:
    spf = spf_of(spf_zone(f"v=spf1 -all {includes(20)}"))
    assert (spf.lookups, spf.over_limit) == (0, False)


# --- SPF: redirect -------------------------------------------------------------------


def test_a_record_without_all_ends_where_its_redirect_ends() -> None:
    target = {("_spf.example.net", "TXT"): ["v=spf1 ip4:192.0.2.1 ~all"]}
    table = spf_zone("v=spf1 redirect=_spf.example.net", t=target)
    spf = spf_of(table)
    assert (spf.ending, spf.lookups, spf.over_limit) == ("softfail", 1, False)


def test_a_redirect_is_followed_through_a_chain() -> None:
    chain = {
        ("a.example.net", "TXT"): ["v=spf1 redirect=b.example.net"],
        ("b.example.net", "TXT"): ["v=spf1 -all"],
    }
    spf = spf_of(spf_zone("v=spf1 redirect=a.example.net", c=chain))
    assert (spf.ending, spf.lookups) == ("fail", 2)


def test_a_redirect_to_nothing_leaves_the_ending_unknown() -> None:
    spf = spf_of(spf_zone("v=spf1 redirect=missing.example.net"))
    assert (spf.ending, spf.lookups, spf.over_limit) == (None, 1, False)


def test_a_redirect_with_a_macro_cannot_be_followed() -> None:
    spf = spf_of(spf_zone("v=spf1 redirect=%{d}.example.net"))
    assert (spf.ending, spf.lookups, spf.over_limit) == (None, 1, None)


def test_a_redirect_is_ignored_when_the_record_has_all() -> None:
    spf = spf_of(spf_zone("v=spf1 -all redirect=x.example.net"))
    assert (spf.ending, spf.lookups) == ("fail", 0)


def test_a_redirect_past_the_limit_leaves_the_ending_unknown() -> None:
    spf = spf_of(spf_zone(f"v=spf1 {includes(10)} redirect=x.example.net"))
    assert (spf.ending, spf.lookups, spf.over_limit) == (None, 11, True)


# --- SPF: a lookup that fails while following ------------------------------------


def test_a_failed_include_leaves_the_count_incomplete_not_the_domain_failed() -> None:
    failing = {("a.example.net", "TXT"): LookupFailure(TIMEOUT)}
    table = spf_zone("v=spf1 include:a.example.net -all", f=failing)
    result = run(table)
    assert result.failure is None
    assert result.spf == SpfResult(
        records=1, ending="fail", provider=None, lookups=1, over_limit=None
    )


def test_a_provider_found_before_a_failed_include_stays_found() -> None:
    failing = {("a.example.net", "TXT"): LookupFailure(SERVFAIL)}
    record = f"v=spf1 include:{PROVIDER} include:a.example.net -all"
    spf = spf_of(spf_zone(record, f=failing))
    assert (spf.provider, spf.over_limit) == (True, None)


def test_an_include_that_cannot_be_looked_up_leaves_the_count_incomplete() -> None:
    for target in ("include:localhost", "include:%{d}.example.net", "include"):
        spf = spf_of(spf_zone(f"v=spf1 {target} -all"))
        assert (spf.provider, spf.over_limit) == (None, None), target


def test_an_exhausted_budget_makes_the_count_incomplete() -> None:
    resolver = resolver_for(
        spf_zone("v=spf1 include:a.example.net include:b.example.net -all")
    )
    spf = evaluate_spf(Queries(resolver, 2), DOMAIN)
    assert (spf.lookups, spf.provider, spf.over_limit) == (2, None, None)


# --- DKIM ----------------------------------------------------------------------------


def test_a_selector_published_as_a_cname_is_found() -> None:
    result = run(zone(DOMAIN, cnames=["selector1"]))
    assert result.dkim == dnscheck.DkimResult(checked=2, found=1)
    assert result.dkim is not None and result.dkim.published


def test_a_selector_published_as_a_key_record_is_found() -> None:
    result = run(zone(DOMAIN, keys={"selector2": KEY}))
    assert result.dkim is not None and result.dkim.published


@pytest.mark.parametrize(
    "text",
    ["v=DKIM1; k=rsa; p=", "v=DKIM2; p=abc", "v=spf1 -all", "k=rsa", ""],
    ids=["revoked", "other-version", "not-dkim", "no-key", "empty"],
)
def test_a_text_record_that_is_not_a_key_is_not_a_selector(text: str) -> None:
    result = run(zone(DOMAIN, keys={"selector1": text}))
    assert result.dkim is not None
    assert (result.dkim.found, result.dkim.published) == (0, False)


def test_a_key_record_without_a_version_tag_is_a_key() -> None:
    result = run(zone(DOMAIN, keys={"selector1": "p=abc"}))
    assert result.dkim == dnscheck.DkimResult(checked=2, found=1)


def test_no_selector_record_is_a_fact_not_a_failure() -> None:
    result = run(zone(DOMAIN))
    assert result.failure is None
    assert result.dkim == dnscheck.DkimResult(checked=2, found=0)


def test_supplied_selectors_are_looked_up_with_selector1_and_selector2() -> None:
    result = run(zone(DOMAIN, cnames=["google"]), selectors=["Google", "selector1"])
    assert result.dkim == dnscheck.DkimResult(checked=3, found=1)


def test_the_selector_names_asked_are_exactly_the_ones_published() -> None:
    resolver = resolver_for(zone(DOMAIN, cnames=["selector1"]))
    run_checks(resolver, [DOMAIN], ["s9"], captured_at=AT)
    assert ("selector1._domainkey.client.example", "CNAME") in resolver.queries
    assert ("selector1._domainkey.client.example", "TXT") not in resolver.queries, (
        "a CNAME answers the question; the key record is not asked for"
    )
    assert ("s9._domainkey.client.example", "TXT") in resolver.queries


# --- DMARC: every shape of a record --------------------------------------------------

RUA = "rua=mailto:dmarc@client.example"
DMARC_SHAPES = [
    (f"v=DMARC1; p=none; {RUA}", "none", 100, True),
    ("v=DMARC1; p=none", "none", 100, False),
    (f"v=DMARC1; p=quarantine; pct=50; {RUA}", "quarantine", 50, True),
    (f"v=DMARC1; p=quarantine; {RUA}", "quarantine", 100, True),
    ("v=DMARC1; p=quarantine", "quarantine", 100, False),
    ("v=DMARC1; p=reject; rua=mailto:a@client.example,mailto:b@client.example",
     "reject", 100, True),
    ("v=DMARC1; p=reject", "reject", 100, False),
    (f"  v = dmarc1 ;P=REJECT;PCT=0;{RUA.upper()}", "reject", 0, True),
    (f"v=DMARC1; p=bogus; {RUA}", None, 100, True),
    (f"v=DMARC1; {RUA}", None, 100, True),
    ("v=DMARC1; p=reject; pct=abc", "reject", None, False),
    ("v=DMARC1; p=reject; pct=101", "reject", None, False),
    ("v=DMARC1; p=reject; pct=-5", "reject", None, False),
    ("v=DMARC1; p=reject; pct=", "reject", None, False),
    ("v=DMARC1; p=reject; rua=https://reports.example.net/r", "reject", 100, False),
    ("v=DMARC1; p=reject; rua=mailto:", "reject", 100, False),
    ("v=DMARC1; p=none; p=reject", "none", 100, False),
    ("v=DMARC1", None, 100, False),
]


@pytest.mark.parametrize(
    ("record", "policy", "pct", "rua"),
    DMARC_SHAPES,
    ids=[shape[0].strip() for shape in DMARC_SHAPES],
)
def test_every_dmarc_record_shape_is_read(
    record: str, policy: str | None, pct: int | None, rua: bool
) -> None:
    result = run(zone(DOMAIN, dmarc=[record]))
    assert result.dmarc == dnscheck.DmarcResult(
        records=1, policy=policy, pct=pct, rua=rua
    )


def test_a_missing_dmarc_record_is_a_fact_not_a_failure() -> None:
    result = run(zone(DOMAIN))
    assert result.failure is None
    assert result.dmarc == dnscheck.DmarcResult(records=0)


def test_two_dmarc_records_are_counted_and_nothing_else_is_read() -> None:
    table = zone(DOMAIN, dmarc=[GOOD_DMARC, "v=DMARC1; p=none"])
    assert run(table).dmarc == dnscheck.DmarcResult(records=2)


def test_other_text_at_the_dmarc_name_is_not_a_record() -> None:
    table = zone(DOMAIN, dmarc=["v=DMARC10; p=none", "hello", GOOD_DMARC])
    assert run(table).dmarc == dnscheck.parse_dmarc(GOOD_DMARC)


# --- a lookup that fails is never a failure of the domain ----------------------------

FAILING = [
    ("apex", (DOMAIN, "TXT")),
    ("dmarc", (f"_dmarc.{DOMAIN}", "TXT")),
    ("selector-cname", (f"selector1._domainkey.{DOMAIN}", "CNAME")),
    ("selector-key", (f"selector2._domainkey.{DOMAIN}", "TXT")),
]


@pytest.mark.parametrize("reason", [TIMEOUT, SERVFAIL, RESOLVER_ERROR])
@pytest.mark.parametrize(("where", "key"), FAILING, ids=[item[0] for item in FAILING])
def test_a_failed_lookup_is_stored_as_lookup_failed_with_its_reason(
    reason: str, where: str, key: tuple[str, str]
) -> None:
    table = zone(DOMAIN, spf=[GOOD_SPF], dmarc=[GOOD_DMARC], cnames=["selector1"])
    table[key] = LookupFailure(reason)
    result = run(table)
    assert result.failure == reason
    assert (result.spf, result.dkim, result.dmarc) == (None, None, None)
    value = result.fact_value()
    assert value["lookup_failed"] is True and value["lookup_reason"] == reason
    assert all(v is None for k, v in value.items() if k.startswith(("spf", "dmarc")))


def test_an_unknown_failure_reason_is_a_resolver_error() -> None:
    assert LookupFailure("something odd").reason == RESOLVER_ERROR
    assert LookupFailure(TIMEOUT).reason == TIMEOUT


def test_one_failed_domain_does_not_stop_the_others() -> None:
    table = {
        **zone("bad.example", spf=[GOOD_SPF]),
        ("bad.example", "TXT"): LookupFailure(TIMEOUT),
        **zone("good.example", spf=[GOOD_SPF], dmarc=[GOOD_DMARC]),
    }
    check = run_checks(
        resolver_for(table), ["bad.example", "good.example"], captured_at=AT
    )
    bad, good = check.domains
    assert bad.failure == TIMEOUT
    assert good.failure is None and good.spf is not None


def test_the_query_budget_is_shared_and_a_spent_budget_is_a_failed_lookup() -> None:
    resolver = resolver_for(zone("a.example", spf=[GOOD_SPF]))
    check = run_checks(
        resolver, ["a.example", "b.example"], captured_at=AT, max_queries=1
    )
    assert [item.failure for item in check.domains] == [QUERY_LIMIT, QUERY_LIMIT]
    assert len(resolver.queries) == 1, "a spent budget asks nothing more"


def test_answers_are_bounded_in_number_and_length() -> None:
    long_text = "x" * (MAX_TEXT_LENGTH + 100)
    many = [f"record {n}" for n in range(MAX_ANSWERS + 20)]
    resolver = StaticResolver({("a.example", "TXT"): [long_text, *many]})
    answers = Queries(resolver).ask("a.example", "TXT")
    assert len(answers) == MAX_ANSWERS
    assert len(answers[0]) == MAX_TEXT_LENGTH


# --- only the entered domain is asked about ---------------------------------------


def test_the_names_asked_are_the_domain_and_what_its_own_record_publishes() -> None:
    nested = {("_spf.mail.example.net", "TXT"): ["v=spf1 ip4:192.0.2.0/24 -all"]}
    table = zone(
        DOMAIN,
        spf=[f"v=spf1 include:_spf.mail.example.net include:{PROVIDER} -all"],
        dmarc=[GOOD_DMARC],
        cnames=["selector1", "selector2"],
    )
    table.update(nested)
    resolver = resolver_for(table)
    run_checks(resolver, [DOMAIN], ["custom"], captured_at=AT)
    assert resolver.names() == {
        DOMAIN,
        f"_dmarc.{DOMAIN}",
        f"selector1._domainkey.{DOMAIN}",
        f"selector2._domainkey.{DOMAIN}",
        f"custom._domainkey.{DOMAIN}",
        "_spf.mail.example.net",
        PROVIDER,
    }
    assert {kind for _, kind in resolver.queries} == {"TXT", "CNAME"}


# --- names, selectors, providers -----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("client.example", "client.example"),
        ("  Client.Example.  ", "client.example"),
        ("bücher.example", "xn--bcher-kva.example"),
        ("mail.sub.client.example", "mail.sub.client.example"),
        ("a-b.example", "a-b.example"),
    ],
)
def test_a_domain_is_written_in_lower_case_ascii(text: str, expected: str) -> None:
    assert dnscheck.normalise_domain(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "localhost",
        "192.0.2.1",
        "client.123",
        "a..example",
        "-a.example",
        "a-.example",
        "a_b.example",
        "user@client.example",
        "client.example/path",
        "client example",
        "a" * 64 + ".example",
        ".".join(["a" * 60] * 5) + ".example",
    ],
)
def test_a_value_that_is_not_a_domain_name_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="not a valid domain name"):
        dnscheck.normalise_domain(text)


def test_a_refusal_does_not_repeat_a_long_input_in_full() -> None:
    with pytest.raises(ValueError) as caught:
        dnscheck.normalise_domain("x" * 500)
    assert len(str(caught.value)) < 120


def test_domains_are_deduplicated_after_normalising() -> None:
    names = dnscheck.clean_domains(["A.example", "a.example.", "b.example"])
    assert names == ("a.example", "b.example")


def test_at_least_one_and_at_most_twenty_domains() -> None:
    with pytest.raises(ValueError, match="at least one"):
        dnscheck.clean_domains([])
    many = [f"d{n}.example" for n in range(21)]
    with pytest.raises(ValueError, match="at most 20"):
        dnscheck.clean_domains(many)
    assert len(dnscheck.clean_domains(many[:20])) == 20


def test_selectors_start_with_selector1_and_selector2_and_are_deduplicated() -> None:
    assert dnscheck.clean_selectors([]) == ("selector1", "selector2")
    chosen = dnscheck.clean_selectors(["Google", "selector2", "k1", "google"])
    assert chosen == ("selector1", "selector2", "google", "k1")


@pytest.mark.parametrize(
    "text", ["", "bad selector", "a..b", ".a", "a.", "a/b", "x" * 64, "a@b"]
)
def test_a_selector_that_is_not_a_name_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="not a valid DKIM selector"):
        dnscheck.clean_selectors([text])


def test_at_most_ten_selectors_can_be_supplied() -> None:
    ten = [f"s{n}" for n in range(10)]
    assert len(dnscheck.clean_selectors(ten)) == 12
    with pytest.raises(ValueError, match="at most 10 DKIM selectors"):
        dnscheck.clean_selectors([*ten, "s10"])


def test_providers_start_with_microsoft_365_and_are_checked_like_domains() -> None:
    assert dnscheck.clean_providers([]) == (PROVIDER,)
    chosen = dnscheck.clean_providers(["_spf.Google.com", PROVIDER])
    assert chosen == (PROVIDER, "_spf.google.com")
    with pytest.raises(ValueError, match="not a valid domain name"):
        dnscheck.clean_providers(["not a domain"])
    with pytest.raises(ValueError, match="at most 10 mail providers"):
        dnscheck.clean_providers([f"p{n}.example" for n in range(11)])


def test_a_supplied_provider_is_recognised_in_the_record() -> None:
    table = zone(DOMAIN, spf=["v=spf1 include:_spf.google.com -all"])
    result = run_checks(
        resolver_for(table), [DOMAIN], providers=["_spf.google.com"], captured_at=AT
    )
    assert result.domains[0].spf is not None
    assert result.domains[0].spf.provider is True


def test_a_selector_that_makes_a_name_too_long_is_refused_before_any_lookup() -> None:
    domain = ".".join(["a" * 60] * 3 + ["example"])
    resolver = StaticResolver()
    with pytest.raises(ValueError, match="is too long"):
        run_checks(resolver, [domain], ["s" * 63], captured_at=AT)
    assert resolver.queries == []


# --- the run -------------------------------------------------------------------------


def test_a_naive_capture_time_is_refused_before_any_lookup() -> None:
    resolver = StaticResolver()
    with pytest.raises(ValueError, match="captured_at must carry a timezone"):
        run_checks(resolver, [DOMAIN], captured_at=datetime(2026, 10, 18, 9, 0))
    assert resolver.queries == []


def test_nothing_is_looked_up_when_an_input_is_refused() -> None:
    resolver = StaticResolver()
    with pytest.raises(ValueError):
        run_checks(resolver, [DOMAIN, "not a domain"], captured_at=AT)
    assert resolver.queries == []


def test_the_capture_time_is_kept_in_utc() -> None:
    plus_two = timezone(timedelta(hours=2))
    stamp = datetime(2026, 10, 18, 11, 0, tzinfo=plus_two)
    check = run_checks(StaticResolver(), [DOMAIN], captured_at=stamp)
    assert check.captured_at == AT
    assert check.captured_at.utcoffset() == timedelta(0)


def test_the_stored_columns_of_a_complete_domain() -> None:
    table = zone(DOMAIN, spf=[GOOD_SPF], dmarc=[GOOD_DMARC], cnames=["selector1"])
    assert run(table).fact_value() == {
        "lookup_failed": False,
        "lookup_reason": None,
        "spf_records": 1,
        "spf_ending": "fail",
        "spf_provider": True,
        "spf_lookups": 1,
        "spf_over_limit": False,
        "dkim_selectors": True,
        "dkim_checked": 2,
        "dkim_found": 1,
        "dmarc_records": 1,
        "dmarc_policy": "reject",
        "dmarc_pct": 100,
        "dmarc_rua": True,
    }


def test_the_columns_of_a_domain_with_no_records_say_none_not_unknown() -> None:
    value = run(zone(DOMAIN)).fact_value()
    assert value["spf_records"] == 0 and value["dmarc_records"] == 0
    assert value["dkim_selectors"] is False and value["lookup_failed"] is False


def test_the_document_is_canonical_ascii_json_with_the_capture_time() -> None:
    table = zone(DOMAIN, spf=[GOOD_SPF], dmarc=[GOOD_DMARC])
    check = run_checks(resolver_for(table), [DOMAIN], captured_at=AT)
    data = dnscheck.render_document(check)
    assert data.isascii() and not data.endswith(b"\n")
    document = json.loads(data)
    assert document["capturedAt"] == "2026-10-18T09:00:00+00:00"
    [item] = document["domains"]
    assert item["domain"] == DOMAIN
    assert {key: item[key] for key in check.domains[0].fact_value()} == (
        check.domains[0].fact_value()
    )
    assert data == dnscheck.render_document(check), "the same run gives the same bytes"


def test_this_module_reads_no_clock_and_opens_no_connection() -> None:
    text = Path(dnscheck.__file__).read_text(encoding="utf-8")
    for forbidden in ("import socket", "datetime.now", "utcnow", "import dns."):
        assert forbidden not in text, forbidden
