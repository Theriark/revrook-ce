# Public DNS check (phase 7)

The DNS check reads the public SPF, DKIM and DMARC records of the mail domains an
MSP enters for a client, and stores the result as evidence. It feeds the controls
`PC-EML-01` (SPF), `PC-EML-02` (DKIM, together with the Exchange export) and
`PC-EML-03` (DMARC).

## What leaves the instance

Only DNS questions, and only these names: the entered domain, `_dmarc.<domain>`,
`<selector>._domainkey.<domain>`, and the `include:` and `redirect=` targets that the
domain's own SPF record publishes (they are needed to count the lookups). No client
name, pseudonym, file or score is ever in a question. One run asks at most 400
questions, for at most 20 domains, 10 extra selectors and 10 extra mail providers.

## Resolvers

`DNS_RESOLVER` chooses who is asked (`app/dns_resolver.py`):

| Value | Resolver |
| --- | --- |
| not set | dnspython, with the resolvers of the system |
| an IP address | dnspython, with that one nameserver |
| an `https://` URL | DNS over HTTPS (RFC 8484, GET), certificates checked, no redirect followed |

dnspython (ISC licence, audited in `docs/licences.md`) is already a runtime
dependency; the DNS-over-HTTPS resolver uses the standard library, so httpx is not
needed in the image. Every lookup has a deadline of five seconds. Any other value of
`DNS_RESOLVER` stops the start with `DNS_RESOLVER must be an IP address or an
https:// URL`.

## How a run is stored

`POST /api/v1/clients/{id}/dns-check` with `{"domains": [...], "selectors": [...],
"providers": [...]}` (the last two are optional) runs the check and stores one
evidence item of the source `dns-check`:

- the domain is replaced by the client's pseudonym, the same one the `domain` of the
  Exchange DKIM rows gets, so the two sources can be matched;
- the capture time is the time the run started, timezone-aware UTC. A naive time is
  refused (`captured_at must carry a timezone`), as in the scoring engine;
- the item goes into the client's hash chain like any other evidence;
- nobody can upload a `dns-check` file by hand: the adapter is not in the default
  registry.

`GET /api/v1/clients/{id}/dns-check` returns `PC-EML-01` to `PC-EML-03` from the newest
`dns-check` item (and the newest Exchange export, which `PC-EML-02` also reads), each
with `evidence_at`, the time the evidence was captured, and its age.

An invalid domain, selector or provider answers 422 and nothing is looked up; an
unknown client answers 404. Both routes need a Bearer token and share the API rate
limit.

## Results

The columns stored for a domain are those documented in `app/checks/email.py`.

| Record shape | Stored | PC-EML-01 / PC-EML-03 |
| --- | --- | --- |
| No SPF record | `spf_records` 0 | fail |
| Two or more `v=spf1` records | `spf_records` 2 or more | fail |
| SPF ends `?all` or has no `all` | `spf_ending` neutral | partial |
| SPF ends `~all` or `-all`, provider included | `spf_ending` softfail or fail | pass |
| SPF ends `~all` or `-all`, provider not included | `spf_provider` false | fail |
| SPF ends `+all` | `spf_ending` pass | fail |
| No DMARC record, or two | `dmarc_records` 0 or 2 | fail |
| DMARC `p=none` with `rua` | `dmarc_policy` none | partial |
| DMARC `p=none` without `rua` | `dmarc_policy` none | fail |
| DMARC `p=quarantine` or `reject`, `pct` 100, with `rua` | | pass |
| DMARC `p=quarantine` or `reject`, `pct` below 100 or no `rua` | | partial |

`PC-EML-02` passes for a domain when Exchange says DKIM signing is enabled and at
least one selector record exists (`selector1` and `selector2` are always asked, with
the selectors the MSP supplies; a selector exists as a CNAME or as a TXT record with a
`p=` key).

With more than one domain, the rule of the control decides from the share of domains
that pass (`partial_share` in `data/controls.yaml`).

### The SPF limit of ten lookups

The SPF standard lets a receiver make at most ten DNS lookups while it evaluates a
record. The check counts every `include`, `a`, `mx`, `ptr` and `exists` term and the
`redirect`, following `include:` and `redirect=` targets. `spf_lookups` is the count
(11 means more than the limit) and `spf_over_limit` is true above ten. 11 includes are
therefore reported as over the limit. If a lookup failed before the whole record was
followed, the count and the provider are stored as unknown and never guessed.

### A lookup that fails is unknown, never a fail

A timeout, SERVFAIL, a refused or unreadable answer, or a spent query budget stores
the domain with `lookup_failed` true and the reason (`timeout`, `servfail`,
`resolver_error` or `query_limit`). The check engine reads it as unknown with the
reason `lookup_failed`. A run that fails therefore never turns a pass into a fail: the
newest run is the one that counts, and for a domain it could not look up it says
unknown, which the score treats as no evidence. A name that does not
exist (NXDOMAIN) or has no such record is not a failure: it is a fact (no record).

## Tests

`tests/dns_helpers.py` has a fake resolver that answers from a table and records every
question. Every test of the check uses it; the test run blocks the real network
(`tests/conftest.py`), so a test that reaches a real resolver fails.
`scripts/e2e/phase_07.sh` runs the check inside the image against a stub, with no DNS
question leaving the machine. The scheduled re-check (phase 10) and the page of the
checklist (phase 9) call `run_dns_check` and `dns_controls` from `app/dns_service.py`.

## Known limit

A run holds its database transaction open while the resolver answers. With the 400
question budget and the five second deadline of a lookup, a resolver that fails badly
can keep it open for minutes. The check runs in a thread, so the event loop is not
blocked.
