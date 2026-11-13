"""The Google Cloud export script (app/static/scripts/export-gcp.sh).

The script runs against a fake `gcloud` that answers like value() output; the files it
writes are then read by revrook's own importers.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.importers.generic import ADAPTERS

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "app" / "static" / "scripts" / "export-gcp.sh"
BY_CODE = {adapter.source_code: adapter for adapter in ADAPTERS}
BASH = shutil.which("bash")

# Tab-separated answers, in the column order of each --format of the script. Project
# p2 has no Compute Engine API and must be skipped without a compute call.
FAKE_GCLOUD = r"""#!/usr/bin/env bash
case "$1 $2" in
  "projects list") printf '%s\n' p1 p2 ;;
  "services list") case "$*" in *"--project p1"*) echo compute.googleapis.com ;; esac ;;
  "compute firewall-rules")
    case "$*" in *"--project p2"*) echo "compute call for p2" >&2; exit 1 ;; esac
    printf '%s\n' \
    $'ssh\tFalse\t0.0.0.0/0\ttcp:22,tcp:8000-8100\t' \
    $'internal\tFalse\t10.128.0.0/9\tall\t' \
    $'tagged\tFalse\t\ttcp:443\t' \
    $'old\tTrue\t0.0.0.0/0\ticmp\t' \
    $'block\tFalse\t0.0.0.0/0\t\tudp:53' ;;
  "compute instances") printf '%s\n' \
    $'web\teurope-west1-b\tdebian-12-bookworm' \
    $'dc\teurope-west1-b\twindows-server-2022-dc' ;;
  "compute snapshots") printf '%s\n' \
    $'disk-a\tdaily\tCREATING\t2026-11-13T05:00:00Z' \
    $'disk-a\tdaily\tFAILED\t2026-11-12T05:00:00Z' \
    $'disk-a\tdaily\tREADY\t2026-11-11T05:00:00Z' \
    $'disk-b\t\tREADY\t2026-11-10T05:00:00Z' ;;
  *) echo "unexpected gcloud call: $*" >&2; exit 1 ;;
esac
"""


@pytest.fixture(scope="module")
def exported(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if BASH is None:
        pytest.skip("bash is not installed")
    bin_dir = tmp_path_factory.mktemp("bin")
    fake = bin_dir / "gcloud"
    fake.write_text(FAKE_GCLOUD, encoding="utf-8", newline="\n")
    fake.chmod(0o755)
    out = tmp_path_factory.mktemp("out")
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    run = subprocess.run(
        [BASH, SCRIPT.as_posix(), out.as_posix()],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )
    assert "p2: Compute Engine API not enabled, skipped." in run.stdout
    return out


def summary(code: str, file: Path) -> dict:
    result = BY_CODE[code].parse(file.read_bytes(), 1000)
    value = dict(result.facts[-1].value)
    assert value["rows_rejected"] == 0
    return value


def test_every_port_of_an_ingress_rule_is_a_line(exported: Path) -> None:
    lines = (exported / "network-export-gcp.csv").read_text().splitlines()
    assert "rule,p1/ssh,true,inbound,allow,0.0.0.0/0,22,gcp" in lines
    assert "rule,p1/ssh,true,inbound,allow,0.0.0.0/0,8000-8100,gcp" in lines
    assert "rule,p1/internal,true,inbound,allow,10.128.0.0/9,any,gcp" in lines
    assert "rule,p1/tagged,true,inbound,allow,,443,gcp" in lines  # tags only: unknown
    assert "rule,p1/old,false,inbound,allow,0.0.0.0/0,,gcp" in lines  # disabled, ICMP
    assert "rule,p1/block,true,inbound,deny,0.0.0.0/0,53,gcp" in lines
    value = summary("network-export", exported / "network-export-gcp.csv")
    assert value["rules"] == 6 and value["rules_enabled"] == 5


def test_running_vms_are_servers_with_encrypted_disks(exported: Path) -> None:
    lines = (exported / "device-inventory-gcp.csv").read_text().splitlines()
    assert lines[1].startswith("p1/europe-west1-b/web,linux,server,")
    assert lines[2].startswith("p1/europe-west1-b/dc,windows,server,")
    value = summary("device-inventory", exported / "device-inventory-gcp.csv")
    assert value["devices"] == 2 and value["encrypted"] == 2


def test_a_disk_keeps_its_newest_result_and_last_success(exported: Path) -> None:
    lines = (exported / "backup-export-gcp.csv").read_text().splitlines()
    assert "p1/disk-a,daily,2026-11-11T05:00:00Z,failed,,,server,true,gcp" in lines
    assert (
        "p1/disk-b,manual snapshots,2026-11-10T05:00:00Z,success,,,server,true,gcp"
        in lines
    )
    value = summary("backup-export", exported / "backup-export-gcp.csv")
    assert value["jobs"] == 2 and value["failed"] == 1 and value["encrypted"] == 2


def test_the_script_only_reads_the_projects() -> None:
    code = [
        line
        for line in SCRIPT.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    calls = re.findall(r"(?:^|[\s(])gcloud ((?:compute )?\S+) (\S+)", "\n".join(code))
    assert len(calls) == 5
    for _, action in calls:
        assert action == "list", action


def test_each_kind_has_the_same_columns_in_every_cloud_script() -> None:
    # The files of one kind are joined into one import (guide 12), so their headers
    # must match.
    scripts = ("export-aws.sh", "export-gcp.sh", "export-cloudflare.sh")
    found: dict[str, set[str]] = {}
    for name in scripts:
        text = (SCRIPT.parent / name).read_text(encoding="utf-8")
        for match in re.finditer(
            r"(?:record_type|hostname|system_or_device),[a-z_,]+", text
        ):
            found.setdefault(match.group().split(",")[0], set()).add(match.group())
    assert set(found) == {"record_type", "hostname", "system_or_device"}
    assert all(len(headers) == 1 for headers in found.values()), found
