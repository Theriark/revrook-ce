#!/usr/bin/env bash
# Loads synthetic demo data into a running revrook stack: one client and the six
# example files of tools/make_generic_fixtures.py, captured now, so that a new
# installation has something to look at (docs/quick-start.md).
#
# Run from the repository root with the stack up:
#
#   bash scripts/demo.sh USERNAME
#
# USERNAME is the account you made on the first-run page (/setup). The script asks the
# web container for an API token for that account and keeps it only in a shell variable;
# the token is never printed. It is stored, though: each run leaves one API credential
# named "demo data" (as a hash) on the account, and it stays after the demo client is
# deleted (docs/quick-start.md, step 6). The script then makes the client through the
# API and uploads the six files. Everything in the files is invented: no real customer,
# tenant, device or person.
#
# Needs docker, curl, jq and Python 3.11 or newer on this machine (the file generator
# uses only the standard library). BASE_URL (default http://localhost:8080),
# COMPOSE_PROJECT (default revrook) and DEMO_CLIENT_NAME can be set in the environment.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
PROJECT="${COMPOSE_PROJECT:-revrook}"
CLIENT_NAME="${DEMO_CLIENT_NAME:-Demo Client (synthetic data)}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() { echo "demo: $*" >&2; exit 1; }

user="${1:-}"
[[ -n "${user}" ]] || fail "usage: bash scripts/demo.sh USERNAME (the account made on /setup)"

for tool in docker curl jq python3; do
  command -v "${tool}" >/dev/null 2>&1 || fail "${tool} is not installed"
done

web="$(docker ps -q \
  --filter label=com.docker.compose.project="${PROJECT}" \
  --filter label=com.docker.compose.service=web | head -n 1)"
[[ -n "${web}" ]] || fail "no running web container of the compose project '${PROJECT}'; start it with: docker compose up --build --wait"

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

# An API token for the account, made by the application's own function inside the web
# container. It is shown once, here, and kept only in this shell variable.
token="$(docker exec -i -e DEMO_USER="${user}" "${web}" python - <<'PY' | tail -n 1
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth import issue_api_token
from app.db import make_engine
from app.models import AppUser
from app.settings import load_settings


async def main() -> None:
    engine = make_engine(load_settings().database_url)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            found = await session.execute(
                select(AppUser).where(AppUser.username == os.environ["DEMO_USER"])
            )
            user = found.scalar_one_or_none()
            if user is None:
                raise SystemExit("there is no account named " + os.environ["DEMO_USER"])
            print(await issue_api_token(session, user, "demo data"))
    finally:
        await engine.dispose()


asyncio.run(main())
PY
)" || fail "could not make an API token for '${user}'; use the name of the account made on /setup"
[[ -n "${token}" ]] || fail "no API token was made"
api() { curl -sS --max-time 60 -H "Authorization: Bearer ${token}" "$@"; }

who="$(api "${BASE_URL}/api/v1/whoami" | jq -r '.username // empty')"
[[ "${who}" == "${user}" ]] || fail "the web interface at ${BASE_URL} did not accept the token"

code="$(api -o "${work}/client.json" -w '%{http_code}' -H 'Content-Type: application/json' \
  -d "$(jq -n --arg name "${CLIENT_NAME}" '{name: $name}')" "${BASE_URL}/api/v1/clients")"
[[ "${code}" == "201" ]] || fail "making the client returned ${code}: $(cat "${work}/client.json")"
client_id="$(jq -r .id "${work}/client.json")"
[[ "${client_id}" =~ ^[0-9]+$ ]] || fail "the answer holds no client id"
echo "demo: client ${client_id} made"

fixtures="${work}/fixtures"
(cd "${ROOT}" && python3 -m tools.make_generic_fixtures "${fixtures}" >/dev/null) \
  || fail "the example files could not be made (Python 3.11 or newer is needed)"
manifest="${fixtures}/manifest.json"
[[ "$(jq '.files | length' "${manifest}")" == "6" ]] || fail "the manifest does not list six files"

captured="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
for name in $(jq -r '.files | keys[]' "${manifest}"); do
  source_code="$(jq -r --arg f "${name}" '.files[$f].source_code' "${manifest}")"
  code="$(api -o "${work}/upload.json" -w '%{http_code}' \
    -F "file=@${fixtures}/${name}" -F "source_code=${source_code}" \
    -F "captured_at=${captured}" "${BASE_URL}/api/v1/clients/${client_id}/evidence")"
  [[ "${code}" == "201" ]] || fail "${name}: the upload returned ${code}: $(cat "${work}/upload.json")"
  echo "demo: ${source_code} imported"
done

echo
echo "Demo data is in. Open ${BASE_URL}/clients/${client_id} and sign in."
echo "Then choose Reports, make the report for the last full quarter and export it."
echo "DEMO_CLIENT_ID=${client_id}"
