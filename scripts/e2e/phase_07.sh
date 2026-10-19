#!/usr/bin/env bash
# Phase 7 end-to-end check against a running compose stack. Run with:
#   bash scripts/e2e/phase_07.sh
#
# Proves, in the image that the stack runs, with the resolver stubbed (no DNS question
# leaves the machine):
#   - the DNS check runs in the image: every record shape of PC-EML-01 to 03 gives the
#     documented result, 11 includes are reported as over the lookup limit, and a
#     timeout is stored as unknown with a reason and never as a fail;
#   - the importer turns a run into facts and the check engine reads them;
#   - the production resolvers exist in the image (dnspython is installed) and refuse
#     a bad DNS_RESOLVER setting;
#   - the new API routes answer 401 to a wrong token.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"

fail() { echo "::error::phase_07: FAIL: $*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker is not available"
command -v curl >/dev/null 2>&1 || fail "curl is not available"

web="$(docker ps -q \
  --filter label=com.docker.compose.project=revrook \
  --filter label=com.docker.compose.service=web | head -n 1)"
[[ -n "${web}" ]] || fail "no compose web container found by label"

code="$(curl -sS --max-time 30 -o /dev/null -w '%{http_code}' "${BASE_URL}/readyz")"
[[ "${code}" == "200" ]] || fail "/readyz returned ${code}"

# The routes exist and are closed: 401 for a wrong bearer token (404 would mean absent).
for method in GET POST; do
  code="$(curl -sS --max-time 30 -o /dev/null -w '%{http_code}' -X "${method}" \
    -H 'Authorization: Bearer rvk_not-a-real-token' \
    -H 'Content-Type: application/json' -d '{"domains":["client.example"]}' \
    "${BASE_URL}/api/v1/clients/1/dns-check")"
  [[ "${code}" == "401" ]] || fail "${method} /api/v1/clients/1/dns-check returned ${code}, not 401"
  echo "phase_07: ${method} dns-check with a wrong token is 401"
done

docker exec -i "${web}" python - <<'PY'
from datetime import UTC, datetime, timedelta

from app.checks.dnscheck import TIMEOUT, LookupFailure, run_checks
from app.checks.engine import evaluate_control
from app.checks.library import load_library
from app.checks.model import Evidence, SourceFacts
from app.dns_resolver import DnsPythonResolver, DohResolver, make_resolver
from app.importers.dnscheck import DnsCheckImporter
from app.checks.dnscheck import render_document

AT = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
LIBRARY = load_library()
PROVIDER = "spf.protection.outlook.com"


class Stub:
    """Answers from a table; any name it does not know has no record."""

    def __init__(self, table):
        self.table = table
        self.asked = []

    def lookup(self, name, rdtype):
        self.asked.append((name, rdtype))
        answer = self.table.get((name, rdtype), ())
        if isinstance(answer, LookupFailure):
            raise answer
        return tuple(answer)


def run(table, domain="client.example"):
    stub = Stub(table)
    check = run_checks(stub, [domain], captured_at=AT)
    parsed = DnsCheckImporter().parse(render_document(check), 1000)
    rows = [(fact.key, fact.value) for fact in parsed.facts]
    sources = {"dns-check": SourceFacts.from_facts(parsed.captured_at, rows)}
    evidence = Evidence(as_of=AT + timedelta(days=1), sources=sources)
    results = {
        cid: evaluate_control(LIBRARY, LIBRARY.control(cid), evidence)
        for cid in ("PC-EML-01", "PC-EML-03")
    }
    return check.domains[0], results, stub


good = {
    ("client.example", "TXT"): [f"v=spf1 include:{PROVIDER} -all"],
    ("_dmarc.client.example", "TXT"): [
        "v=DMARC1; p=reject; rua=mailto:dmarc@client.example"
    ],
    ("selector1._domainkey.client.example", "CNAME"): ["target.example.net"],
}
domain, results, stub = run(good)
assert domain.failure is None and domain.dkim.published, domain
assert results["PC-EML-01"].status == "pass", results["PC-EML-01"]
assert results["PC-EML-03"].status == "pass", results["PC-EML-03"]
assert results["PC-EML-01"].evidence_at == AT
assert {name for name, _ in stub.asked} <= {
    "client.example",
    "_dmarc.client.example",
    "selector1._domainkey.client.example",
    "selector2._domainkey.client.example",
    PROVIDER,
}, stub.asked
print("phase_07: a good domain passes PC-EML-01 and PC-EML-03 in the image")

weak = {
    ("client.example", "TXT"): ["v=spf1 include:" + PROVIDER + " ~all"],
    ("_dmarc.client.example", "TXT"): ["v=DMARC1; p=none"],
}
_, results, _ = run(weak)
assert results["PC-EML-01"].status == "pass", results["PC-EML-01"]
assert results["PC-EML-03"].status == "fail", results["PC-EML-03"]
print("phase_07: SPF soft fail with the provider passes, DMARC p=none fails")

includes = " ".join(f"include:inc{n}.example.net" for n in range(11))
many = {("client.example", "TXT"): [f"v=spf1 {includes} -all"]}
domain, _, _ = run(many)
assert domain.spf.over_limit is True and domain.spf.lookups == 11, domain.spf
print("phase_07: 11 includes are reported as over the limit of 10")

down = {**good, ("client.example", "TXT"): LookupFailure(TIMEOUT)}
domain, results, _ = run(down)
assert domain.failure == "timeout", domain
for cid in ("PC-EML-01", "PC-EML-03"):
    assert results[cid].status == "unknown", results[cid]
    assert results[cid].reason == "lookup_failed", results[cid]
print("phase_07: a timeout is unknown (lookup_failed), never a fail")

assert type(make_resolver(None)) is DnsPythonResolver
assert type(make_resolver("9.9.9.9")) is DnsPythonResolver
assert type(make_resolver("https://dns.example/dns-query")) is DohResolver
try:
    make_resolver("not an address")
except ValueError:
    pass
else:
    raise AssertionError("a bad DNS_RESOLVER was accepted")
print("phase_07: the production resolvers load in the image")
PY

echo "phase_07: OK"
