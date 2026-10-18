"""Public DNS checks for SPF, DKIM and DMARC (phase 7; PC-EML-01 to PC-EML-03).

For every mail domain the MSP enters, the check reads the public DNS records and
reduces them to the columns that `app/checks/email.py` documents for the source
`dns-check`: the number of SPF records, how the record ends, whether the mail
provider is included, whether a DKIM selector record exists, and the DMARC policy,
percentage and report address. Nothing here stores anything: the importer
(`app/importers/dnscheck.py`) turns the result into facts and the service
(`app/dns_service.py`) stores them as evidence with their capture time.

What leaves the instance is a DNS question and nothing else, and the names asked are
fixed by this module: the entered domain, `_dmarc.<domain>`,
`<selector>._domainkey.<domain>`, and the `include:` and `redirect=` targets that the
domain's own SPF record publishes (they are needed to count the lookups the SPF
standard limits to ten). No client name, pseudonym, file or score is in a question.

A lookup that times out, fails with SERVFAIL or is refused is never a failure of the
domain: the domain is stored as `lookup_failed` with the reason, and the check engine
reads it as unknown. A record that is absent (NXDOMAIN or no answer) is a fact. A
failure while following an SPF `include:` leaves the lookup count incomplete: the
count and the provider are then unknown, never guessed.

The resolver is injected (`Resolver`), so the tests run against a fake one and no test
touches the network.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

Value = str | int | bool | None

SPF_LOOKUP_LIMIT = 10
MAX_DOMAINS = 20
MAX_SELECTORS = 10
MAX_PROVIDERS = 10
MAX_QUERIES = 400
MAX_NAME_LENGTH = 253
MAX_ANSWERS = 50
MAX_TEXT_LENGTH = 8192
DEFAULT_SELECTORS = ("selector1", "selector2")
DEFAULT_PROVIDERS = ("spf.protection.outlook.com",)

# Why a lookup gave no answer.
TIMEOUT = "timeout"
SERVFAIL = "servfail"
RESOLVER_ERROR = "resolver_error"
QUERY_LIMIT = "query_limit"
FAILURE_REASONS = frozenset({TIMEOUT, SERVFAIL, RESOLVER_ERROR, QUERY_LIMIT})

SPF_ENDINGS = frozenset({"fail", "softfail", "neutral", "pass"})
DMARC_POLICIES = frozenset({"none", "quarantine", "reject"})

QUALIFIERS = {"+": "pass", "-": "fail", "~": "softfail", "?": "neutral"}
LOOKUP_MECHANISMS = frozenset({"include", "a", "mx", "ptr", "exists"})

_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_HOST_LABEL = re.compile(r"[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?\Z")
_SELECTOR = re.compile(r"[a-z0-9_](?:[a-z0-9_.-]{0,61}[a-z0-9_])?\Z")
_SPF_START = re.compile(r"v=spf1(?:\s|\Z)", re.IGNORECASE)
_DMARC_START = re.compile(r"\s*v\s*=\s*DMARC1\s*(?:;|\Z)", re.IGNORECASE)
_MODIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*=")
_PERCENT = re.compile(r"[0-9]{1,3}\Z")


class LookupFailure(Exception):
    """A lookup gave no answer: a timeout, SERVFAIL or another resolver failure.

    `reason` is one of FAILURE_REASONS (anything else is read as resolver_error).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason if reason in FAILURE_REASONS else RESOLVER_ERROR


class Resolver(Protocol):
    """Asks the public DNS. `rdtype` is `TXT` or `CNAME`."""

    def lookup(self, name: str, rdtype: str) -> Sequence[str]:
        """The text of every record of that type at the name.

        One text per record (the strings of a TXT record joined). An empty sequence
        when the name has no such record, NXDOMAIN included. Raises LookupFailure on a
        timeout, SERVFAIL or any other failure to get an answer.
        """


