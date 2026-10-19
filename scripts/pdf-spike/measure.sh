#!/usr/bin/env bash
# PDF spike measurement (phase 8, step 1). Opt-in: scripts/e2e/phase_08.sh runs it only
# when RUN_PDF_SPIKE=1 is set (it takes minutes and installs unpinned packages, so the
# merge gate does not run it). By hand:
#   bash scripts/pdf-spike/measure.sh <repository root>
#
# Builds a THROWAWAY image (python:3.12-slim plus WeasyPrint, Pango and a font; it is
# never pushed and never part of the product image), renders the real golden reports
# to PDF in it and prints, one per line:
#   SPIKE size_base_mb=... size_spike_mb=... size_increase_mb=...
#   SPIKE peak_ram_mb=... (docker stats sampled every second)
#   SPIKE render_seconds=...
#   SPIKE pages=... tagged=... disclaimer_on_every_page=...
#   SPIKE gates size=... ram=... time=... tagged=...   (the gates of docs/pdf-spike.md)
# Nothing here changes the product: the gates only report. The licence and font
# gates are read by hand (docs/pdf-spike.md) and are not measured here.
set -uo pipefail

ROOT="${1:?usage: measure.sh <repository root>}"
BASE_IMAGE="python:3.12-slim"
SPIKE_IMAGE="revrook-pdf-spike:local"
NAME="revrook-pdf-spike"
WORK="$(mktemp -d)"
trap 'docker rm -f "${NAME}" >/dev/null 2>&1; rm -rf "${WORK}"' EXIT

size_mb() { docker image inspect -f '{{.Size}}' "$1" | awk '{printf "%.1f", $1 / 1048576}'; }

docker pull -q "${BASE_IMAGE}" >/dev/null 2>&1 || true
base_mb="$(size_mb "${BASE_IMAGE}")" || { echo "SPIKE not-measured: no base image"; exit 1; }

cat > "${WORK}/Dockerfile" <<'EOF'
FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 fonts-noto-core \
 && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir weasyprint pypdf
EOF

cat > "${WORK}/render.py" <<'EOF'
import glob
import re
import sys
import time

from pypdf import PdfReader
from weasyprint import HTML

DISCLAIMER_START = "This report summarises security settings observed on the stated date."
started = time.time()
pages = tagged = covered = 0
for path in sorted(glob.glob("/in/*.html")):
    target = "/tmp/" + path.rsplit("/", 1)[-1] + ".pdf"
    try:
        HTML(filename=path).write_pdf(target, pdf_variant="pdf/ua-1")
    except Exception:
        HTML(filename=path).write_pdf(target)
    raw = open(target, "rb").read()
    tagged += int(b"/StructTreeRoot" in raw and b"/MarkInfo" in raw)
    reader = PdfReader(target)
    for page in reader.pages:
        pages += 1
        text = re.sub(r"\s+", " ", page.extract_text() or "")
        covered += int(DISCLAIMER_START in text)
print(f"RENDERED files={len(glob.glob('/in/*.html'))} pages={pages} tagged_files={tagged} "
      f"disclaimer_pages={covered} seconds={time.time() - started:.1f}")
sys.stdout.flush()
EOF

docker build -q -t "${SPIKE_IMAGE}" "${WORK}" >"${WORK}/build.log" 2>&1 \
  || { echo "SPIKE not-measured: the throwaway image did not build"; tail -n 5 "${WORK}/build.log"; exit 1; }
spike_mb="$(size_mb "${SPIKE_IMAGE}")"
increase_mb="$(awk -v a="${spike_mb}" -v b="${base_mb}" 'BEGIN {printf "%.1f", a - b}')"
echo "SPIKE size_base_mb=${base_mb} size_spike_mb=${spike_mb} size_increase_mb=${increase_mb}"

start="$(date +%s.%N)"
docker run -d --name "${NAME}" --memory 1g \
  -v "${ROOT}/tests/golden/reports:/in:ro" \
  -v "${WORK}/render.py:/render.py:ro" \
  "${SPIKE_IMAGE}" python /render.py >/dev/null || { echo "SPIKE not-measured: the render did not start"; exit 1; }

peak=0
while [[ "$(docker inspect -f '{{.State.Running}}' "${NAME}" 2>/dev/null)" == "true" ]]; do
  used="$(docker stats --no-stream --format '{{.MemUsage}}' "${NAME}" 2>/dev/null | awk '{print $1}')"
  mb="$(echo "${used}" | awk '/GiB/ {sub(/GiB/, ""); printf "%.1f", $1 * 1024; next} /MiB/ {sub(/MiB/, ""); printf "%.1f", $1; next} /kiB|KiB/ {printf "0"; next} {printf "0"}')"
  if awk -v a="${mb:-0}" -v b="${peak}" 'BEGIN {exit !(a > b)}'; then peak="${mb}"; fi
  sleep 1
done
end="$(date +%s.%N)"
seconds="$(awk -v a="${start}" -v b="${end}" 'BEGIN {printf "%.1f", b - a}')"
result="$(docker logs "${NAME}" 2>&1 | grep '^RENDERED' | tail -n 1)"
echo "SPIKE peak_ram_mb=${peak}"
echo "SPIKE render_seconds=${seconds}"
echo "SPIKE ${result:-render-failed}"

tagged_files="$(echo "${result}" | sed -n 's/.* tagged_files=\([0-9]*\).*/\1/p')"
files="$(echo "${result}" | sed -n 's/.* files=\([0-9]*\).*/\1/p')"
gate() { awk -v v="$1" -v limit="$2" 'BEGIN {print ((v + 0 < limit + 0) ? "pass" : "FAIL")}'; }
tagged_gate="FAIL"
if [[ -n "${files}" && "${files}" != "0" && "${tagged_files}" == "${files}" ]]; then tagged_gate="pass"; fi
echo "SPIKE gates size=$(gate "${increase_mb}" 250) ram=$(gate "${peak}" 400) time=$(gate "${seconds}" 30) tagged=${tagged_gate}"
