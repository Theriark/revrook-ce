#!/usr/bin/env bash
# Phase 10 end-to-end check against a running compose stack (check 9 runs it through
# tests/e2e/run.sh). Run with: bash scripts/e2e/phase_10.sh
#
# Proves, through the HTTP interface of the stack with synthetic files only:
#   - the worker of the stack reports a heartbeat (API and System page) and /metrics is
#     off while METRICS_TOKEN is not set;
#   - a schedule is added, listed and removed through the API, and a bad one is refused;
#   - a snapshot request is run by the worker, once, and shows up as a snapshot;
#   - the data export is a zip with a CSV file per table and no user name in it;
#   - stopping the worker puts a banner on every page within 3 minutes, and starting it
#     again removes the banner;
#   - a client is deleted from the System page (wrong name refused, no token refused)
#     and the deletion is an audit event.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
ADMIN_USER="phase10-admin"
ADMIN_PASSWORD="phase10-e2e-throwaway-password-0001"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

fail() { echo "::error::phase_10: FAIL: $*" >&2; exit 1; }

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
worker="$(service_container worker)"
[[ -n "${web}" ]] || fail "no compose web container found by label"
[[ -n "${db}" ]] || fail "no compose db container found by label"
[[ -n "${worker}" ]] || fail "no compose worker container found by label"

work="$(mktemp -d)"
cleanup() {
  # The worker must run again whatever happened, or the next phase finds it stopped.
  if [[ -z "$(docker ps -q --filter id="${worker}")" ]]; then docker start "${worker}" >/dev/null 2>&1 || true; fi
  rm -rf "${work}"
}
trap cleanup EXIT

sql() { docker exec "${db}" psql -U revrook -d revrook -tA -c "$1"; }

# A dedicated user whose password is known and an API token for it.
token="$(docker exec -i -e ADMIN_USER="${ADMIN_USER}" -e ADMIN_PASSWORD="${ADMIN_PASSWORD}" "${web}" python - <<'PY' | tail -n 1
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth import issue_api_token
from app.db import make_engine
from app.models import AppUser
from app.security import hash_password
from app.settings import load_settings


async def main() -> None:
    engine = make_engine(load_settings().database_url)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            found = await session.execute(
                select(AppUser).where(AppUser.username == os.environ["ADMIN_USER"])
            )
            user = found.scalar_one_or_none()
            if user is None:
                user = AppUser(
                    username=os.environ["ADMIN_USER"],
                    password_hash=hash_password(os.environ["ADMIN_PASSWORD"]),
                )
                session.add(user)
                await session.flush()
            print(await issue_api_token(session, user, "phase10-e2e"))
    finally:
        await engine.dispose()


asyncio.run(main())
PY
)"
[[ -n "${token}" ]] || fail "no API token was issued"
api() { curl -sS --max-time 60 -H "Authorization: Bearer ${token}" "$@"; }
who="$(api "${BASE_URL}/api/v1/whoami" | jq -r .username)"
[[ "${who}" == "${ADMIN_USER}" ]] || fail "the token does not work (whoami '${who}')"

jar="${work}/cookies.txt"
browser() { curl -sS --max-time 60 -b "${jar}" -c "${jar}" "$@"; }
csrf_of() { grep -o -m 1 'name="csrf_token" value="[^"]*"' | sed 's/.*value="//; s/"$//'; }
location_of() { grep -i '^location:' "$1" | tr -d '\r' | awk '{print $2}'; }

csrf="$(browser "${BASE_URL}/login" | csrf_of)"
[[ -n "${csrf}" ]] || fail "the sign-in page has no CSRF token"
code="$(browser -o /dev/null -w '%{http_code}' -d "csrf_token=${csrf}" \
  -d "username=${ADMIN_USER}" --data-urlencode "password=${ADMIN_PASSWORD}" "${BASE_URL}/login")"
[[ "${code}" == "303" ]] || fail "sign-in returned ${code}, expected 303"

# The worker reports, and the pages are quiet. The worker beats every 5 seconds.
worker_state() { api "${BASE_URL}/api/v1/system" | jq -r .worker.state; }
state="never"
for _ in $(seq 1 24); do
  state="$(worker_state)"
  [[ "${state}" == "running" ]] && break
  sleep 5
done
[[ "${state}" == "running" ]] || fail "the worker is not reporting (state '${state}')"
system_page="$(browser "${BASE_URL}/system")"
[[ "${system_page}" == *"Worker running"* ]] || fail "the System page does not say the worker runs"
[[ "${system_page}" != *'id="worker-banner"'* ]] || fail "the banner shows while the worker runs"
[[ "${system_page}" == *"expiry-reminders"* && "${system_page}" == *"retention-purge"* ]] \
  || fail "the System page does not list the default schedules"
