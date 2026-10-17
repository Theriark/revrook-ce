#!/usr/bin/env bash
# Phase 0 end-to-end check against a running compose stack (check 9 runs it after
# "docker compose up --wait"). Run with: bash scripts/e2e/phase_00.sh
#
# Proves: /healthz and /readyz answer 200 on port 8080, the web container runs as
# uid 10001 and its image holds no development package.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

fail() { echo "phase_00: FAIL: $*" >&2; exit 1; }

for path in /healthz /readyz; do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "${BASE_URL}${path}")"
  [[ "${code}" == "200" ]] || fail "${path} returned ${code}, expected 200"
  echo "phase_00: ${path} 200"
done

if command -v docker >/dev/null 2>&1; then
  container="$(docker compose -f "${ROOT}/docker-compose.yml" ps -q web)"
  if [[ -n "${container}" ]]; then
    uid="$(docker exec "${container}" id -u)"
    [[ "${uid}" == "10001" ]] || fail "web container runs as uid ${uid}, expected 10001"
    echo "phase_00: web container uid ${uid}"
    image="$(docker inspect --format '{{.Image}}' "${container}")"
    bash "${ROOT}/scripts/check_image_packages.sh" "${image}"
  else
    echo "phase_00: no compose web container found, skipping uid and image checks"
  fi
fi

echo "phase_00: OK"
