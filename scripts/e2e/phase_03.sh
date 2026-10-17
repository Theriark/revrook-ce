#!/usr/bin/env bash
# Phase 3 end-to-end check against a running compose stack (check 9 runs it through
# tests/e2e/run.sh). Run with: bash scripts/e2e/phase_03.sh
#
# Proves, with synthetic files only (tools/make_fixtures.py, seeded):
#   - the five Microsoft fixtures import through the API and every summary fact
#     (counts and flags) equals the manifest the generator wrote;
#   - the sensitive fields (imei, phoneNumber, activationLockBypassCode), the mail
#     domain, device names and policy names never reach the database (dump grep);
#   - a file of another source is refused with a message naming the missing column;
#   - a formula cell is neutralised and deeply nested JSON is refused;
#   - the client's hash chain verifies, and deleting the client leaves nothing.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
ADMIN_PASSWORD="phase03-e2e-throwaway-password-0001"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

fail() { echo "::error::phase_03: FAIL: $*" >&2; exit 1; }

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

# An API token. The first run creates the administrator; a later run (or phase 2,
# which runs first) has already done that, so the first existing user is used.
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
                    session, "phase03-admin", os.environ["ADMIN_PASSWORD"]
                )
            else:
                found = await session.execute(
                    select(AppUser).order_by(AppUser.id).limit(1)
                )
                user = found.scalar_one()
            print(await issue_api_token(session, user, "phase03-e2e"))
    finally:
        await engine.dispose()


asyncio.run(main())
PY
)"
[[ -n "${token}" ]] || fail "no API token was issued"

api() { curl -sS --max-time 60 -H "Authorization: Bearer ${token}" "$@"; }

who="$(api "${BASE_URL}/api/v1/whoami" | jq -r .username)"
[[ -n "${who}" && "${who}" != "null" ]] || fail "the token does not work (whoami '${who}')"
echo "phase_03: token works"

fixtures="${work}/fixtures"
python3 "${ROOT}/tools/make_fixtures.py" "${fixtures}" >/dev/null
manifest="${fixtures}/manifest.json"
[[ -s "${manifest}" ]] || fail "the fixture generator wrote no manifest"
[[ "$(jq '.files | length' "${manifest}")" == "5" ]] || fail "the manifest does not list five files"

client_name="Phase 03 E2E Client"
client_id="$(api -X POST -H 'Content-Type: application/json' \
  -d "{\"name\": \"${client_name}\"}" "${BASE_URL}/api/v1/clients" | jq -r .id)"
[[ "${client_id}" =~ ^[0-9]+$ ]] || fail "client was not created (id '${client_id}')"
echo "phase_03: client ${client_id} created"

captured="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# upload FILE SOURCE: the HTTP status goes to stdout, the body to ${work}/upload.json.
upload() {
  api -o "${work}/upload.json" -w '%{http_code}' \
    -F "file=@$1" -F "source_code=$2" -F "captured_at=${captured}" \
    "${BASE_URL}/api/v1/clients/${client_id}/evidence"
}

# The five fixtures: status 201, the fact count of the manifest, the summary fact
# equal to the expected counts and flags, and the capture time from the file when
# the file has one.
for name in $(jq -r '.files | keys[]' "${manifest}"); do
  source_code="$(jq -r --arg f "${name}" '.files[$f].source_code' "${manifest}")"
  code="$(upload "${fixtures}/${name}" "${source_code}")"
  [[ "${code}" == "201" ]] || fail "${name}: upload returned ${code}: $(cat "${work}/upload.json")"
  facts="$(jq -r .facts "${work}/upload.json")"
  want_facts="$(jq -r --arg f "${name}" '.files[$f].facts' "${manifest}")"
  [[ "${facts}" == "${want_facts}" ]] || fail "${name}: ${facts} facts, expected ${want_facts}"

  item="$(jq -r .item_id "${work}/upload.json")"
  got="$(sql "SELECT value::text FROM fact WHERE evidence_item_id = ${item} AND fact_key LIKE '%.summary'" | jq -S -c .)"
  want="$(jq -S -c --arg f "${name}" '.files[$f].expected' "${manifest}")"
  [[ "${got}" == "${want}" ]] || fail "${name}: summary ${got}, expected ${want}"

  stored_time="$(jq -r .captured_at "${work}/upload.json")"
  from="$(jq -r --arg f "${name}" '.files[$f].expected.capture_time_source' "${manifest}")"
  if [[ "${from}" == "file" ]]; then
    [[ "${stored_time}" != "${captured}"* ]] || fail "${name}: the capture time is the upload time"
  else
    [[ "${stored_time}" == "${captured%Z}"* ]] || fail "${name}: expected the upload time, got ${stored_time}"
  fi
  echo "phase_03: ${name} -> ${source_code}: ${facts} facts, summary as expected (${from} time)"
