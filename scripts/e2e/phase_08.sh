#!/usr/bin/env bash
# Phase 8 end-to-end check against a running compose stack. Run with:
#   bash scripts/e2e/phase_08.sh
#
# Proves, in the image that the stack runs:
#   - both reports render from a snapshot, every page has the disclaimer, a hostile
#     name is printed as text and a claim with no dated evidence blocks the export
#     (scripts/e2e/phase_08_check.py, run inside the web container);
# and measures the PDF spike on the runner (scripts/pdf-spike/measure.sh): image
# size, peak memory, render time and tags. The measurement only reports (see
# docs/pdf-spike.md); a problem in it is a warning and never fails the merge gate.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/../.." && pwd)"

fail() { echo "::error::phase_08: FAIL: $*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker is not available"
command -v curl >/dev/null 2>&1 || fail "curl is not available"

web="$(docker ps -q \
  --filter label=com.docker.compose.project=revrook \
  --filter label=com.docker.compose.service=web | head -n 1)"
[[ -n "${web}" ]] || fail "no compose web container found by label"

code="$(curl -sS --max-time 30 -o /dev/null -w '%{http_code}' "${BASE_URL}/readyz")"
[[ "${code}" == "200" ]] || fail "/readyz returned ${code}"

docker exec -i "${web}" python - < "${HERE}/phase_08_check.py" \
  || fail "the report check failed inside the image"

# The image ships no PDF library: the shipping format is HTML with a print stylesheet.
docker exec -i "${web}" python - <<'PY' || fail "a PDF library is present in the image"
import importlib.util

for name in ("weasyprint", "reportlab", "fpdf", "xhtml2pdf"):
    assert importlib.util.find_spec(name) is None, name
print("phase_08: the image holds no PDF library (HTML with a print stylesheet)")
PY

if bash "${ROOT}/scripts/pdf-spike/measure.sh" "${ROOT}"; then
  echo "phase_08: the PDF spike measurement finished"
else
  echo "::warning::phase_08: the PDF spike measurement did not finish (see the log)"
fi

echo "phase_08: OK"