class Queries:
    """The resolver behind a budget: one run asks for at most `limit` names."""

    def __init__(self, resolver: Resolver, limit: int = MAX_QUERIES) -> None:
        self._resolver = resolver
        self._left = limit

    def ask(self, name: str, rdtype: str) -> tuple[str, ...]:
        if self._left <= 0:
            raise LookupFailure(QUERY_LIMIT)
        self._left -= 1
        answers = list(self._resolver.lookup(name, rdtype))[:MAX_ANSWERS]
        return tuple(text[:MAX_TEXT_LENGTH] for text in answers)


# --- names -------------------------------------------------------------------------


def _shown(text: str) -> str:
    return text if len(text) <= 60 else text[:57] + "..."


def valid_name(name: str, *, underscores: bool = False) -> bool:
    """Whether a lower-case ASCII name has two or more valid labels.

    A mail domain has letters, digits and hyphens only. The names that an SPF record
    points to (`_spf.example.net`) and the provider names may also use underscores.
    """
    if not 0 < len(name) <= MAX_NAME_LENGTH:
        return False
    labels = name.split(".")
    if len(labels) < 2 or labels[-1].isdigit():
        return False
    pattern = _HOST_LABEL if underscores else _LABEL
    return all(pattern.match(label) for label in labels)


def _normalise(text: str, *, underscores: bool) -> str:
    candidate = text.strip().rstrip(".").lower()
    try:
        name = candidate.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError(f"{_shown(text)!r} is not a valid domain name") from None
    if not valid_name(name, underscores=underscores):
        raise ValueError(f"{_shown(text)!r} is not a valid domain name")
    return name


def normalise_domain(text: str) -> str:
    """The lower-case ASCII (punycode) form of a mail domain, or ValueError."""
    return _normalise(text, underscores=False)


def normalise_host(text: str) -> str:
    """Like `normalise_domain`, for a name that may have underscores."""
    return _normalise(text, underscores=True)


def _clean_selector(text: str) -> str:
    selector = text.strip().lower()
    labels = selector.split(".")
    if not _SELECTOR.match(selector) or not all(labels):
        raise ValueError(f"{_shown(text)!r} is not a valid DKIM selector")
    return selector


