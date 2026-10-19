"""The email rules, PC-EML-01 to PC-EML-06 (PC-EML-07 is a manual artefact).

SPF, DKIM selectors and DMARC come from our own public DNS check (phase 7). Its
facts are read here in the shape the check will store: one `domain` row per mail
domain of the client in the source `dns-check` with these columns:

    domain           the pseudonymous mail domain (the same pseudonym as the
                     `domain` of the Exchange DKIM rows)
    lookup_failed    true when the lookup timed out or the resolver failed
    spf_records      how many v=spf1 records the apex has (0: none)
    spf_ending       fail, softfail, neutral or pass: the ending of the record
    spf_provider     whether the record includes the mail provider
    dkim_selectors   whether the DKIM selector records exist
    dmarc_records    how many DMARC records _dmarc has (0: none)
    dmarc_policy     none, quarantine or reject
    dmarc_pct        the pct tag (100 when the tag is left out)
    dmarc_rua        whether a rua address is given

A domain whose lookup failed is unknown and never a fail: a resolver failure cannot
flip a pass to a fail. Until phase 7 imports these facts, the three DNS controls
are unknown with the reason licence_or_scope, never pass and never fail.
"""

from collections.abc import Sequence
from datetime import datetime
from fractions import Fraction

from app.checks.library import Control
from app.checks.model import LOOKUP_FAILED, UNRESOLVED, Outcome, Row, Status
from app.checks.support import (
    Context,
    absent,
    count_of,
    count_outcome,
    decided,
    flag_of,
    no_source,
    text_of,
    unknown,
    worst_of,
)

DNS = "dns-check"
EXCHANGE = "exchange-export"
FILTER_POLICIES = ("anti-phish", "safe-links", "safe-attachments", "preset")


def _spf_state(row: Row) -> Status | None:
    if row.get("lookup_failed") is True:
        return None
    records = count_of(row.get("spf_records"))
    if records is None:
        return None
    if records != 1:
        return "fail"
    ending = text_of(row.get("spf_ending"))
    if ending == "neutral":
        return "partial"
    if ending in ("fail", "softfail"):
        provider = flag_of(row.get("spf_provider"))
        return None if provider is None else ("pass" if provider else "fail")
    return "fail" if ending == "pass" else None


def _dmarc_state(row: Row) -> Status | None:
    if row.get("lookup_failed") is True:
        return None
    records = count_of(row.get("dmarc_records"))
    if records is None:
        return None
    if records != 1:
        return "fail"
    policy = text_of(row.get("dmarc_policy"))
    percent = count_of(row.get("dmarc_pct"))
    reporting = flag_of(row.get("dmarc_rua"))
    if policy is None or percent is None or reporting is None:
        return None
    if policy in ("quarantine", "reject"):
        return "pass" if percent == 100 and reporting else "partial"
    return "partial" if reporting else "fail"


def _dmarc_reason(rows: Sequence[Row]) -> str:
    """Why a DMARC state is unknown: a failed lookup, or a record it cannot read.

    A malformed record (no valid `p=`, a `pct` that is not 0 to 100) is not a failed
    lookup: the DNS answered, with a value the check does not understand, so the
    reason says the values are unresolved.
    """
    failed = any(row.get("lookup_failed") is True for row in rows)
    return LOOKUP_FAILED if failed else UNRESOLVED


def _half_rule(
    control: Control,
    states: Sequence[Status | None],
    at: datetime | None,
    what: str,
) -> Outcome:
    """Pass if all domains pass; partial if at least the stated share pass."""
    total = len(states)
    share = Fraction(control.number("partial_share"))

    def result(passing: int) -> Status:
        if passing == total:
            return "pass"
        return "partial" if Fraction(passing, total) >= share else "fail"

    passing = sum(1 for state in states if state == "pass")
    unresolved = sum(1 for state in states if state is None)
    detail = f"{passing} of {total} {what}"
    if unresolved:
        detail += f"; {unresolved} could not be looked up"
    if unresolved and result(passing + unresolved) == "fail":
        return decided("fail", detail, at, passing, total)
    if unresolved:
        return unknown(LOOKUP_FAILED, detail, at)
    return decided(result(passing), detail, at, passing, total)


def eml_01(ctx: Context) -> Outcome:
    """SPF: one record ending in a fail, with the provider included."""
    dns = ctx.source(DNS)
    if dns is None:
        return no_source(DNS)
    rows = dns.rows("domain")
    if not rows:
        return absent("The DNS check has no mail domain for this client.")
    states = [_spf_state(row) for row in rows]
    return _half_rule(ctx.control, states, dns.captured_at, "mail domains pass SPF")


