#!/usr/bin/env bash
# End-to-end scripts after phase 0, run by CI check 9 against the compose stack.
# The workflow files stay unchanged: they call this one file, and each phase adds
# its script here. Run with: bash tests/e2e/run.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

bash "${ROOT}/scripts/e2e/phase_02.sh"
bash "${ROOT}/scripts/e2e/phase_03.sh"
bash "${ROOT}/scripts/e2e/phase_04.sh"
bash "${ROOT}/scripts/e2e/phase_05.sh"
