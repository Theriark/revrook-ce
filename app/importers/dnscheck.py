"""The source adapter of our own public DNS check (phase 7).

The check (`app/checks/dnscheck.py`) writes its result as a small JSON document and
this adapter turns that document into facts, the same way the adapters of the other
sources do, so that the evidence store pseudonymises the mail domains, writes the
hash chain and keeps the capture time. It is not in the default registry: nobody can
upload a `dns-check` file by hand. `app/dns_service.py` registers it for its own
runs only.

Document: `{"capturedAt": "<ISO time with a zone>", "domains": [{...}]}`, at most
20 domains, each with its `domain` and every column of `DomainResult.fact_value`.
A fact `dns.domain` is one domain: the columns that `app/checks/email.py` reads, with
the domain as an identifier (it becomes the client's pseudonym). The summary
`dns.summary` has the number of domains and how many lookups failed.
"""

from collections.abc import Mapping
from typing import cast

from app.checks.dnscheck import (
    DMARC_POLICIES,
    FAILURE_REASONS,
    MAX_DOMAINS,
    SPF_ENDINGS,
    normalise_domain,
)
from app.importers.base import FactValue, ImportRejectedError, ParsedFact, ParseResult
from app.importers.framework import (
    Flags,
    Rejects,
    json_capture_time,
    load_json,
    summary_fact,
)

PREFIX = "dns"
MAX_COUNT = 1_000

# The columns of a domain: name, kind (flag, count or word) and the words allowed.
FIELDS: tuple[tuple[str, str, frozenset[str] | None], ...] = (
    ("lookup_failed", "flag", None),
    ("lookup_reason", "word", FAILURE_REASONS),
    ("spf_records", "count", None),
    ("spf_ending", "word", SPF_ENDINGS),
    ("spf_provider", "flag", None),
    ("spf_lookups", "count", None),
    ("spf_over_limit", "flag", None),
    ("dkim_selectors", "flag", None),
    ("dkim_checked", "count", None),
    ("dkim_found", "count", None),
    ("dmarc_records", "count", None),
    ("dmarc_policy", "word", DMARC_POLICIES),
    ("dmarc_pct", "count", None),
    ("dmarc_rua", "flag", None),
)


def _valid(value: object, kind: str, words: frozenset[str] | None) -> bool:
    if kind == "flag":
        return isinstance(value, bool)
    if kind == "count":
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= MAX_COUNT
        )
    return isinstance(value, str) and value in (words or ())


def _column(
    item: Mapping[str, object], key: str, kind: str, words: frozenset[str] | None
) -> FactValue:
    """One column of a domain: its value, or None. Anything odd rejects the file."""
    if key not in item:
        raise ImportRejectedError(f"The DNS check result lacks the field {key}.")
    value = item[key]
    if value is None and key != "lookup_failed":
        return None
    if not _valid(value, kind, words):
        raise ImportRejectedError(f"The DNS check result has an invalid {key}.")
    return cast(FactValue, value)


def _domain(item: object, number: int) -> ParsedFact:
    invalid = ImportRejectedError(f"Domain {number} is not a valid name.")
    if not isinstance(item, dict):
        raise ImportRejectedError(f"Domain {number} is not an object.")
    text = item.get("domain")
    if not isinstance(text, str):
        raise invalid
    try:
        name = normalise_domain(text)
    except ValueError:
        raise invalid from None
    value = {key: _column(item, key, kind, words) for key, kind, words in FIELDS}
    return ParsedFact(f"{PREFIX}.domain", value, {"domain": name})


class DnsCheckImporter:
    """Reads the document of one DNS check run. `parse` is pure."""

    source_code = "dns-check"
    version = "dns-check-1"

    def parse(self, data: bytes, max_rows: int) -> ParseResult:
        root = load_json(data, max_rows)
        moment, assumed = json_capture_time(root)
        if moment is None or not isinstance(root, dict):
            raise ImportRejectedError("The DNS check result has no capturedAt.")
        items = root.get("domains")
        if not isinstance(items, list) or not 0 < len(items) <= MAX_DOMAINS:
            raise ImportRejectedError(
                f"The DNS check result must list 1 to {MAX_DOMAINS} domains."
            )
        facts: list[ParsedFact] = []
        seen: set[str] = set()
        for number, item in enumerate(items, start=1):
            fact = _domain(item, number)
            name = fact.identifiers["domain"]
            if name in seen:
                raise ImportRejectedError(f"Domain {number} is listed twice.")
            seen.add(name)
            facts.append(fact)
        failed = sum(1 for fact in facts if fact.value["lookup_failed"] is True)
        counts: dict[str, FactValue] = {"domains": len(facts), "lookups_failed": failed}
        summary = summary_fact(
            PREFIX,
            counts,
            Rejects(PREFIX),
            Flags(assumed_utc=assumed),
            capture_in_file=True,
        )
        return ParseResult(facts=(*facts, summary), captured_at=moment)
