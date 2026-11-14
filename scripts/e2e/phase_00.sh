#!/usr/bin/env bash
# Phase 0 end-to-end check against a running compose stack (check 9 runs it after
# "docker compose up --wait"). Run with: bash scripts/e2e/phase_00.sh
#
# Proves: /healthz and /readyz answer 200 on port 8080, the web container runs as
# uid 10001, its image holds no development package and it prints a report to PDF.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# "::error::" makes GitHub Actions show the message as an annotation, so the
# failure reason is visible in the CI summary and in ci_logs.
fail() { echo "::error::phase_00: FAIL: $*" >&2; exit 1; }

for path in /healthz /readyz; do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "${BASE_URL}${path}" || echo curl-failed)"
  [[ "${code}" == "200" ]] || fail "${path} returned ${code}, expected 200"
  echo "phase_00: ${path} 200"
done

# In CI (CI=true) the uid and image checks are mandatory: a missing docker or a
# compose label that drifted must fail the run, not skip silently.
strict="${CI:-}"

if ! command -v docker >/dev/null 2>&1; then
  if [[ "${strict}" == "true" ]]; then
    fail "docker is not available in CI, so the uid and image checks cannot run"
  fi
  echo "phase_00: docker not found, skipping uid and image checks (outside CI)"
else
  # Compose labels avoid "docker compose ps", which would need the env file.
  container="$(docker ps -q \
    --filter label=com.docker.compose.project=revrook \
    --filter label=com.docker.compose.service=web | head -n 1)"
  if [[ -n "${container}" ]]; then
    uid="$(docker exec "${container}" id -u)" || fail "docker exec id -u failed"
    [[ "${uid}" == "10001" ]] || fail "web container runs as uid ${uid}, expected 10001"
    echo "phase_00: web container uid ${uid}"
    image="$(docker inspect --format '{{.Image}}' "${container}")"
    bash "${ROOT}/scripts/check_image_packages.sh" "${image}" || fail "image package check failed (see lines above)"
    # The browser of the image prints a report (app/reports/pdf.py), inside the
    # running container: read-only root, /tmp as tmpfs, uid 10001. The golden
    # review goes in as HTML and must come out as a PDF.
    pdf="$(mktemp)"
    docker exec -i "${container}" python -m app.reports.pdf \
      < "${ROOT}/tests/golden/reports/qbr-client-a.html" > "${pdf}" \
      || fail "the container could not print a report to PDF"
    [[ "$(head -c 5 "${pdf}")" == "%PDF-" ]] || fail "what the container printed is not a PDF"
    size="$(wc -c < "${pdf}")"
    [[ "${size}" -gt 100000 ]] || fail "the printed report is only ${size} bytes"
    # A4 sheets, as the print stylesheet asks (not the paper of the browser), and
    # the whole report, not one sheet.
    grep -a -q '/MediaBox \[0 0 59[45]' "${pdf}" || fail "the printed report is not on A4 sheets"
    sheets="$(grep -a -c '/Type /Page$' "${pdf}" || true)"
    [[ "${sheets}" -ge 10 ]] || fail "the printed report has ${sheets} sheets, expected the whole review"
    echo "phase_00: a report prints to a PDF of ${size} bytes, ${sheets} A4 sheets"
    rm -f "${pdf}"
  elif [[ "${strict}" == "true" ]]; then
    fail "no compose web container found by label (project revrook, service web) in CI"
  else
    echo "phase_00: no compose web container found, skipping uid and image checks (outside CI)"
  fi
fi

echo "phase_00: OK"
