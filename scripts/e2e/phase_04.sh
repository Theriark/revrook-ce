#!/usr/bin/env bash
# Phase 4 end-to-end check against a running compose stack (check 9 runs it through
# tests/e2e/run.sh). Run with: bash scripts/e2e/phase_04.sh
#
# Proves, with synthetic files only (tools/make_generic_fixtures.py, seeded):
#   - the six generic fixtures import through the API and every summary fact (counts
#     and flags) equals the manifest the generator wrote;
#   - a vendor-style file with other column names imports through a saved mapping
#     profile (API: save the profile, name it in the upload) and not without it;
#   - a file missing a required column is refused with the column named;
#   - hostile files: a formula cell is neutralised, a field above the CSV limit and
#     JSON are refused, and an email-like text rejects its row and not the upload;
#   - serial numbers, client names, host, job, system, network and mail-domain names
#     and the syslog address never reach the database (dump grep);
#   - the client's hash chain verifies, and deleting the client leaves nothing.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
ADMIN_PASSWORD="phase04-e2e-throwaway-password-0001"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

fail() { echo "::error::phase_04: FAIL: $*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker is not available"
command -v curl >/dev/null 2>&1 || fail "curl is not available"
command -v jq >/dev/null 2>&1 || fail "jq is not available"
command -v python3 >/dev/null 2>&1 || fail "python3 is not available"

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

# An API token. An earlier phase has already created the administrator, so the first
# existing user is used when there is one.
token="$(docker exec -i -e ADMIN_PASSWORD="${ADMIN_PASSWORD}" "${web}" python - <<'PY' | tail -n 1
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth import count_users, create_first_admin, issue_api_token
from app.db import make_engine
from app.models import AppUser
from app.settings import load_settings


async def main() -> None:
    engine = make_engine(load_settings().database_url)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            if await count_users(session) == 0:
                user = await create_first_admin(
                    session, "phase04-admin", os.environ["ADMIN_PASSWORD"]
                )
            else:
                found = await session.execute(
                    select(AppUser).order_by(AppUser.id).limit(1)
                )
                user = found.scalar_one()
            print(await issue_api_token(session, user, "phase04-e2e"))
    finally:
        await engine.dispose()


asyncio.run(main())
PY
)"
[[ -n "${token}" ]] || fail "no API token was issued"

api() { curl -sS --max-time 60 -H "Authorization: Bearer ${token}" "$@"; }

who="$(api "${BASE_URL}/api/v1/whoami" | jq -r .username)"
[[ -n "${who}" && "${who}" != "null" ]] || fail "the token does not work (whoami '${who}')"
echo "phase_04: token works"

fixtures="${work}/fixtures"
(cd "${ROOT}" && python3 -m tools.make_generic_fixtures "${fixtures}" >/dev/null)
manifest="${fixtures}/manifest.json"
[[ -s "${manifest}" ]] || fail "the fixture generator wrote no manifest"
[[ "$(jq '.files | length' "${manifest}")" == "6" ]] || fail "the manifest does not list six files"

client_name="Phase 04 E2E Client"
client_id="$(api -X POST -H 'Content-Type: application/json' \
  -d "{\"name\": \"${client_name}\"}" "${BASE_URL}/api/v1/clients" | jq -r .id)"
[[ "${client_id}" =~ ^[0-9]+$ ]] || fail "client was not created (id '${client_id}')"
echo "phase_04: client ${client_id} created"

captured="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# upload FILE SOURCE [PROFILE_ID]: the HTTP status goes to stdout, the body to
# ${work}/upload.json.
upload() {
  local extra=()
  if [[ -n "${3:-}" ]]; then extra=(-F "profile_id=$3"); fi
  api -o "${work}/upload.json" -w '%{http_code}' \
    -F "file=@$1" -F "source_code=$2" -F "captured_at=${captured}" "${extra[@]}" \
    "${BASE_URL}/api/v1/clients/${client_id}/evidence"
}

# fact_of ITEM EXPRESSION CONDITION: one expression of the facts of one stored file.
fact_of() { sql "SELECT $2 FROM fact WHERE evidence_item_id = $1 AND $3"; }