code="$(curl -sS --max-time 30 -o /dev/null -w '%{http_code}' "${BASE_URL}/metrics")"
[[ "${code}" == "404" ]] || fail "/metrics returned ${code} without METRICS_TOKEN, expected 404"
code="$(curl -sS --max-time 30 -o /dev/null -w '%{http_code}' "${BASE_URL}/readyz")"
[[ "${code}" == "200" ]] || fail "/readyz returned ${code}"
echo "phase_10: the worker reports, the System page lists its schedules, /metrics is off"

# A client with the generic fixtures.
client_name="Phase 10 E2E Client"
code="$(api -o "${work}/client.json" -w '%{http_code}' -H 'Content-Type: application/json' \
  -d "{\"name\": \"${client_name}\"}" "${BASE_URL}/api/v1/clients")"
[[ "${code}" == "201" ]] || fail "creating the client returned ${code}: $(cat "${work}/client.json")"
client_id="$(jq -r .id "${work}/client.json")"
fixtures="${work}/fixtures"
(cd "${ROOT}" && python3 -m tools.make_generic_fixtures "${fixtures}" >/dev/null)
manifest="${fixtures}/manifest.json"
now_stamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
for name in $(jq -r '.files | keys[]' "${manifest}"); do
  source_code="$(jq -r --arg f "${name}" '.files[$f].source_code' "${manifest}")"
  code="$(api -o "${work}/upload.json" -w '%{http_code}' \
    -F "file=@${fixtures}/${name}" -F "source_code=${source_code}" -F "captured_at=${now_stamp}" \
    "${BASE_URL}/api/v1/clients/${client_id}/evidence")"
  [[ "${code}" == "201" ]] || fail "${name}: upload returned ${code}: $(cat "${work}/upload.json")"
done
echo "phase_10: client ${client_id} with six fixtures"

# Schedules through the API: add, list, remove; bad ones refused.
code="$(api -o "${work}/schedule.json" -w '%{http_code}' -H 'Content-Type: application/json' \
  -d "{\"kind\": \"dns-check\", \"cron\": \"0 4 1 1 *\", \"client_id\": ${client_id}, \"domains\": [\"client.example\"]}" \
  "${BASE_URL}/api/v1/schedules")"
[[ "${code}" == "201" ]] || fail "adding a schedule returned ${code}: $(cat "${work}/schedule.json")"
schedule_id="$(jq -r .id "${work}/schedule.json")"
listed="$(api "${BASE_URL}/api/v1/schedules" | jq -r --argjson id "${schedule_id}" '.schedules[] | select(.id == $id) | .kind')"
[[ "${listed}" == "dns-check" ]] || fail "the new schedule is not in the list"
for bad in '{"kind": "dns-check", "cron": "61 * * * *", "client_id": '"${client_id}"'}' \
           '{"kind": "mystery", "cron": "@daily"}' \
           '{"kind": "retention-purge", "cron": "@daily", "client_id": '"${client_id}"'}'; do
  code="$(api -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d "${bad}" "${BASE_URL}/api/v1/schedules")"
  [[ "${code}" == "422" ]] || fail "a bad schedule returned ${code}, expected 422: ${bad}"
done
code="$(api -o /dev/null -w '%{http_code}' -X DELETE "${BASE_URL}/api/v1/schedules/${schedule_id}")"
[[ "${code}" == "200" ]] || fail "removing the schedule returned ${code}"
echo "phase_10: a schedule added, listed and removed; bad ones refused (422)"

# A snapshot request: the worker builds it, once.
code="$(api -o "${work}/request.json" -w '%{http_code}' -X POST "${BASE_URL}/api/v1/clients/${client_id}/snapshot-requests")"
[[ "${code}" == "202" ]] || fail "the snapshot request returned ${code}: $(cat "${work}/request.json")"
snapshots="0"
for _ in $(seq 1 24); do
  snapshots="$(sql "SELECT count(*) FROM snapshot WHERE client_id = ${client_id}")"
  [[ "${snapshots}" != "0" ]] && break
  sleep 5
done
[[ "${snapshots}" == "1" ]] || fail "expected one snapshot built by the worker, found ${snapshots}"
sleep 12
snapshots="$(sql "SELECT count(*) FROM snapshot WHERE client_id = ${client_id}")"
[[ "${snapshots}" == "1" ]] || fail "the request ran again: ${snapshots} snapshots"
ran="$(sql "SELECT count(*) FROM audit_event WHERE action = 'snapshot.created' AND detail->>'client_id' = '${client_id}' AND detail->>'by' = 'worker'")"
[[ "${ran}" == "1" ]] || fail "expected one audit event of the worker snapshot, found ${ran}"
echo "phase_10: the worker built the requested snapshot once"

# The export: a zip with a CSV per table, no user name in it.
api -o "${work}/export.zip" "${BASE_URL}/api/v1/export" || fail "the export could not be read"
python3 - "${work}/export.zip" "${ADMIN_USER}" "${client_name}" <<'PY' || fail "the export is not what it should be"
import csv
import io
import sys
import zipfile