def eml_02(ctx: Context) -> Outcome:
    """DKIM: signing enabled in Exchange and the selector records published."""
    exchange, dns = ctx.source(EXCHANGE), ctx.source(DNS)
    if exchange is None:
        return no_source(EXCHANGE)
    if dns is None:
        return no_source(DNS)
    rows = exchange.rows("dkim")
    if not rows:
        return absent("The Exchange export has no DKIM signing records.")
    selectors: dict[str, bool | None] = {}
    for dns_row in dns.rows("domain"):
        domain = text_of(dns_row.get("domain"))
        if domain is not None:
            found = flag_of(dns_row.get("dkim_selectors"))
            failed = dns_row.get("lookup_failed") is True
            selectors[domain] = None if failed else found

    def state(row: Row) -> Status | None:
        enabled = flag_of(row.get("enabled"))
        present = selectors.get(text_of(row.get("domain")) or "")
        if enabled is False or present is False:
            return "fail"
        return "pass" if enabled is True and present is True else None

    states = [state(row) for row in rows]
    at = min(exchange.captured_at, dns.captured_at)
    return _half_rule(ctx.control, states, at, "mail domains sign with DKIM")


def eml_03(ctx: Context) -> Outcome:
    """DMARC: published, enforcing, at 100 percent, with a report address."""
    dns = ctx.source(DNS)
    if dns is None:
        return no_source(DNS)
    rows = dns.rows("domain")
    if not rows:
        return absent("The DNS check has no mail domain for this client.")
    states = [_dmarc_state(row) for row in rows]
    what = "mail domains enforce DMARC"
    return worst_of(states, dns.captured_at, what, _dmarc_reason(rows))


def eml_04(ctx: Context) -> Outcome:
    """Inbound filtering: anti-phishing with safe links and attachments, or a preset."""
    exchange = ctx.source(EXCHANGE)
    if exchange is None:
        return no_source(EXCHANGE)
    at = exchange.captured_at
    rows = [
        row
        for row in exchange.rows("policy")
        if row.get("policy_type") in FILTER_POLICIES
        and flag_of(row.get("enabled")) is not None
    ]
    if not rows:
        return absent("The Exchange export has no filtering policy with a state.")
    on = {row.get("policy_type") for row in rows if row.get("enabled") is True}
    if "preset" in on or {"anti-phish", "safe-links", "safe-attachments"} <= on:
        return decided("pass", "Inbound mail filtering is fully enabled.", at)
    if "anti-phish" in on:
        return decided("partial", "Only the anti-phishing policy is enabled.", at)
    return decided("fail", "No inbound filtering policy is enabled.", at)


def eml_05(ctx: Context) -> Outcome:
    """Automatic forwarding off, and few mailboxes that forward outside."""
    exchange = ctx.source(EXCHANGE)
    if exchange is None:
        return no_source(EXCHANGE)
    at = exchange.captured_at
    modes = [
        text_of(row.get("auto_forwarding_mode"))
        for row in exchange.rows("policy")
        if row.get("policy_type") == "outbound-spam"
    ]
    known_modes = [mode for mode in modes if mode is not None]
    mailboxes = exchange.rows("mailbox")
    flags = [flag_of(row.get("forwarding_external")) for row in mailboxes]
    if not known_modes or all(flag is None for flag in flags):
        return absent("The Exchange export lacks the outbound policy or the mailboxes.")
    if any(mode != "off" for mode in known_modes):
        return decided("fail", "Automatic forwarding to outside is allowed.", at)
    forwarding = sum(1 for flag in flags if flag)
    unresolved = sum(1 for flag in flags if flag is None)
    allowed = ctx.control.whole("partial_mailboxes")

    def status(count: int) -> Status:
        if count == 0:
            return "pass"
        return "partial" if count <= allowed else "fail"

    detail = f"{forwarding} mailboxes forward outside"
    if status(forwarding) != status(forwarding + unresolved):
        return unknown(UNRESOLVED, detail, at)
    return decided(status(forwarding), detail, at, forwarding, len(flags))


def eml_06(ctx: Context) -> Outcome:
    """Shared mailboxes that can be signed into: none is wanted."""
    exchange = ctx.source(EXCHANGE)
    if exchange is None:
        return no_source(EXCHANGE)
    rows = exchange.rows("mailbox")
    if not rows or all(text_of(row.get("recipient_type")) is None for row in rows):
        return absent("The Exchange export does not say which mailboxes are shared.")
    shared = [row for row in rows if row.get("recipient_type") == "shared"]
    enabled = sum(1 for row in shared if row.get("account_enabled") is True)
    unresolved = sum(1 for row in shared if flag_of(row.get("account_enabled")) is None)
    what = "shared mailboxes can be signed into"
    return count_outcome(
        ctx.control, enabled, unresolved, exchange.captured_at, what, len(shared)
    )
