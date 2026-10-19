#!/usr/bin/env bash
# Phase 11 end-to-end check against a running compose stack (check 9 runs it through
# tests/e2e/run.sh). Run with: bash scripts/e2e/phase_11.sh
#
# Runs the quick start of docs/quick-start.md with synthetic files only, and times it:
#   - scripts/demo.sh makes a demo client and uploads the six example files, and
#     refuses an account that does not exist;
#   - the client has six evidence items, and the checklist shows all 51 controls;
#   - the report of the last full quarter is made, previewed (strict policy) and the
#     quarterly review is exported, and its download equals the kept copy;
#   - the whole flow takes under 10 minutes (the acceptance check of the quick start);
#   - the demo client is deleted again.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
ADMIN_USER="phase11-admin"
ADMIN_PASSWORD="phase11-e2e-throwaway-password-0001"
CLIENT_NAME="Phase 11 Demo Client"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LIMIT_SECONDS=600

fail() { echo "::error::phase_11: FAIL: $*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker is not available"
command -v curl >/dev/null 2>&1 || fail "curl is not available"
command -v jq >/dev/null 2>&1 || fail "jq is not available"
command -v python3 >/dev/null 2>&1 || fail "python3 is not available"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is not available"

service_container() {
  docker ps -q \
    --filter label=com.docker.compose.project=revrook \
    --filter label=com.docker.compose.service="$1" | head -n 1
}
web="$(service_container web)"
[[ -n "${web}" ]] || fail "no compose web container found by label"

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT
SECONDS=0

# A dedicated account whose password is known (the quick start makes the first one on
# the /setup page), and an API token for it, to delete the demo client at the end.
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
            print(await issue_api_token(session, user, "phase11-e2e"))
    finally:
        await engine.dispose()


asyncio.run(main())
PY
)"
[[ -n "${token}" ]] || fail "no API token was issued"
api() { curl -sS --max-time 60 -H "Authorization: Bearer ${token}" "$@"; }
who="$(api "${BASE_URL}/api/v1/whoami" | jq -r .username)"
[[ "${who}" == "${ADMIN_USER}" ]] || fail "the token does not work (whoami '${who}')"

# 1. The demo script: an unknown account is refused, the right one gets a client.
if bash "${ROOT}/scripts/demo.sh" "no-such-account-phase-11" >"${work}/refused.txt" 2>&1; then
  fail "scripts/demo.sh accepted an account that does not exist"
fi
grep -q "no account named\|could not make an API token" "${work}/refused.txt" \
  || fail "scripts/demo.sh gave no reason for refusing the unknown account: $(cat "${work}/refused.txt")"
echo "phase_11: the demo script refuses an unknown account"

DEMO_CLIENT_NAME="${CLIENT_NAME}" bash "${ROOT}/scripts/demo.sh" "${ADMIN_USER}" >"${work}/demo.txt" \
  || fail "scripts/demo.sh failed: $(cat "${work}/demo.txt")"
client_id="$(sed -n 's/^DEMO_CLIENT_ID=//p' "${work}/demo.txt")"
[[ "${client_id}" =~ ^[0-9]+$ ]] || fail "the demo script printed no client id"
items="$(api "${BASE_URL}/api/v1/clients/${client_id}/evidence" | jq '.items | length')"
[[ "${items}" == "6" ]] || fail "the demo client has ${items} evidence items, expected 6"
echo "phase_11: the demo script made client ${client_id} with six evidence items"

# 2. The browser part of the quick start: sign in, open the client, read the checklist.
jar="${work}/cookies.txt"
browser() { curl -sS --max-time 60 -b "${jar}" -c "${jar}" "$@"; }
csrf_of() { grep -o -m 1 'name="csrf_token" value="[^"]*"' | sed 's/.*value="//; s/"$//'; }
location_of() { grep -i '^location:' "$1" | tr -d '\r' | awk '{print $2}'; }

csrf="$(browser "${BASE_URL}/login" | csrf_of)"
[[ -n "${csrf}" ]] || fail "the sign-in page has no CSRF token"
code="$(browser -o /dev/null -w '%{http_code}' -d "csrf_token=${csrf}" \
  -d "username=${ADMIN_USER}" --data-urlencode "password=${ADMIN_PASSWORD}" "${BASE_URL}/login")"
[[ "${code}" == "303" ]] || fail "sign-in returned ${code}, expected 303"

clients="$(browser "${BASE_URL}/clients")"
[[ "${clients}" == *"${CLIENT_NAME}"* ]] || fail "the clients page does not list the demo client"
csrf="$(csrf_of <<<"${clients}")"
[[ -n "${csrf}" ]] || fail "the clients page has no CSRF token"
# The report names the MSP on its cover, so the export needs the name from Settings.
code="$(browser -o /dev/null -w '%{http_code}' -d "csrf_token=${csrf}" \
  --data-urlencode "msp_name=Phase 11 MSP" "${BASE_URL}/settings")"
