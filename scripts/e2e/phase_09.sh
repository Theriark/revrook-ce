#!/usr/bin/env bash
# Phase 9 end-to-end check against a running compose stack (check 9 runs it through
# tests/e2e/run.sh). Run with: bash scripts/e2e/phase_09.sh
#
# Proves, through the HTTP interface of the stack with synthetic files only, the whole
# flow of one client from signing in to an exported report:
#   - sign in with the form, add a client on the clients page, import the six generic
#     fixtures (one of them captured 100 days ago) through the API;
#   - pick a period on the overview, read the checklist (the filter shows only rows that
#     changed or need a look) and the evidence page (the old export is named in the list
#     of exports to refresh);
#   - autosave a note, set the MSP name, make the report, preview it (strict policy),
#     export the quarterly review and the insurance pack, read the export history and
#     download the kept copy (its SHA-256 equals the one in the history);
#   - a POST without the CSRF token is 403, a page without a session goes to the sign-in
#     page, another client's export is 404;
#   - deleting the client removes its drafts and exports.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
ADMIN_USER="phase09-admin"
ADMIN_PASSWORD="phase09-e2e-throwaway-password-0001"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

fail() { echo "::error::phase_09: FAIL: $*" >&2; exit 1; }

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
db="$(service_container db)"
[[ -n "${web}" ]] || fail "no compose web container found by label"
[[ -n "${db}" ]] || fail "no compose db container found by label"

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

sql() { docker exec "${db}" psql -U revrook -d revrook -tA -c "$1"; }

# A dedicated user whose password is known (an earlier phase made the first one) and an
# API token for it. The application's own functions do it inside the web container.
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
            print(await issue_api_token(session, user, "phase09-e2e"))
    finally:
        await engine.dispose()


asyncio.run(main())
PY
)"
[[ -n "${token}" ]] || fail "no API token was issued"
api() { curl -sS --max-time 60 -H "Authorization: Bearer ${token}" "$@"; }
who="$(api "${BASE_URL}/api/v1/whoami" | jq -r .username)"
[[ "${who}" == "${ADMIN_USER}" ]] || fail "the token does not work (whoami '${who}')"

# A browser session: the sign-in form, with its CSRF token, and a cookie jar.
jar="${work}/cookies.txt"
browser() { curl -sS --max-time 60 -b "${jar}" -c "${jar}" "$@"; }
csrf_of() { grep -o -m 1 'name="csrf_token" value="[^"]*"' | sed 's/.*value="//; s/"$//'; }
location_of() { grep -i '^location:' "$1" | tr -d '\r' | awk '{print $2}'; }

code="$(curl -sS --max-time 30 -o /dev/null -w '%{http_code}' "${BASE_URL}/clients")"
[[ "${code}" == "303" ]] || fail "/clients without a session returned ${code}, expected 303"
echo "phase_09: a page without a session goes to the sign-in page (303)"

csrf="$(browser "${BASE_URL}/login" | csrf_of)"
[[ -n "${csrf}" ]] || fail "the sign-in page has no CSRF token"
code="$(browser -o /dev/null -w '%{http_code}' -d "csrf_token=${csrf}" \
  -d "username=${ADMIN_USER}" --data-urlencode "password=${ADMIN_PASSWORD}" "${BASE_URL}/login")"
[[ "${code}" == "303" ]] || fail "sign-in returned ${code}, expected 303"
echo "phase_09: signed in with the form"

page="$(browser "${BASE_URL}/clients")"
[[ "${page}" == *"<title>Clients - revrook</title>"* ]] || fail "the clients page did not open"
csrf="$(csrf_of <<<"${page}")"

# POST without the CSRF token: refused.
code="$(browser -o /dev/null -w '%{http_code}' --data-urlencode "name=No Token Client" "${BASE_URL}/clients")"
[[ "${code}" == "403" ]] || fail "a client POST without a CSRF token returned ${code}, expected 403"
echo "phase_09: a POST without the CSRF token is 403"

# The flow starts: add the client on the clients page.
client_name="Phase 09 E2E Client"
code="$(browser -o /dev/null -D "${work}/created.txt" -w '%{http_code}' -d "csrf_token=${csrf}" \
  --data-urlencode "name=${client_name}" "${BASE_URL}/clients")"
[[ "${code}" == "303" ]] || fail "adding the client returned ${code}, expected 303"
client_id="$(location_of "${work}/created.txt" | sed 's#.*/##')"
[[ "${client_id}" =~ ^[0-9]+$ ]] || fail "no client id in the redirect"
echo "phase_09: client ${client_id} added on the clients page"

other_name="Phase 09 Other Client"
code="$(browser -o /dev/null -D "${work}/other.txt" -w '%{http_code}' -d "csrf_token=${csrf}" \
  --data-urlencode "name=${other_name}" "${BASE_URL}/clients")"
