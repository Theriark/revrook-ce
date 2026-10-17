#!/usr/bin/env bash
# Fails when the image holds a package that only requirements-dev.txt installs.
# Usage: bash scripts/check_image_packages.sh [IMAGE]   (default: revrook-ce:ci)
# Run from any directory; needs docker and both compiled lock files.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${1:-revrook-ce:ci}"

# Package names (lower case, dashes) pinned in a hashed lock file.
names() { grep -oE '^[A-Za-z0-9_.-]+==' "$1" | sed 's/==$//' | tr 'A-Z_' 'a-z-' | sort -u; }

installed="$(docker run --rm --entrypoint python "${IMAGE}" -m pip freeze | sed 's/==.*//' | tr 'A-Z_' 'a-z-' | sort -u)"
dev_only="$(comm -13 <(names "${ROOT}/requirements.txt") <(names "${ROOT}/requirements-dev.txt"))"
leaked="$(comm -12 <(echo "${installed}") <(echo "${dev_only}"))"

if [[ -n "${leaked}" ]]; then
  echo "check_image_packages: FAIL: development packages in ${IMAGE}:" >&2
  echo "${leaked}" >&2
  exit 1
fi
echo "check_image_packages: OK, $(echo "${dev_only}" | wc -l) development-only packages, none in ${IMAGE}"
