#!/usr/bin/env bash
# Backup and restore check against a running compose stack (docs/operations.md,
# "Checking that a backup restores"). Run with: bash scripts/restore_check.sh
#
# Does what the backup and restore guide does, into a second database that is dropped
# again, and fails when anything differs:
#   1. pg_dump -Fc of the database revrook;
#   2. pg_restore of the dump into the database revrook_restore_check;
#   3. the row count of every table is the same in both (a count of the live database
#      may lie between the count taken before and the count taken after the dump,
#      because the application keeps running);
#   4. the evidence folder is copied out of the web container; every file named in the
#      restored database is there with the SHA-256 of its name, and the copy equals the
#      folder;
#   5. verify-chain on the restored database prints the same chains, record counts and
#      head hashes as on the live database.
# It reads nothing of the live database except through pg_dump, verify-chain and
# SELECT count(*), and it removes the second database on the way out.
set -euo pipefail

RESTORE_DB="revrook_restore_check"

fail() { echo "::error::restore_check: FAIL: $*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker is not available"
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
cleanup() {
  docker exec "${db}" psql -U revrook -d postgres -q \
    -c "DROP DATABASE IF EXISTS ${RESTORE_DB}" >/dev/null 2>&1 || true
  rm -rf "${work}"
}
trap cleanup EXIT

sql_in() { docker exec "${db}" psql -U revrook -d "$1" -tA -c "$2"; }

live_url="$(docker exec "${web}" printenv DATABASE_URL)"
[[ -n "${live_url}" ]] || fail "the web container has no DATABASE_URL"
restore_url="${live_url%/*}/${RESTORE_DB}"

chains_of() { docker exec -e DATABASE_URL="$1" "${web}" python -m app.cli verify-chain; }

# The tables, and the count of each before the dump.
mapfile -t tables < <(sql_in revrook "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")
[[ "${#tables[@]}" -ge 10 ]] || fail "only ${#tables[@]} tables in the live database"
declare -A before after
for table in "${tables[@]}"; do
  before["${table}"]="$(sql_in revrook "SELECT count(*) FROM \"${table}\"")"
done
chains_before="$(chains_of "${live_url}")" || fail "verify-chain failed on the live database: ${chains_before}"

# 1. The dump. A custom format file, as in the guide.
docker exec "${db}" pg_dump -U revrook -d revrook -Fc > "${work}/revrook.dump"
[[ -s "${work}/revrook.dump" ]] || fail "pg_dump wrote an empty file"
echo "restore_check: dumped ${#tables[@]} tables ($(wc -c < "${work}/revrook.dump") bytes)"

# 2. The restore, into a second database.
docker exec "${db}" psql -U revrook -d postgres -q \
  -c "DROP DATABASE IF EXISTS ${RESTORE_DB}" -c "CREATE DATABASE ${RESTORE_DB}" >/dev/null
docker exec -i "${db}" pg_restore -U revrook -d "${RESTORE_DB}" --no-owner --exit-on-error \
  < "${work}/revrook.dump" || fail "pg_restore failed"
echo "restore_check: restored into ${RESTORE_DB}"

# 3. The same tables, and the same number of rows in each.
mapfile -t restored_tables < <(sql_in "${RESTORE_DB}" "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")
[[ "${tables[*]}" == "${restored_tables[*]}" ]] || fail "the restored database has other tables: ${restored_tables[*]}"
for table in "${tables[@]}"; do
  after["${table}"]="$(sql_in revrook "SELECT count(*) FROM \"${table}\"")"
done
total=0
for table in "${tables[@]}"; do
  restored="$(sql_in "${RESTORE_DB}" "SELECT count(*) FROM \"${table}\"")"
  low="${before[${table}]}"
  high="${after[${table}]}"
  if (( low > high )); then low="${after[${table}]}"; high="${before[${table}]}"; fi
  if (( restored < low || restored > high )); then
    fail "table ${table}: ${restored} rows after the restore, ${before[${table}]} before and ${after[${table}]} after the dump"
  fi
  total=$(( total + restored ))
done
echo "restore_check: ${#tables[@]} tables restored with equal row counts (${total} rows)"

# 4. The evidence folder, copied as the guide does, and every kept file checked.
mkdir -p "${work}/evidence"
docker cp "${web}:/data/evidence/." "${work}/evidence" || fail "the evidence folder could not be copied"
missing=0
checked=0
while IFS= read -r key; do
  [[ -n "${key}" ]] || continue
  file="${work}/evidence/${key}"
  [[ -f "${file}" ]] || { echo "restore_check: missing file ${key}" >&2; missing=$(( missing + 1 )); continue; }
  digest="$(sha256sum "${file}" | cut -d' ' -f1)"
  [[ "${digest}" == "${key##*/}" ]] || { echo "restore_check: the content of ${key} is not its name" >&2; missing=$(( missing + 1 )); continue; }
  checked=$(( checked + 1 ))
done < <(sql_in "${RESTORE_DB}" "SELECT storage_key FROM evidence_revision WHERE storage_key IS NOT NULL UNION SELECT storage_key FROM report_export ORDER BY 1")
[[ "${missing}" == "0" ]] || fail "${missing} kept files are missing or damaged in the copy"
copy_list="$(cd "${work}/evidence" && find . -type f | LC_ALL=C sort | xargs -r -d '\n' sha256sum)"
live_list="$(docker exec "${web}" sh -c "cd /data/evidence && find . -type f | LC_ALL=C sort | xargs -r -d '\n' sha256sum")"
[[ "${copy_list}" == "${live_list}" ]] || fail "the copy of the evidence folder differs from the folder"
echo "restore_check: evidence folder copied, ${checked} kept files found with their hashes"

# 5. The hash chains of the restored database, against the live ones.
chains_restored="$(chains_of "${restore_url}")" || fail "verify-chain failed on the restored database: ${chains_restored}"
chains_after="$(chains_of "${live_url}")" || fail "verify-chain failed on the live database: ${chains_after}"
if [[ "${chains_restored}" != "${chains_before}" && "${chains_restored}" != "${chains_after}" ]]; then
  echo "live:     ${chains_before}" >&2
  echo "restored: ${chains_restored}" >&2
  fail "the restored hash chains differ from the live ones"
fi
echo "restore_check: $(tail -n 1 <<<"${chains_restored}")"
echo "restore_check: OK, the restored database has the same rows, files and verified hash chains"
