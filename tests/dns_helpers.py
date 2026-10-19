"""A fake resolver and zone builders for the DNS check tests (phase 7).

No test of the DNS check may reach the network: the check is given a StaticResolver,
which answers from a table and records every question it was asked.
"""

from collections.abc import Mapping, Sequence

from app.checks.dnscheck import LookupFailure

Answer = Sequence[str] | LookupFailure
Zone = dict[tuple[str, str], Answer]


class StaticResolver:
    """Answers from a table of (name, type) to records; a missing name has none."""

    def __init__(self, answers: Mapping[tuple[str, str], Answer] | None = None) -> None:
        self.answers: Zone = dict(answers or {})
        self.queries: list[tuple[str, str]] = []

    def lookup(self, name: str, rdtype: str) -> tuple[str, ...]:
        key = (name.lower(), rdtype.upper())
        self.queries.append(key)
        answer = self.answers.get(key, ())
        if isinstance(answer, LookupFailure):
            raise answer
        return tuple(answer)

    def names(self) -> set[str]:
        return {name for name, _ in self.queries}


def zone(
    domain: str,
    *,
    spf: Sequence[str] = (),
    dmarc: Sequence[str] = (),
    cnames: Sequence[str] = (),
    keys: Mapping[str, str] | None = None,
) -> Zone:
    """The records of one mail domain.

    `cnames` are DKIM selectors published as a CNAME; `keys` maps a selector to the
    text of a TXT record at its `_domainkey` name.
    """
    table: Zone = {}
    if spf:
        table[(domain, "TXT")] = list(spf)
    if dmarc:
        table[(f"_dmarc.{domain}", "TXT")] = list(dmarc)
    for selector in cnames:
        table[(f"{selector}._domainkey.{domain}", "CNAME")] = ["target.example.net"]
    for selector, text in (keys or {}).items():
        table[(f"{selector}._domainkey.{domain}", "TXT")] = [text]
    return table


def resolver_for(*tables: Zone) -> StaticResolver:
    merged: Zone = {}
    for table in tables:
        merged.update(table)
    return StaticResolver(merged)