[[ "${code}" == "303" ]] || fail "saving the settings returned ${code}, expected 303"
overview="$(browser "${BASE_URL}/clients/${client_id}")"
[[ "${overview}" == *'id="summary"'* ]] || fail "the client overview did not open"
browser -o "${work}/checklist.html" "${BASE_URL}/clients/${client_id}/checklist"
rows="$(grep -c '<tr data-control=' "${work}/checklist.html" || true)"
[[ "${rows}" == "51" ]] || fail "the checklist shows ${rows} controls, expected 51"
echo "phase_11: the overview opens and the checklist shows ${rows} controls"

# 3. The report of the last full quarter: make it, preview it, export the review.
read -r period_start period_end < <(python3 - <<'PY'
from datetime import date, timedelta

today = date.today()
this_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
end = this_start - timedelta(days=1)
start = date(end.year, 3 * ((end.month - 1) // 3) + 1, 1)
print(start.isoformat(), end.isoformat())
PY
)
code="$(browser -o /dev/null -D "${work}/snapshot.txt" -w '%{http_code}' -d "csrf_token=${csrf}" \
  -d "period_start=${period_start}" -d "period_end=${period_end}" \
  "${BASE_URL}/clients/${client_id}/reports/snapshot")"
[[ "${code}" == "303" ]] || fail "making the report returned ${code}, expected 303"
report_path="$(location_of "${work}/snapshot.txt")"
[[ "${report_path}" =~ ^/clients/${client_id}/reports/[0-9]+$ ]] || fail "unexpected redirect '${report_path}'"
report="$(browser "${BASE_URL}${report_path}")"
[[ "${report}" == *"Preview and export"* ]] || fail "the report page did not open"
if [[ "${report}" == *'class="rv-errors"'* ]]; then
  fail "the report cannot be exported: $(grep -o '<li>[^<]*</li>' <<<"${report}" | head -n 5)"
fi
report_csrf="$(csrf_of <<<"${report}")"

for kind in qbr insurance; do
  code="$(browser -o "${work}/${kind}.html" -D "${work}/${kind}.txt" -w '%{http_code}' \
    "${BASE_URL}${report_path}/preview/${kind}")"
  [[ "${code}" == "200" ]] || fail "the ${kind} preview returned ${code}"
  grep -qi "^content-security-policy: default-src 'none'" "${work}/${kind}.txt" \
    || fail "the ${kind} preview has not got the strict policy"
  grep -q 'This report summarises security settings observed on the stated date.' "${work}/${kind}.html" \
    || fail "the ${kind} preview has no disclaimer"
done

code="$(browser -o /dev/null -D "${work}/export.txt" -w '%{http_code}' -d "csrf_token=${report_csrf}" \
  -d "kind=qbr" "${BASE_URL}${report_path}/export")"
[[ "${code}" == "303" ]] || fail "exporting the review returned ${code}, expected 303"
export_id="$(location_of "${work}/export.txt" | sed 's#.*exported=##')"
[[ "${export_id}" =~ ^[0-9]+$ ]] || fail "no export id in the redirect"
code="$(browser -o "${work}/download.html" -w '%{http_code}' \
  "${BASE_URL}/clients/${client_id}/exports/${export_id}/download")"
[[ "${code}" == "200" ]] || fail "the download returned ${code}"
digest="$(sha256sum "${work}/download.html" | awk '{print $1}')"
history="$(browser "${BASE_URL}/clients/${client_id}/exports")"
[[ "${history}" == *"${digest}"* ]] || fail "the SHA-256 of the download is not the one in the history"
echo "phase_11: the review of ${period_start} to ${period_end} is exported (${digest})"

# 4. The whole flow is quick, and the demo client goes again.
[[ "${SECONDS}" -lt "${LIMIT_SECONDS}" ]] || fail "the quick start took ${SECONDS} seconds, over ${LIMIT_SECONDS}"
code="$(api -o "${work}/delete.json" -w '%{http_code}' -G -X DELETE \
  --data-urlencode "confirm=${CLIENT_NAME}" "${BASE_URL}/api/v1/clients/${client_id}")"
[[ "${code}" == "200" ]] || fail "deleting the demo client returned ${code}: $(cat "${work}/delete.json")"
code="$(browser -o /dev/null -w '%{http_code}' "${BASE_URL}/clients/${client_id}/exports/${export_id}/download")"
[[ "${code}" == "404" ]] || fail "the download after the delete returned ${code}, expected 404"
docker exec "${web}" python -m app.cli verify-chain || fail "verify-chain failed after the delete"

echo "phase_11: OK (${SECONDS} seconds)"
