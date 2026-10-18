#!/usr/bin/env bash
# Phase 5 (part 1) end-to-end check against a running compose stack (check 9 runs it
# through tests/e2e/run.sh). Run with: bash scripts/e2e/phase_05.sh
#
# Proves, in the image that the stack runs:
#   - the application loads the control library through its own code
#     (python -m app.cli verify-controls): 51 controls, 8 domains, domain weights 100,
#     3 gates, 8 manual-only, and the two NIST reference datasets with their credit;
#   - the control file and the NIST datasets inside the image are byte for byte the
#     files of the repository (sha256), so the image does not carry another library;
#   - the JSON Schema is in the image and the file validates against it there;
#   - the unrelated sources still import: the web container answers /readyz.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_ROOT="/srv/revrook"

fail() { echo "::error::phase_05: FAIL: $*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker is not available"
command -v curl >/dev/null 2>&1 || fail "curl is not available"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is not available"

web="$(docker ps -q \
  --filter label=com.docker.compose.project=revrook \
  --filter label=com.docker.compose.service=web | head -n 1)"
[[ -n "${web}" ]] || fail "no compose web container found by label"

code="$(curl -sS --max-time 30 -o /dev/null -w '%{http_code}' "${BASE_URL}/readyz")"
[[ "${code}" == "200" ]] || fail "/readyz returned ${code}"

output="$(docker exec "${web}" python -m app.cli verify-controls)" \
  || fail "verify-controls failed in the image: ${output:-no output}"
echo "${output}"
expected='PC-RULES v0.1: 51 controls, 8 domains, domain weights 100, 3 gates (PC-ACC-01, PC-ACC-02, PC-BCK-01), 8 manual-only'
[[ "${output}" == *"${expected}"* ]] || fail "the control library line is not '${expected}'"
[[ "${output}" == *"nist-csf-2.0: 32 names"* ]] || fail "the CSF names were not loaded"
[[ "${output}" == *"nist-sp800-171r3: 26 names"* ]] || fail "the SP 800-171 names were not loaded"

for file in data/controls.yaml data/nist/nist-csf-2.0-names.json \
  data/nist/nist-sp800-171r3-names.json app/checks/controls.schema.json; do
  inside="$(docker exec "${web}" sha256sum "${APP_ROOT}/${file}" | cut -d' ' -f1)"
  outside="$(sha256sum "${ROOT}/${file}" | cut -d' ' -f1)"
  [[ -n "${inside}" && "${inside}" == "${outside}" ]] \
    || fail "${file} in the image (${inside}) is not the file of the repository (${outside})"
  echo "phase_05: ${file} is identical in the image"
done

# The same file, validated by the schema inside the image, and a broken copy refused.
docker exec -i "${web}" python - <<'PY'
from app.checks.library import (
    CONTROLS_PATH,
    SCHEMA_PATH,
    parse_yaml,
    validate_document,
)

assert SCHEMA_PATH.is_file(), "the schema is not in the image"
document = parse_yaml(CONTROLS_PATH.read_text(encoding="utf-8"))
assert validate_document(document) == [], "the control file does not validate"
document["controls"][0]["weight"] = 7
problems = validate_document(document)
assert any("controls/0/weight" in problem for problem in problems), problems
print("schema check in the image: ok")
PY

echo "phase_05: OK"
