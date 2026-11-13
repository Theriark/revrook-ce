"""The Cloudflare export script (app/static/scripts/export-cloudflare.sh).

The script runs against a fake `curl` that answers like the Cloudflare API; the file it
writes is then read by revrook's own importer. It needs jq, as on the MSP's machine.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.importers.generic import ADAPTERS

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "app" / "static" / "scripts" / "export-cloudflare.sh"
NETWORK = next(a for a in ADAPTERS if a.source_code == "network-export")
BASH = shutil.which("bash")
ALLOW = {"decision": "allow", "include": [{"email_domain": {"domain": "c.example"}}]}
BYPASS = {"decision": "bypass", "include": [{"everyone": {}}]}


def page(result: object, pages: int = 1) -> dict:
    return {"success": True, "result": result, "result_info": {"total_pages": pages}}


ANSWERS = {
    "accounts": page([{"id": "acc1"}]),
    # The applications come on two pages.
    "accounts/acc1/access/apps": page(
        [
            {"domain": "admin.c.example", "policies": [ALLOW]},
            {"domain": "*.dev.c.example", "policies": [ALLOW]},
        ],
        pages=2,
    ),
    "accounts/acc1/access/apps?page=2": page(
        [
            {"domain": "open.c.example", "policies": [ALLOW, BYPASS]},
            {"domain": "www.c.example/admin", "policies": [ALLOW]},
            {"domain": "empty.c.example", "policies": []},
        ],
        pages=2,
    ),
    "accounts/acc1/cfd_tunnel?is_deleted=false": page(
        [{"id": "t1", "name": "core"}, {"id": "t2", "name": "local"}]
    ),
    "accounts/acc1/cfd_tunnel/t1/configurations": page(
        {
            "config": {
                "ingress": [
                    {"hostname": "admin.c.example", "service": "http://10.0.0.5:80"},
                    {"hostname": "app.dev.c.example", "service": "https://10.0.0.6"},
                    {"hostname": "open.c.example", "service": "ssh://10.0.0.7:22"},
                    {"hostname": "www.c.example", "service": "http://10.0.0.8"},
                    {"hostname": "empty.c.example", "service": "rdp://10.0.0.9:3389"},
                    {"hostname": "db.c.example", "service": "tcp://10.0.0.10:5432"},
                    {"service": "http_status:404"},
                ]
            }
        }
    ),
    "accounts/acc1/cfd_tunnel/t2/configurations": page({"config": None}),
}


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    if BASH is None or shutil.which("jq") is None:
        pytest.skip("bash and jq are needed")
    data = tmp_path_factory.mktemp("api")
    for i, (path, body) in enumerate(ANSWERS.items()):
        (data / f"{i}.url").write_text(path, encoding="utf-8")
        (data / f"{i}.json").write_text(json.dumps(body), encoding="utf-8")
    bin_dir = tmp_path_factory.mktemp("bin")
    fake = bin_dir / "curl"
    # Serve the answer whose path the URL ends with, ignoring per_page and page=1
    # alone; refuse anything but a GET with the bearer token.
    fake.write_text(
        f"""#!/usr/bin/env bash
case "$*" in *" -X "*|*--data*|*" -d "*) exit 9 ;; esac
case "$*" in *"Authorization: Bearer test-token"*) ;; *) exit 8 ;; esac
url="${{@: -1}}"; path="${{url#https://api.cloudflare.com/client/v4/}}"
path=$(echo "$path" | sed -E 's/[?&]per_page=50//; s/&page=1$//' \
  | sed -E 's/^([^?]*)&/\\1?/')
for f in "{data.as_posix()}"/*.url; do
  if [ "$(cat "$f")" = "$path" ]; then cat "${{f%.url}}.json"; exit 0; fi
done
echo "unexpected request: $path" >&2; exit 22
""",
        encoding="utf-8",
        newline="\n",
    )
    fake.chmod(0o755)
    out = tmp_path_factory.mktemp("out")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "CLOUDFLARE_API_TOKEN": "test-token",
    }
    done = subprocess.run(
        [BASH, SCRIPT.as_posix(), out.as_posix()],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )
    return out, done.stdout


def test_only_hosts_without_a_real_access_guard_are_written(
    run: tuple[Path, str],
) -> None:
    out, stdout = run
    lines = (out / "network-export-cloudflare.csv").read_text().splitlines()
    # open: a Bypass policy; www: guarded on a path only; empty: no policy.
    assert lines[1:] == [
        "rule,core/open.c.example,true,inbound,allow,any,22,cloudflare",
        "rule,core/www.c.example,true,inbound,allow,any,443,cloudflare",
        "rule,core/empty.c.example,true,inbound,allow,any,3389,cloudflare",
        "rule,core/db.c.example,true,inbound,allow,any,5432,cloudflare",
    ]
    assert "4 open to the internet, 2 behind Cloudflare Access" in stdout
    assert "Tunnel local: no remote configuration" in stdout


def test_revrook_reads_the_file(run: tuple[Path, str]) -> None:
    out, _ = run
    result = NETWORK.parse((out / "network-export-cloudflare.csv").read_bytes(), 1000)
    value = dict(result.facts[-1].value)
    assert value["rows_rejected"] == 0
    assert value["rules"] == 4 and value["rules_any_source"] == 4


def test_the_script_only_sends_get_requests() -> None:
    lines = SCRIPT.read_text(encoding="utf-8").splitlines()
    calls = [
        line for line in lines if "curl " in line and not line.lstrip().startswith("#")
    ]
    assert len(calls) == 1 and "curl -fsS -H" in calls[0]
    for write in (" -X", "--data", " -d ", "--request", " -F "):
        assert write not in calls[0]