def _unique(items: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def clean_domains(domains: Sequence[str]) -> tuple[str, ...]:
    names = _unique([normalise_domain(item) for item in domains])
    if not names:
        raise ValueError("at least one mail domain is needed")
    if len(names) > MAX_DOMAINS:
        raise ValueError(f"at most {MAX_DOMAINS} mail domains can be checked at once")
    return names


def clean_selectors(selectors: Sequence[str]) -> tuple[str, ...]:
    """The selectors to look up: selector1 and selector2, then the ones supplied."""
    supplied = [_clean_selector(item) for item in selectors]
    chosen = _unique([*DEFAULT_SELECTORS, *supplied])
    if len(chosen) > MAX_SELECTORS + len(DEFAULT_SELECTORS):
        raise ValueError(f"at most {MAX_SELECTORS} DKIM selectors can be supplied")
    return chosen


def clean_providers(providers: Sequence[str]) -> tuple[str, ...]:
    """The include names that count as the mail provider (Microsoft 365 and more)."""
    supplied = [normalise_host(item) for item in providers]
    chosen = _unique([*DEFAULT_PROVIDERS, *supplied])
    if len(chosen) > MAX_PROVIDERS + len(DEFAULT_PROVIDERS):
        raise ValueError(f"at most {MAX_PROVIDERS} mail providers can be supplied")
    return chosen


# --- SPF ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpfTerm:
    """A term that makes the receiver ask the DNS: include, a, mx, ptr or exists."""

    kind: str
    target: str | None


@dataclass(frozen=True)
class ParsedSpf:
    """One SPF record read as text.

    `ending` is how the record ends (fail, softfail, neutral or pass): the `all`
    term, or neutral when there is none, as the standard says. A record with a
    `redirect=` and no `all` ends where the redirected record ends, which needs a
    lookup, so its `ending` is None until `redirect` has been followed.
    """

    ending: str | None
    terms: tuple[SpfTerm, ...]
    redirect: str | None


@dataclass(frozen=True)
class SpfResult:
    """What the SPF record of a domain says.

    records: the v=spf1 records at the apex (one is correct). The rest is None unless
    there is exactly one. lookups is the count of terms that ask the DNS, followed
    through include and redirect (at most 11: 11 means more than the limit of 10);
    over_limit is True above the limit, False when the whole record was followed and
    stays within it, and None when a lookup failed before that could be told.
    provider says whether an include names the mail provider (None when it is not
    found and the record could not be followed to the end).
    """

    records: int
    ending: str | None = None
    provider: bool | None = None
    lookups: int | None = None
    over_limit: bool | None = None


def is_spf(text: str) -> bool:
    return _SPF_START.match(text) is not None


def parse_spf_record(text: str) -> ParsedSpf:
    """Read one SPF record. Terms after `all` are never tested, so they are ignored."""
    ending: str | None = None
    redirect: str | None = None
    terms: list[SpfTerm] = []
    seen_all = False
    for token in text.split()[1:]:
        if _MODIFIER.match(token):
            name, _, value = token.partition("=")
            if name.lower() == "redirect" and value and redirect is None:
                redirect = value
            continue
        if seen_all:
            continue
        qualifier = QUALIFIERS.get(token[0])
        body = token[1:] if qualifier is not None else token
        kind = re.split(r"[:/]", body, maxsplit=1)[0].lower()
        if kind == "all":
            ending = qualifier or "pass"
            seen_all = True
        elif kind in LOOKUP_MECHANISMS:
            target = body.partition(":")[2].split("/")[0] if ":" in body else None
            terms.append(SpfTerm(kind, target or None))
    if seen_all:
        redirect = None
    elif redirect is None:
        ending = "neutral"
    return ParsedSpf(ending, tuple(terms), redirect)


def _is_provider(name: str, providers: Sequence[str]) -> bool:
    return any(name == item or name.endswith("." + item) for item in providers)


class _OverLimit(Exception):
    """More than ten terms ask the DNS: the walk stops."""


class _SpfWalk:
    """Follows the include and redirect targets of one record, counting lookups."""

    def __init__(self, queries: Queries, providers: Sequence[str]) -> None:
        self._queries = queries
        self._providers = providers
        self._seen: set[str] = set()
        self.lookups = 0
        self.complete = True
        self.provider = False

    def _count(self) -> None:
        self.lookups += 1
        if self.lookups > SPF_LOOKUP_LIMIT:
            raise _OverLimit

    def _name(self, target: str | None) -> str | None:
        """The name to look up, or None (and the walk is incomplete)."""
        if target is None or "%" in target:
            self.complete = False
            return None
        name = target.strip().rstrip(".").lower()
        if not valid_name(name, underscores=True):
            self.complete = False
            return None
        if _is_provider(name, self._providers):
            self.provider = True
        return name

    def _follow(self, name: str) -> ParsedSpf | None:
        if name in self._seen:
            return None
        self._seen.add(name)
        try:
            texts = self._queries.ask(name, "TXT")
        except LookupFailure:
            self.complete = False
            return None
        records = [text for text in texts if is_spf(text)]
        if len(records) != 1:
            return None
        return parse_spf_record(records[0])

    def expand(self, parsed: ParsedSpf) -> str | None:
        """Count every term that asks the DNS and follow includes and the redirect.

        Returns how the record ends once a redirect is followed.
        """
        for term in parsed.terms:
            name = self._name(term.target) if term.kind == "include" else None
            self._count()
            if name is not None:
                child = self._follow(name)
                if child is not None:
                    self.expand(child)
        if parsed.redirect is None:
            return parsed.ending
        name = self._name(parsed.redirect)
        self._count()
        if name is None:
            return None
        child = self._follow(name)
        return None if child is None else self.expand(child)


def evaluate_spf(
    queries: Queries, domain: str, providers: Sequence[str] = DEFAULT_PROVIDERS
) -> SpfResult:
    """The SPF result of one domain. A failed apex lookup raises LookupFailure."""
    records = [text for text in queries.ask(domain, "TXT") if is_spf(text)]
    if len(records) != 1:
        return SpfResult(records=len(records))
    parsed = parse_spf_record(records[0])
    walk = _SpfWalk(queries, providers)
    ending = parsed.ending
    try:
        ending = walk.expand(parsed)
    except _OverLimit:
        pass
    over = walk.lookups > SPF_LOOKUP_LIMIT
    complete = walk.complete and not over
    provider: bool | None = True if walk.provider else (False if complete else None)
    return SpfResult(
        records=1,
        ending=ending,
        provider=provider,
        lookups=min(walk.lookups, SPF_LOOKUP_LIMIT + 1),
        over_limit=True if over else (False if complete else None),
    )


# --- DKIM --------------------------------------------------------------------------


@dataclass(frozen=True)
class DkimResult:
    """The DKIM selector records of a domain.

    `found` of the `checked` selectors have a record (a CNAME, or a TXT with a key).
    `published` is True when at least one has: selector1 and selector2 are always
    looked up (Microsoft 365 publishes both) with the selectors the MSP supplied, and
    one record is enough for a domain that signs with a single selector.
    """

    checked: int
    found: int

    @property
    def published(self) -> bool:
        return self.found > 0


def parse_tags(text: str) -> dict[str, str]:
    """The `name=value` tags of a DKIM or DMARC record; the first of a name wins."""
    tags: dict[str, str] = {}
    for part in text.split(";"):
        name, separator, value = part.partition("=")
        key = name.strip().lower()
        if separator and key and key not in tags:
            tags[key] = value.strip()
    return tags


def is_dkim_key(text: str) -> bool:
    """Whether a TXT text is a DKIM key record (an empty `p=` is a revoked key)."""
    tags = parse_tags(text)
    version = tags.get("v")
    if version is not None and version.upper() != "DKIM1":
        return False
    return bool(tags.get("p"))


def selector_exists(queries: Queries, selector: str, domain: str) -> bool:
    name = f"{selector}._domainkey.{domain}"
    if queries.ask(name, "CNAME"):
        return True
    return any(is_dkim_key(text) for text in queries.ask(name, "TXT"))


def evaluate_dkim(
    queries: Queries, domain: str, selectors: Sequence[str] = DEFAULT_SELECTORS
) -> DkimResult:
    found = sum(1 for item in selectors if selector_exists(queries, item, domain))
    return DkimResult(checked=len(selectors), found=found)


# --- DMARC -------------------------------------------------------------------------


@dataclass(frozen=True)
class DmarcResult:
    """The DMARC record of a domain.

    records: the DMARC records at `_dmarc.<domain>` (one is correct); the rest is None
    unless there is exactly one. policy is none, quarantine or reject (None when the
    tag is missing or not one of them); pct is the percentage (100 when the tag is
    left out, None when it is not a number from 0 to 100); rua says whether a
    `mailto:` report address is given.
    """

    records: int
    policy: str | None = None
    pct: int | None = None
    rua: bool | None = None


def is_dmarc(text: str) -> bool:
    return _DMARC_START.match(text) is not None


def _has_report_address(text: str) -> bool:
    for item in text.split(","):
        address = item.strip().lower()
        if address.startswith("mailto:") and len(address) > len("mailto:"):
            return True
    return False


def parse_dmarc(text: str) -> DmarcResult:
    """Read one DMARC record."""
    tags = parse_tags(text)
    policy = tags.get("p", "").lower()
    percent = 100
    if "pct" in tags:
        value = tags["pct"]
        percent = int(value) if _PERCENT.match(value) else -1
    return DmarcResult(
        records=1,
        policy=policy if policy in DMARC_POLICIES else None,
        pct=percent if 0 <= percent <= 100 else None,
        rua=_has_report_address(tags.get("rua", "")),
    )


def evaluate_dmarc(queries: Queries, domain: str) -> DmarcResult:
    records = [
        text for text in queries.ask(f"_dmarc.{domain}", "TXT") if is_dmarc(text)
    ]
    if len(records) != 1:
        return DmarcResult(records=len(records))
    return parse_dmarc(records[0])


# --- one domain, one run -----------------------------------------------------------


@dataclass(frozen=True)
class DomainResult:
    """Everything the check found for one mail domain.

    `failure` is the reason when a lookup gave no answer; the domain is then
    `lookup_failed` and the three results are None: the check engine reads it as
    unknown, so a resolver failure can never turn a pass into a fail.
    """

    domain: str
    failure: str | None = None
    spf: SpfResult | None = None
    dkim: DkimResult | None = None
    dmarc: DmarcResult | None = None

    def fact_value(self) -> dict[str, Value]:
        """The stored columns of the domain (see app/checks/email.py).

        The domain itself is not here: the evidence store replaces it with the
        client's pseudonym.
        """
        spf, dkim, dmarc = self.spf, self.dkim, self.dmarc
        return {
            "lookup_failed": self.failure is not None,
            "lookup_reason": self.failure,
            "spf_records": spf.records if spf else None,
            "spf_ending": spf.ending if spf else None,
            "spf_provider": spf.provider if spf else None,
            "spf_lookups": spf.lookups if spf else None,
            "spf_over_limit": spf.over_limit if spf else None,
            "dkim_selectors": dkim.published if dkim else None,
            "dkim_checked": dkim.checked if dkim else None,
            "dkim_found": dkim.found if dkim else None,
            "dmarc_records": dmarc.records if dmarc else None,
            "dmarc_policy": dmarc.policy if dmarc else None,
            "dmarc_pct": dmarc.pct if dmarc else None,
            "dmarc_rua": dmarc.rua if dmarc else None,
        }


def check_domain(
    queries: Queries,
    domain: str,
    selectors: Sequence[str] = DEFAULT_SELECTORS,
    providers: Sequence[str] = DEFAULT_PROVIDERS,
) -> DomainResult:
    """Look up SPF, DKIM and DMARC of one (already normalised) domain."""
    try:
        spf = evaluate_spf(queries, domain, providers)
        dkim = evaluate_dkim(queries, domain, selectors)
        dmarc = evaluate_dmarc(queries, domain)
    except LookupFailure as failure:
        return DomainResult(domain=domain, failure=failure.reason)
    return DomainResult(domain=domain, spf=spf, dkim=dkim, dmarc=dmarc)


@dataclass(frozen=True)
class DnsCheck:
    """One run: the time it was captured and the result of each domain."""

    captured_at: datetime
    domains: tuple[DomainResult, ...]


def require_aware(value: datetime, name: str) -> datetime:
    """The datetime itself, or a ValueError when it carries no timezone."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must carry a timezone (use UTC), not be naive")
    return value


def run_checks(
    resolver: Resolver,
    domains: Sequence[str],
    selectors: Sequence[str] = (),
    providers: Sequence[str] = (),
    *,
    captured_at: datetime,
    max_queries: int = MAX_QUERIES,
) -> DnsCheck:
    """Check the mail domains of one client.

    Raises ValueError for a naive `captured_at`, a domain, selector or provider that
    is not valid, or too many of them: nothing is looked up then. The capture time is
    the time the run started. Lookups share one budget of `max_queries` questions; a
    domain reached after it is spent is stored as lookup_failed (query_limit).
    """
    stamp = require_aware(captured_at, "captured_at")
    names = clean_domains(domains)
    chosen = clean_selectors(selectors)
    named = clean_providers(providers)
    for name in names:
        for selector in chosen:
            if len(f"{selector}._domainkey.{name}") > MAX_NAME_LENGTH:
                raise ValueError(f"the selector {_shown(selector)!r} is too long")
    queries = Queries(resolver, max_queries)
    results = tuple(check_domain(queries, name, chosen, named) for name in names)
    return DnsCheck(captured_at=stamp.astimezone(UTC), domains=results)


def render_document(check: DnsCheck) -> bytes:
    """The result as the JSON document the `dns-check` importer reads.

    The domains are in it by name: the evidence store pseudonymises them before
    anything is kept, and a raw file is kept only when RAW_RETENTION_DAYS says so.
    """
    document = {
        "capturedAt": check.captured_at.isoformat(),
        "domains": [
            {"domain": item.domain, **item.fact_value()} for item in check.domains
        ],
    }
    text = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return text.encode("ascii")