done

# A file of another source is refused, and the message names the missing column.
code="$(upload "${fixtures}/intune-devices.csv" entra-registration)"
[[ "${code}" == "422" ]] || fail "a wrong file returned ${code}, expected 422"
message="$(jq -r .detail "${work}/upload.json")"
[[ "${message}" == *"missing the column User principal name"* ]] \
  || fail "the message does not name the missing column: ${message}"
echo "phase_03: wrong file refused: ${message}"

# Hostile files: a formula cell is neutralised, deeply nested JSON is refused.
formula="${work}/roles-formula.csv"
printf 'User principal name,Role,Enabled\nformula@phase03.example.invalid,"=HYPERLINK(""http://x.invalid"")",true\n' > "${formula}"
code="$(upload "${formula}" directory-roles)"
[[ "${code}" == "201" ]] || fail "the formula file returned ${code}: $(cat "${work}/upload.json")"
role="$(sql "SELECT value->>'role' FROM fact WHERE evidence_item_id = $(jq -r .item_id "${work}/upload.json") AND fact_key = 'roles.assignment'")"
[[ "${role}" == "'="* ]] || fail "the formula cell was not neutralised: ${role}"

deep='{"value": []}'
for _ in $(seq 40); do deep="{\"value\": [${deep}]}"; done
printf '%s' "${deep}" > "${work}/deep.json"
code="$(upload "${work}/deep.json" entra-registration)"
[[ "${code}" == "422" ]] || fail "deeply nested JSON returned ${code}, expected 422"
[[ "$(jq -r .detail "${work}/upload.json")" == *"nested deeper"* ]] || fail "no readable message for deep JSON"
echo "phase_03: formula neutralised, deep JSON refused"

# Nothing sensitive, personal or free-text reached the database.
dump="${work}/dump.sql"
docker exec "${db}" pg_dump -U revrook revrook > "${dump}"
[[ -s "${dump}" ]] || fail "the database dump is empty"
needles=("$(jq -r .domain "${manifest}")" "$(jq -r .device_name_prefix "${manifest}")" "phase03.example.invalid")
while IFS= read -r value; do needles+=("${value}"); done < <(jq -r '.sensitive_values[], .policy_names[]' "${manifest}")
for needle in "${needles[@]}"; do
  hits="$(grep -cF -- "${needle}" "${dump}" || true)"
  [[ "${hits}" == "0" ]] || fail "${hits} line(s) of the database dump contain '${needle}'"
done
fields="$(sql "SELECT coalesce(string_agg(fact_key || ' ' || value::text, ' '), '') FROM fact")"
[[ -n "${fields}" ]] || fail "the client has no facts"
[[ "$(grep -ciE 'imei|phonenumber|activationlockbypass' <<<"${fields}" || true)" == "0" ]] \
  || fail "a sensitive field name reached the fact table"
echo "phase_03: no sensitive value, mail domain, device name or policy name in the database"

# The chain verifies, through the API and through the command.
chain="$(api "${BASE_URL}/api/v1/clients/${client_id}/evidence/chain")"
[[ "$(echo "${chain}" | jq -r .ok)" == "true" ]] || fail "chain is not intact: ${chain}"
docker exec "${web}" python -m app.cli verify-chain || fail "verify-chain reported a broken chain"

# Delete the client: everything of it goes.
encoded_name="${client_name// /%20}"
code="$(api -o "${work}/delete.json" -w '%{http_code}' -X DELETE \
  "${BASE_URL}/api/v1/clients/${client_id}?confirm=${encoded_name}")"
[[ "${code}" == "200" ]] || fail "delete returned ${code}: $(cat "${work}/delete.json")"
for table in evidence_item fact; do
  count="$(sql "SELECT count(*) FROM ${table} WHERE client_id = ${client_id}")"
  [[ "${count}" == "0" ]] || fail "${count} row(s) of ${table} remain for the deleted client"
done
docker exec "${web}" python -m app.cli verify-chain || fail "verify-chain failed after the delete"

echo "phase_03: OK"