path, admin, client_name = sys.argv[1:4]
with zipfile.ZipFile(path) as archive:
    assert archive.testzip() is None
    names = set(archive.namelist())
    tables = {
        "clients", "evidence_items", "evidence_revisions", "facts", "snapshots",
        "control_results", "exceptions", "report_exports", "schedules",
        "audit_events", "evidence_log",
    }
    assert names == {f"{table}.csv" for table in tables} | {"manifest.csv", "README.txt"}, names
    files = {name: archive.read(name).decode("utf-8") for name in names}
manifest = {row["file"]: int(row["rows"]) for row in csv.DictReader(io.StringIO(files["manifest.csv"]))}
for table in tables:
    rows = list(csv.DictReader(io.StringIO(files[f"{table}.csv"], newline="")))
    assert manifest[f"{table}.csv"] == len(rows), table
assert client_name in files["clients.csv"]
assert admin not in "\n".join(files.values()), "the user name is in the export"
assert manifest["evidence_items.csv"] >= 6
print("the export holds", len(tables), "tables")
PY
echo "phase_10: the data export is a zip with a CSV file per table and no user name"

# Stopping the worker raises the banner within 3 minutes; starting it removes it.
docker stop --time 10 "${worker}" >/dev/null
stopped_at="$(date +%s)"
banner=""
for _ in $(seq 1 40); do
  page="$(browser "${BASE_URL}/clients")"
  if [[ "${page}" == *'id="worker-banner"'* ]]; then banner="yes"; break; fi
  sleep 5
done
elapsed=$(( $(date +%s) - stopped_at ))
[[ "${banner}" == "yes" ]] || fail "no banner ${elapsed} seconds after the worker stopped"
[[ "${elapsed}" -le 180 ]] || fail "the banner took ${elapsed} seconds to show, more than 3 minutes"
[[ "$(worker_state)" == "stale" ]] || fail "the API does not say the worker is stale"
system_page="$(browser "${BASE_URL}/system")"
[[ "${system_page}" == *"Worker not reporting"* ]] || fail "the System page does not say the worker stopped"
echo "phase_10: the banner showed ${elapsed} seconds after the worker stopped"
docker start "${worker}" >/dev/null
for _ in $(seq 1 24); do
  page="$(browser "${BASE_URL}/clients")"
  [[ "${page}" != *'id="worker-banner"'* && "$(worker_state)" == "running" ]] && break
  sleep 5
done
[[ "${page}" != *'id="worker-banner"'* ]] || fail "the banner is still there after the worker started again"
[[ "$(worker_state)" == "running" ]] || fail "the worker does not report after it started again"
echo "phase_10: the worker is back and the banner is gone"

# Delete the client from the System page.
system_page="$(browser "${BASE_URL}/system")"
csrf="$(csrf_of <<<"${system_page}")"
path="/system/clients/${client_id}/delete"
code="$(browser -o /dev/null -w '%{http_code}' --data-urlencode "confirm=${client_name}" "${BASE_URL}${path}")"
[[ "${code}" == "403" ]] || fail "a delete without a CSRF token returned ${code}, expected 403"
code="$(browser -o /dev/null -w '%{http_code}' -d "csrf_token=${csrf}" --data-urlencode "confirm=Phase 10" "${BASE_URL}${path}")"
[[ "${code}" == "422" ]] || fail "a delete with the wrong name returned ${code}, expected 422"
[[ "$(sql "SELECT count(*) FROM client WHERE id = ${client_id}")" == "1" ]] || fail "the client went with a wrong confirmation"
code="$(browser -o /dev/null -D "${work}/deleted.txt" -w '%{http_code}' -d "csrf_token=${csrf}" \
  --data-urlencode "confirm=${client_name}" "${BASE_URL}${path}")"
[[ "${code}" == "303" ]] || fail "the delete returned ${code}, expected 303"
[[ "$(location_of "${work}/deleted.txt")" == "/system?deleted=1" ]] || fail "unexpected redirect after the delete"
[[ "$(sql "SELECT count(*) FROM client WHERE id = ${client_id}")" == "0" ]] || fail "the client is still there"
for statement in \
  "SELECT count(*) FROM evidence_item WHERE client_id = ${client_id}" \
  "SELECT count(*) FROM snapshot WHERE client_id = ${client_id}" \
  "SELECT count(*) FROM schedule WHERE client_id = ${client_id}"; do
  left="$(sql "${statement}")"
  [[ "${left}" == "0" ]] || fail "${left} row(s) remain after the delete: ${statement}"
done
audited="$(sql "SELECT count(*) FROM audit_event WHERE action = 'client.deleted' AND target_id = '${client_id}'")"
[[ "${audited}" == "1" ]] || fail "expected one client.deleted audit event, found ${audited}"
docker exec "${web}" python -m app.cli verify-chain || fail "verify-chain failed after the delete"
echo "phase_10: the client was deleted from the System page and the deletion is audited"

echo "phase_10: OK"