[[ "${code}" == "303" ]] || fail "adding the second client returned ${code}"
other_id="$(location_of "${work}/other.txt" | sed 's#.*/##')"
[[ "${other_id}" =~ ^[0-9]+$ ]] || fail "no id for the second client"

# Evidence: the six generic fixtures through the API. The backup export is captured 100
# days ago, so it is expired (twice the 35 days of an automatic export is 70 days).
fixtures="${work}/fixtures"
(cd "${ROOT}" && python3 -m tools.make_generic_fixtures "${fixtures}" >/dev/null)
manifest="${fixtures}/manifest.json"
[[ "$(jq '.files | length' "${manifest}")" == "6" ]] || fail "the manifest does not list six files"
now_stamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
old_stamp="$(date -u -d '100 days ago' +%Y-%m-%dT%H:%M:%SZ)"
for name in $(jq -r '.files | keys[]' "${manifest}"); do
  source_code="$(jq -r --arg f "${name}" '.files[$f].source_code' "${manifest}")"
  captured="${now_stamp}"
  if [[ "${source_code}" == "backup-export" ]]; then captured="${old_stamp}"; fi
  code="$(api -o "${work}/upload.json" -w '%{http_code}' \
    -F "file=@${fixtures}/${name}" -F "source_code=${source_code}" -F "captured_at=${captured}" \
    "${BASE_URL}/api/v1/clients/${client_id}/evidence")"
  [[ "${code}" == "201" ]] || fail "${name}: upload returned ${code}: $(cat "${work}/upload.json")"
done
echo "phase_09: six fixtures imported, the backup export captured 100 days ago"