# The six fixtures: status 201, the fact count of the manifest, the summary fact equal
# to the expected counts and flags, and the upload time as the capture time (a CSV
# carries none).
for name in $(jq -r '.files | keys[]' "${manifest}"); do
  source_code="$(jq -r --arg f "${name}" '.files[$f].source_code' "${manifest}")"
  code="$(upload "${fixtures}/${name}" "${source_code}")"
  [[ "${code}" == "201" ]] || fail "${name}: upload returned ${code}: $(cat "${work}/upload.json")"
  facts="$(jq -r .facts "${work}/upload.json")"
  want_facts="$(jq -r --arg f "${name}" '.files[$f].facts' "${manifest}")"
  [[ "${facts}" == "${want_facts}" ]] || fail "${name}: ${facts} facts, expected ${want_facts}"

  item="$(jq -r .item_id "${work}/upload.json")"
  got="$(fact_of "${item}" "value::text" "fact_key LIKE '%.summary'" | jq -S -c .)"
  want="$(jq -S -c --arg f "${name}" '.files[$f].expected' "${manifest}")"
  [[ "${got}" == "${want}" ]] || fail "${name}: summary ${got}, expected ${want}"

  stored_time="$(jq -r .captured_at "${work}/upload.json")"
  [[ "${stored_time}" == "${captured%Z}"* ]] || fail "${name}: expected the upload time, got ${stored_time}"
  echo "phase_04: ${name} -> ${source_code}: ${facts} facts, summary as expected"
done

# A vendor-style file with other column names: refused as it is, imported through a
# saved mapping profile that the upload names.
vendor="${work}/vendor.csv"
{
  echo 'Computer,Operating system,Last check-in,Patches,Critical updates,AV product,AV state,AV signatures,Encrypted'
  echo 'phase04-vendor-host,Windows 11,2026-10-16T08:00:00,up_to_date,0,Synthetic Shield,protected,2026-10-15T08:00:00Z,true'
} > "${vendor}"
code="$(upload "${vendor}" device-inventory)"
[[ "${code}" == "422" ]] || fail "the vendor file without a profile returned ${code}, expected 422"
[[ "$(jq -r .detail "${work}/upload.json")" == *"missing the column"* ]] \
  || fail "no readable message for the vendor file: $(cat "${work}/upload.json")"
mapping='{"Computer":"hostname","Operating system":"os","Last check-in":"last_seen","Patches":"patch_status","Critical updates":"pending_critical_updates","AV product":"av_product","AV state":"av_status","AV signatures":"av_signature_date","Encrypted":"disk_encrypted"}'
profile="$(api -X POST -H 'Content-Type: application/json' \
  -d "{\"name\": \"Phase 04 vendor\", \"source_code\": \"device-inventory\", \"mapping\": ${mapping}}" \
  "${BASE_URL}/api/v1/clients/${client_id}/import-profiles")"
profile_id="$(jq -r .id <<<"${profile}")"
[[ "${profile_id}" =~ ^[0-9]+$ ]] || fail "the mapping profile was not saved: ${profile}"
code="$(upload "${vendor}" device-inventory "${profile_id}")"
[[ "${code}" == "201" ]] || fail "the mapped vendor file returned ${code}: $(cat "${work}/upload.json")"
item="$(jq -r .item_id "${work}/upload.json")"
devices="$(fact_of "${item}" "value->>'devices'" "fact_key = 'inventory.summary'")"
assumed="$(fact_of "${item}" "value->>'timezone_assumed_utc'" "fact_key = 'inventory.summary'")"
[[ "${devices}" == "1" ]] || fail "the mapped vendor file gave ${devices} devices, expected 1"
[[ "${assumed}" == "true" ]] || fail "a date without a time zone was not flagged (${assumed})"
echo "phase_04: vendor-style file imported through profile ${profile_id}, UTC assumption flagged"

# A missing required column refuses the file and names the column.
printf 'hostname,os\nphase04-short,Windows\n' > "${work}/short.csv"
code="$(upload "${work}/short.csv" device-inventory)"
[[ "${code}" == "422" ]] || fail "a file without required columns returned ${code}, expected 422"
message="$(jq -r .detail "${work}/upload.json")"
[[ "${message}" == *"missing the column last_seen"* ]] || fail "the message does not name the column: ${message}"
echo "phase_04: missing column refused: ${message}"

