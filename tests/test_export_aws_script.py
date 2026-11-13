"""The AWS export script (app/static/scripts/export-aws.sh).

The script runs against a fake `aws` that answers like AWS CLI v2 text output; the
files it writes are then read by revrook's own importers.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.importers.generic import ADAPTERS

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "app" / "static" / "scripts" / "export-aws.sh"
BY_CODE = {adapter.source_code: adapter for adapter in ADAPTERS}
BASH = shutil.which("bash")

# Tab-separated answers, in the column order of each --query of the script.
FAKE_AWS = r"""#!/usr/bin/env bash
case "$1 $2" in
  "sts get-caller-identity") echo 123456789012 ;;
  "ec2 describe-regions") echo eu-west-1 ;;
  "ec2 describe-vpcs") printf '%s\n' $'vpc-1\t172.31.0.0/16 2a05:d018::/56' ;;
  "ec2 describe-security-groups") printf '%s\n' $'sg-1\tvpc-1' $'sg-2\tvpc-1' ;;
  "ec2 describe-security-group-rules") printf '%s\n' \
    $'sg-1\ttcp\t22\t22\t0.0.0.0/0\tNone\tNone\tNone' \
    $'sg-1\ttcp\t8000\t8100\t10.0.0.0/8\tNone\tNone\tNone' \
    $'sg-2\t-1\t-1\t-1\tNone\tNone\tsg-2\tNone' \
    $'sg-2\ttcp\t443\t443\tNone\tNone\tsg-9\tpcx-1' \
    $'sg-2\ticmp\t8\t0\tNone\t::/0\tNone\tNone' ;;
  "ec2 describe-volumes") printf '%s\n' \
    $'i-a\tTrue' $'i-a\tFalse' $'None\tTrue' ;;
  "ec2 describe-instances") printf '%s\n' \
    $'i-a\tLinux/UNIX' $'i-b\tWindows' ;;
  "backup list-backup-jobs") printf '%s\n' \
    $'2026-11-10T05\tarn:db\tplan-1\tCOMPLETED\t2026-11-10T05:20:00Z\tRDS\tv' \
    $'2026-11-12T05\tarn:db\tplan-1\tFAILED\tNone\tRDS\tv' \
    $'2026-11-13T05\tarn:db\tplan-1\tRUNNING\tNone\tRDS\tv' \
    $'2026-11-11T05\tarn:vol\tNone\tCOMPLETED\t2026-11-11T05:10:00Z\tEBS\tv' ;;
  *) echo "unexpected aws call: $*" >&2; exit 1 ;;
esac
"""


@pytest.fixture(scope="module")
def exported(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if BASH is None:
        pytest.skip("bash is not installed")
    bin_dir = tmp_path_factory.mktemp("bin")
    fake = bin_dir / "aws"
    fake.write_text(FAKE_AWS, encoding="utf-8", newline="\n")
    fake.chmod(0o755)
    out = tmp_path_factory.mktemp("out")
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    subprocess.run([BASH, SCRIPT.as_posix(), out.as_posix()], check=True, env=env)
    return out


def summary(code: str, file: Path) -> dict:
    result = BY_CODE[code].parse(file.read_bytes(), 1000)
    value = dict(result.facts[-1].value)
    assert value["rows_rejected"] == 0
    return value


def test_inbound_rules_are_read_with_their_source(exported: Path) -> None:
    text = (exported / "network-export-aws.csv").read_text(encoding="utf-8")
    # A group of the same VPC is reached from the VPC's blocks only; across a
    # peering the source is unknown.
    assert "sg-2,true,inbound,allow,172.31.0.0/16 2a05:d018::/56,any" in text
    assert "sg-2,true,inbound,allow,,443" in text
    assert "allow,::/0,,aws\n" in text  # ICMP has no port
    value = summary("network-export", exported / "network-export-aws.csv")
    assert value["rules"] == 5
    assert value["rules_any_source"] == 2  # 0.0.0.0/0 and ::/0


def test_running_instances_carry_their_disk_encryption(exported: Path) -> None:
    lines = (
        (exported / "device-inventory-aws.csv").read_text(encoding="utf-8").splitlines()
    )
    assert lines[1].startswith("i-a,linux,server,") and lines[1].endswith(",false,aws")
    assert lines[2].startswith("i-b,windows,server,") and lines[2].endswith(",,aws")
    value = summary("device-inventory", exported / "device-inventory-aws.csv")
    assert value["devices"] == 2 and value["encryption_known"] == 1


def test_a_backup_job_keeps_its_newest_result_and_last_success(exported: Path) -> None:
    lines = (
        (exported / "backup-export-aws.csv").read_text(encoding="utf-8").splitlines()
    )
    assert "arn:db,plan-1 (v),2026-11-10T05:20:00Z,failed,,,database,,aws" in lines
    assert "arn:vol,on-demand (v),2026-11-11T05:10:00Z,success,,,server,,aws" in lines
    value = summary("backup-export", exported / "backup-export-aws.csv")
    assert value["jobs"] == 2 and value["failed"] == 1 and value["success"] == 1


def test_the_script_only_reads_the_account() -> None:
    code = [
        line
        for line in SCRIPT.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    calls = re.findall(r"(?:^|[\s(])aws (\S+) (\S+)", "\n".join(code))
    assert len(calls) == 8
    for _, action in calls:
        assert action.startswith(("describe-", "list-", "get-")), action