# Period selection on the overview.
read -r period_start period_end < <(python3 - <<'PY'
from datetime import date, timedelta

today = date.today()
this_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
end = this_start - timedelta(days=1)
start = date(end.year, 3 * ((end.month - 1) // 3) + 1, 1)
print(start.isoformat(), end.isoformat())
PY
)
overview="$(browser "${BASE_URL}/clients/${client_id}?period_start=${period_start}&period_end=${period_end}")"
[[ "${overview}" == *'id="period-picker"'* ]] || fail "the overview has no period picker"
[[ "${overview}" == *"Period ${period_start} to ${period_end}"* ]] || fail "the overview does not show the period"
[[ "${overview}" == *'id="summary"'* && "${overview}" == *'id="freshness"'* ]] || fail "the overview has no summary or freshness table"
echo "phase_09: overview for ${period_start} to ${period_end}"

# The checklist: all 51 controls, and the filter keeps only rows that changed or need a look.
browser -o "${work}/checklist-all.html" "${BASE_URL}/clients/${client_id}/checklist"
all_rows="$(grep -c '<tr data-control=' "${work}/checklist-all.html" || true)"
[[ "${all_rows}" == "51" ]] || fail "the checklist shows ${all_rows} controls, expected 51"
code="$(browser -o "${work}/checklist-flagged.html" -w '%{http_code}' "${BASE_URL}/clients/${client_id}/checklist?show=flagged")"
[[ "${code}" == "200" ]] || fail "the filtered checklist returned ${code}"
quiet="$(grep -c 'data-changed="false" data-flagged="false"' "${work}/checklist-flagged.html" || true)"
[[ "${quiet}" == "0" ]] || fail "the filtered checklist shows ${quiet} rows that neither changed nor need a look"
shown="$(grep -c '<tr data-control=' "${work}/checklist-flagged.html" || true)"
[[ "${shown}" -le "${all_rows}" ]] || fail "the filter shows more rows than there are"
code="$(browser -o /dev/null -w '%{http_code}' "${BASE_URL}/clients/${client_id}/checklist?show=nonsense")"
[[ "${code}" == "422" ]] || fail "an unknown filter returned ${code}, expected 422"
echo "phase_09: checklist ${all_rows} controls, ${shown} after the filter"

# Every status is an icon plus words (never colour alone).
grep -q 'class="rv-status-icon" aria-hidden="true">[^<]*</span> Not checked' "${work}/checklist-all.html" \
  || grep -q 'class="rv-status-icon" aria-hidden="true">[^<]*</span> Protected' "${work}/checklist-all.html" \
  || fail "no status shows an icon followed by its words"

# The evidence page names the export to refresh.
evidence="$(browser "${BASE_URL}/clients/${client_id}/evidence")"
[[ "${evidence}" == *'id="refresh-list"'* ]] || fail "the evidence page has no refresh list"
[[ "${evidence}" == *"<strong>Backup jobs export</strong>"* ]] || fail "the old backup export is not named in the refresh list"
[[ "${evidence}" == *"Expired"* ]] || fail "the old export is not shown as expired"
echo "phase_09: the evidence page names the backup export to refresh"

# A control page, and an autosaved note (htmx: the CSRF token travels in a header).
control="PC-ACC-01"
code="$(browser -o "${work}/note.html" -w '%{http_code}' -H 'HX-Request: true' -H "X-CSRF-Token: ${csrf}" \
  --data-urlencode "did=Phase 09 e2e note" --data-urlencode "recommend=Enforce it" \
  "${BASE_URL}/clients/${client_id}/controls/${control}/note")"
[[ "${code}" == "200" ]] || fail "the autosave returned ${code}: $(cat "${work}/note.html")"
grep -q 'Saved at' "${work}/note.html" || fail "the autosave did not say it saved"
control_page="$(browser "${BASE_URL}/clients/${client_id}/controls/${control}")"
[[ "${control_page}" == *"Phase 09 e2e note"* ]] || fail "the saved note is not on the control page"
echo "phase_09: a note autosaved and read back"

# The control drawer: asked for with the drawer target, the control comes without its shell.
code="$(browser -o "${work}/drawer.html" -w '%{http_code}' -H 'HX-Request: true' -H 'HX-Target: control-drawer-body' \
  "${BASE_URL}/clients/${client_id}/controls/${control}")"
[[ "${code}" == "200" ]] || fail "the drawer request returned ${code}"
grep -q 'id="control-drawer-title"' "${work}/drawer.html" || fail "the drawer answer has no title"
grep -q 'Open as a page' "${work}/drawer.html" || fail "the drawer answer does not lead to the page"
! grep -q '<html' "${work}/drawer.html" || fail "the drawer answer is a whole page"
[[ "${control_page}" == *'id="control-drawer-title"'* ]] && fail "the control page carries the drawer title"
grep -q 'id="control-drawer"' "${work}/checklist-all.html" || fail "the checklist has no drawer"
echo "phase_09: the control drawer answers with the control without its shell"

# An exception, then the settings: the MSP name that goes on the cover.
review_date="$(date -u -d '+1 year' +%Y-%m-%d)"
code="$(browser -o /dev/null -w '%{http_code}' -d "csrf_token=${csrf}" -d "control_id=${control}" \
  --data-urlencode "owner=Office manager" --data-urlencode "reason=Accepted for the e2e test" \
  -d "review_date=${review_date}" "${BASE_URL}/clients/${client_id}/exceptions")"
[[ "${code}" == "303" ]] || fail "adding an exception returned ${code}, expected 303"
code="$(browser -o /dev/null -w '%{http_code}' -d "csrf_token=${csrf}" -d "control_id=${control}" \
  -d "owner=" -d "reason=" -d "review_date=not-a-date" "${BASE_URL}/clients/${client_id}/exceptions")"
[[ "${code}" == "422" ]] || fail "a bad exception returned ${code}, expected 422"
code="$(browser -o /dev/null -w '%{http_code}' -d "csrf_token=${csrf}" \
  --data-urlencode "msp_name=Phase 09 MSP" "${BASE_URL}/settings")"
[[ "${code}" == "303" ]] || fail "saving the settings returned ${code}, expected 303"
echo "phase_09: exception added, a bad one refused (422), MSP name saved"

# Make the report for the period, preview it and export both reports.
code="$(browser -o /dev/null -D "${work}/snapshot.txt" -w '%{http_code}' -d "csrf_token=${csrf}" \
  -d "period_start=${period_start}" -d "period_end=${period_end}" \
  "${BASE_URL}/clients/${client_id}/reports/snapshot")"
[[ "${code}" == "303" ]] || fail "making the report returned ${code}, expected 303"
report_path="$(location_of "${work}/snapshot.txt")"
[[ "${report_path}" =~ ^/clients/${client_id}/reports/[0-9]+$ ]] || fail "unexpected redirect '${report_path}'"
report="$(browser "${BASE_URL}${report_path}")"
[[ "${report}" == *"Preview and export"* ]] || fail "the report page did not open"
report_csrf="$(csrf_of <<<"${report}")"
if [[ "${report}" == *'class="rv-errors"'* ]]; then
  fail "the report cannot be exported: $(grep -o '<li>[^<]*</li>' <<<"${report}" | head -n 5)"
fi

for kind in qbr insurance; do
  code="$(browser -o "${work}/${kind}.html" -D "${work}/${kind}.txt" -w '%{http_code}' \
    "${BASE_URL}${report_path}/preview/${kind}")"
  [[ "${code}" == "200" ]] || fail "the ${kind} preview returned ${code}"
  grep -qi "^content-security-policy: default-src 'none'" "${work}/${kind}.txt" \
    || fail "the ${kind} preview has not got the strict policy"
  grep -q 'This report summarises security settings observed on the stated date.' "${work}/${kind}.html" \
    || fail "the ${kind} preview has no disclaimer"
  if grep -qi '<script' "${work}/${kind}.html"; then fail "the ${kind} preview has a script"; fi
done
code="$(browser -o /dev/null -w '%{http_code}' "${BASE_URL}${report_path}/preview/deck")"
[[ "${code}" == "404" ]] || fail "an unknown report kind returned ${code}, expected 404"

code="$(browser -o /dev/null -w '%{http_code}' -d "kind=qbr" "${BASE_URL}${report_path}/export")"
[[ "${code}" == "403" ]] || fail "an export POST without a CSRF token returned ${code}, expected 403"
code="$(browser -o /dev/null -w '%{http_code}' -d "csrf_token=${report_csrf}" -d "kind=deck" "${BASE_URL}${report_path}/export")"
[[ "${code}" == "422" ]] || fail "an export of an unknown kind returned ${code}, expected 422"

export_ids=()
for kind in qbr insurance; do
  code="$(browser -o /dev/null -D "${work}/export-${kind}.txt" -w '%{http_code}' -d "csrf_token=${report_csrf}" \
    -d "kind=${kind}" "${BASE_URL}${report_path}/export")"
  [[ "${code}" == "303" ]] || fail "exporting ${kind} returned ${code}, expected 303"
  export_ids+=("$(location_of "${work}/export-${kind}.txt" | sed 's#.*exported=##')")
done
echo "phase_09: both reports exported (ids ${export_ids[*]})"

# The history lists them with their hash, and the download is the kept copy.
history="$(browser "${BASE_URL}/clients/${client_id}/exports")"
for id in "${export_ids[@]}"; do
  [[ "${history}" == *"/exports/${id}/download"* ]] || fail "export ${id} is not in the history"
done
qbr_id="${export_ids[0]}"
code="$(browser -o "${work}/download.html" -D "${work}/download.txt" -w '%{http_code}' \
  "${BASE_URL}/clients/${client_id}/exports/${qbr_id}/download")"
[[ "${code}" == "200" ]] || fail "the download returned ${code}"
grep -qi '^content-disposition: attachment; filename="qbr-phase-09-e2e-client-' "${work}/download.txt" \
  || fail "the download is not an attachment with the expected name"
digest="$(sha256sum "${work}/download.html" | awk '{print $1}')"
[[ "${history}" == *"${digest}"* ]] || fail "the SHA-256 of the download is not the one in the history"
stored="$(sql "SELECT file_sha256 FROM report_export WHERE id = ${qbr_id}")"
[[ "${stored}" == "${digest}" ]] || fail "the stored hash ${stored} differs from the download ${digest}"
echo "phase_09: the download equals the kept copy (${digest})"

# Another client's address never gives this client's export.
code="$(browser -o /dev/null -w '%{http_code}' "${BASE_URL}/clients/${other_id}/exports/${qbr_id}/download")"
[[ "${code}" == "404" ]] || fail "another client's download address returned ${code}, expected 404"
echo "phase_09: an export of another client is 404"

# Glossary and settings open.
for path in /glossary /settings; do
  code="$(browser -o /dev/null -w '%{http_code}' "${BASE_URL}${path}")"
  [[ "${code}" == "200" ]] || fail "${path} returned ${code}"
done

# Deleting the client removes its drafts and exports.
drafts="$(sql "SELECT count(*) FROM setting WHERE key = 'draft:${client_id}'")"
[[ "${drafts}" == "1" ]] || fail "expected one draft row before the delete, found ${drafts}"
for entry in "${client_id}:${client_name}" "${other_id}:${other_name}"; do
  id="${entry%%:*}"
  name="${entry#*:}"
  code="$(api -o "${work}/delete.json" -w '%{http_code}' -X DELETE \
    "${BASE_URL}/api/v1/clients/${id}?confirm=${name// /%20}")"
  [[ "${code}" == "200" ]] || fail "delete of client ${id} returned ${code}: $(cat "${work}/delete.json")"
done
for statement in \
  "SELECT count(*) FROM setting WHERE key = 'draft:${client_id}'" \
  "SELECT count(*) FROM report_export WHERE client_id = ${client_id}" \
  "SELECT count(*) FROM snapshot WHERE client_id = ${client_id}" \
  "SELECT count(*) FROM exception_record WHERE client_id = ${client_id}"; do
  left="$(sql "${statement}")"
  [[ "${left}" == "0" ]] || fail "${left} row(s) remain after the delete: ${statement}"
done
docker exec "${web}" python -m app.cli verify-chain || fail "verify-chain failed after the delete"
code="$(browser -o /dev/null -w '%{http_code}' "${BASE_URL}/clients/${client_id}/exports/${qbr_id}/download")"
[[ "${code}" == "404" ]] || fail "the download after the delete returned ${code}, expected 404"

echo "phase_09: OK"