# Hostile files. A formula cell is neutralised; an email-like text rejects its row and
# not the upload; a field above the CSV limit and JSON are refused.
header='hostname,os,last_seen,patch_status,pending_critical_updates,av_product,av_status,av_signature_date,disk_encrypted'
row() { printf '%s,Windows 11,2026-10-16T08:00:00Z,up_to_date,0,%s,protected,2026-10-15T08:00:00Z,true\n' "$1" "$2"; }
{ echo "${header}"; row phase04-formula "=cmd|' /C calc'!A0"; } > "${work}/formula.csv"
code="$(upload "${work}/formula.csv" device-inventory)"
[[ "${code}" == "201" ]] || fail "the formula file returned ${code}: $(cat "${work}/upload.json")"
product="$(fact_of "$(jq -r .item_id "${work}/upload.json")" "value->>'av_product'" "fact_key = 'inventory.device'")"
[[ "${product}" == "'="* ]] || fail "the formula cell was not neutralised: ${product}"

{ echo "${header}"; row phase04-leaky "contact ops@phase04.example.invalid"; row phase04-fine "Synthetic Shield"; } > "${work}/leaky.csv"
code="$(upload "${work}/leaky.csv" device-inventory)"
[[ "${code}" == "201" ]] || fail "the email-like file returned ${code}: $(cat "${work}/upload.json")"
item="$(jq -r .item_id "${work}/upload.json")"
[[ "$(fact_of "${item}" "value->>'devices'" "fact_key = 'inventory.summary'")" == "1" ]] || fail "the good row of the email-like file was not kept"
[[ "$(fact_of "${item}" "value->>'rows_rejected'" "fact_key = 'inventory.summary'")" == "1" ]] || fail "the email-like row was not rejected"

{ echo "${header}"; head -c 200000 /dev/zero | tr '\0' x; printf ',Windows\n'; } > "${work}/huge.csv"
code="$(upload "${work}/huge.csv" device-inventory)"
[[ "${code}" == "422" ]] || fail "a field above the CSV limit returned ${code}, expected 422"
[[ "$(jq -r .detail "${work}/upload.json")" == *"not a readable CSV"* ]] || fail "no readable message for the huge field"

deep='{"value": []}'
for _ in $(seq 40); do deep="{\"value\": [${deep}]}"; done
printf '%s' "${deep}" > "${work}/deep.json"
code="$(upload "${work}/deep.json" leavers-csv)"
[[ "${code}" == "422" ]] || fail "JSON for a CSV source returned ${code}, expected 422"
[[ "$(jq -r .detail "${work}/upload.json")" == *"must be a CSV file"* ]] || fail "no readable message for JSON"
echo "phase_04: formula neutralised, email-like text rejected as a row, huge field and JSON refused"

# Nothing unread, personal or free-text reached the database.
dump="${work}/dump.sql"
docker exec "${db}" pg_dump -U revrook revrook > "${dump}"
[[ -s "${dump}" ]] || fail "the database dump is empty"
needles=("$(jq -r .domain "${manifest}")" "phase04.example.invalid" "phase04-vendor-host" "phase04-formula")
while IFS= read -r value; do needles+=("${value}"); done < <(jq -r '.unread_values[]' "${manifest}")
for needle in "${needles[@]}"; do
  hits="$(grep -cF -- "${needle}" "${dump}" || true)"
  [[ "${hits}" == "0" ]] || fail "${hits} line(s) of the database dump contain '${needle}'"
done
count="$(sql "SELECT count(*) FROM fact WHERE client_id = ${client_id}")"
[[ "${count}" -gt 0 ]] || fail "the client has no facts"
echo "phase_04: no serial, client name, host, job, system, network or domain name in the database"

# The chain verifies, through the API and through the command.
chain="$(api "${BASE_URL}/api/v1/clients/${client_id}/evidence/chain")"
[[ "$(echo "${chain}" | jq -r .ok)" == "true" ]] || fail "chain is not intact: ${chain}"
docker exec "${web}" python -m app.cli verify-chain || fail "verify-chain reported a broken chain"

# Delete the client: everything of it goes.
encoded_name="${client_name// /%20}"
code="$(api -o "${work}/delete.json" -w '%{http_code}' -X DELETE \
  "${BASE_URL}/api/v1/clients/${client_id}?confirm=${encoded_name}")"
[[ "${code}" == "200" ]] || fail "delete returned ${code}: $(cat "${work}/delete.json")"
for table in evidence_item fact import_profile; do
  left="$(sql "SELECT count(*) FROM ${table} WHERE client_id = ${client_id}")"
  [[ "${left}" == "0" ]] || fail "${left} row(s) of ${table} remain for the deleted client"
done
docker exec "${web}" python -m app.cli verify-chain || fail "verify-chain failed after the delete"

echo "phase_04: OK"
