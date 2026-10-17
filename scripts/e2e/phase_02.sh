#!/usr/bin/env bash
# Phase 2 end-to-end check against a running compose stack (check 9 runs it through
# tests/e2e/run.sh). Run with: bash scripts/e2e/phase_02.sh
#
# Proves, with a synthetic file only:
#   - an upload through the API is stored and the client's hash chain verifies;
#   - no synthetic user name survives in the database (dump grep finds none);
#   - with the default retention of 0 days the raw file is gone after parsing;
#   - a second upload of the same file for the same client is refused (409) with
#     a readable message;
#   - deleting the client removes everything of it, leaves only audit entries and
#     the chain command still reports every chain intact.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
UPN_MARKER="phase02.e2e"
ADMIN_PASSWORD="phase02-e2e-throwaway-password-0001"

fail() { echo "::error::phase_02: FAIL: $*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker is not available"
command -v curl >/dev/null 2>&1 || fail "curl is not available"
command -v jq >/dev/null 2>&1 || fail "jq is not available"

service_container() {
  docker ps -q \
    --filter label=com.docker.compose.project=revrook \
    --filter label=com.docker.compose.service="$1" | head -n 1
}
web="$(service_container web)"
db="$(service_container db)"
[[ -n "${web}" ]] || fail "no compose web container found by label"
[[ -n "${db}" ]] || fail "no compose db container found by label"

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

sql() { docker exec "${db}" psql -U revrook -d revrook -tA -c "$1"; }

# The first administrator and an API token. There is no page that issues a token
# in this phase, so the application's own functions do it inside the web container.
token="$(docker exec -i -e ADMIN_PASSWORD="${ADMIN_PASSWORD}" "${web}" python - <<'PY' | tail -n 1
import asyncio
import os

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth import create_first_admin, issue_api_token
from app.db import make_engine
from app.settings import load_settings


async def main() -> None:
    engine = make_engine(load_settings().database_url)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            user = await create_first_admin(
                session, "phase02-admin", os.environ["ADMIN_PASSWORD"]
            )
            print(await issue_api_token(session, user, "phase02-e2e"))
    finally:
        await engine.dispose()


asyncio.run(main())
PY
)"
[[ -n "${token}" ]] || fail "no API token was issued"

api() { curl -sS --max-time 30 -H "Authorization: Bearer ${token}" "$@"; }

who="$(api "${BASE_URL}/api/v1/whoami" | jq -r .username)"
[[ "${who}" == "phase02-admin" ]] || fail "whoami returned '${who}'"
echo "phase_02: token works"

client_name="Phase 02 E2E Client"
client_id="$(api -X POST -H 'Content-Type: application/json' \
  -d "{\"name\": \"${client_name}\"}" "${BASE_URL}/api/v1/clients" | jq -r .id)"
[[ "${client_id}" =~ ^[0-9]+$ ]] || fail "client was not created (id '${client_id}')"
echo "phase_02: client ${client_id} created"

csv="${work}/users.csv"
{
  echo "user_principal_name,mfa_registered"
  echo "alice@${UPN_MARKER}.example.invalid,true"
  echo "bob@${UPN_MARKER}.example.invalid,false"
  echo "carol@${UPN_MARKER}.example.invalid,yes"
} > "${csv}"
captured="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

upload() {
  api -o "${work}/upload.json" -w '%{http_code}' \
    -F "file=@${csv}" -F source_code=reference-csv -F "captured_at=${captured}" \
    "${BASE_URL}/api/v1/clients/${client_id}/evidence"
}

code="$(upload)"
[[ "${code}" == "201" ]] || fail "upload returned ${code}: $(cat "${work}/upload.json")"
retained="$(jq -r .raw_retained "${work}/upload.json")"
facts="$(jq -r '.facts' "${work}/upload.json")"
echo "phase_02: upload 201, raw_retained=${retained}, facts=${facts}"

