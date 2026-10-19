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

| Record shape | Stored | Domain state |
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

The table gives the state of one domain, which is not always the result of the control.
PC-EML-01 counts only the domains that pass: one domain whose SPF is neutral (state
partial) therefore gives the control a fail, because no domain passes, and with several
domains the share of passing domains decides (see below). PC-EML-03 takes the worst
state of the domains, so a partial domain gives a partial control.

`PC-EML-02` passes for a domain when Exchange says DKIM signing is enabled and at
least one selector record exists (`selector1` and `selector2` are always asked, with
the selectors the MSP supplies; a selector exists as a CNAME or as a TXT record with a
`p=` key).

With more than one domain, PC-EML-01 and PC-EML-02 decide from the share of domains
that pass (`partial_share` in `data/controls.yaml`); PC-EML-03 takes the worst state.

### The SPF limit of ten lookups

The SPF standard lets a receiver make at most ten DNS lookups while it evaluates a
record. The check counts every `include`, `a`, `mx`, `ptr` and `exists` term and the
`redirect`, following `include:` and `redirect=` targets. `spf_lookups` is the count
(11 means more than the limit) and `spf_over_limit` is true above ten. 11 includes are
therefore reported as over the limit. A term is counted every time a receiver would
evaluate it, so an include that appears twice, or in two included records, counts
twice (the record behind its name is asked for once); a record that includes itself, or
two records that include each other, end the walk. If a lookup failed before the whole record was
followed, the count and the provider are stored as unknown and never guessed.

### A lookup that fails is unknown, never a fail

A timeout, SERVFAIL, a refused or unreadable answer, a spent query budget or a spent
run deadline stores the domain with `lookup_failed` true and the reason (`timeout`,
`servfail`, `resolver_error` or `query_limit`). So does an answer the check cannot
read in full: a name with more than 50 TXT records (`too_many_answers`), or an SPF,
DMARC or DKIM record longer than 8192 characters (`answer_too_large`). Cutting such an
answer would show a record as missing or neutral, which is a false fail. (A long text
that is not one of these records is cut and ignored.) The check engine reads it as
unknown with the
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

A DMARC record that is there but cannot be read (no valid `p=`, a `pct` that is not 0
to 100) is not a failed lookup: the control is unknown with the reason
`unresolved_values`, and `lookup_failed` only when a lookup really failed.

## Time and database

The lookups run before any database transaction opens (`look_up_dns` in
`app/dns_service.py`; the API checks the client in a short session, looks up with no
session open, and opens the transaction only to store the result). A run also has a
deadline of 60 seconds: a question asked after it is a timeout, so with the 400
question budget and the five second deadline of one lookup, a resolver that is down
cannot keep a run (or a database connection) busy for minutes. The check runs in a
thread, so the event loop is not blocked.

## Known limit

The DNS-over-HTTPS resolver applies its five second deadline to each socket
operation, not to a whole lookup; the deadline of one lookup is exact only for
dnspython. The run deadline above bounds both. DMARC has no fallback to the
organisational domain for a subdomain.