# Retention 0 (the default): the raw file is gone once it is parsed.
[[ "${retained}" == "false" ]] || fail "raw_retained is ${retained}, expected false with retention 0"
on_disk="$(docker exec "${web}" sh -c "find /data/evidence/${client_id} -type f 2>/dev/null | wc -l")"
[[ "${on_disk}" == "0" ]] || fail "${on_disk} raw file(s) remain on disk with retention 0"
echo "phase_02: no raw file on disk"

# Duplicate upload for the same client: refused with a readable message.
code="$(upload)"
[[ "${code}" == "409" ]] || fail "duplicate upload returned ${code}, expected 409"
message="$(jq -r .detail "${work}/upload.json")"
[[ -n "${message}" && "${message}" != "null" ]] || fail "duplicate upload gave no readable message"
echo "phase_02: duplicate refused (409): ${message}"

# The chain verifies, through the API and through the command.
chain="$(api "${BASE_URL}/api/v1/clients/${client_id}/evidence/chain")"
[[ "$(echo "${chain}" | jq -r .ok)" == "true" ]] || fail "chain is not intact: ${chain}"
records="$(echo "${chain}" | jq -r .records)"
[[ "${records}" -ge 1 ]] || fail "chain has ${records} records, expected at least 1"
docker exec "${web}" python -m app.cli verify-chain || fail "verify-chain reported a broken chain"
echo "phase_02: chain intact, ${records} records"

# No synthetic user name survives in any stored fact: the whole dump is searched.
dump="${work}/dump.sql"
docker exec "${db}" pg_dump -U revrook revrook > "${dump}"
[[ -s "${dump}" ]] || fail "the database dump is empty"
hits="$(grep -c "${UPN_MARKER}" "${dump}" || true)"
[[ "${hits}" == "0" ]] || fail "${hits} line(s) of the database dump contain the synthetic user name"
echo "phase_02: no synthetic user name in the database dump"

# A wrong confirmation deletes nothing; the right one deletes everything.
code="$(api -o "${work}/delete.json" -w '%{http_code}' -X DELETE \
  "${BASE_URL}/api/v1/clients/${client_id}?confirm=wrong")"
[[ "${code}" == "422" ]] || fail "delete with a wrong confirmation returned ${code}, expected 422"
[[ "$(sql "SELECT count(*) FROM client WHERE id = ${client_id}")" == "1" ]] \
  || fail "the client vanished after a refused delete"

encoded_name="${client_name// /%20}"
code="$(api -o "${work}/delete.json" -w '%{http_code}' -X DELETE \
  "${BASE_URL}/api/v1/clients/${client_id}?confirm=${encoded_name}")"
[[ "${code}" == "200" ]] || fail "delete returned ${code}: $(cat "${work}/delete.json")"
echo "phase_02: client deleted: $(jq -c . "${work}/delete.json")"

for table in evidence_item snapshot report_export; do
  count="$(sql "SELECT count(*) FROM ${table} WHERE client_id = ${client_id}")"
  [[ "${count}" == "0" ]] || fail "${count} row(s) of ${table} remain for the deleted client"
done
[[ "$(sql "SELECT count(*) FROM client WHERE id = ${client_id}")" == "0" ]] \
  || fail "the client row remains"
[[ "$(sql "SELECT count(*) FROM fact")" == "0" ]] || fail "facts remain after the delete"
remaining="$(docker exec "${web}" sh -c "find /data/evidence/${client_id} 2>/dev/null | wc -l")"
[[ "${remaining}" == "0" ]] || fail "the client's evidence folder remains"
[[ "$(sql "SELECT count(*) FROM audit_event WHERE action = 'client.deleted'")" -ge 1 ]] \
  || fail "the audit trail has no entry about the client"
docker exec "${web}" python -m app.cli verify-chain || fail "verify-chain failed after the delete"

echo "phase_02: OK"
