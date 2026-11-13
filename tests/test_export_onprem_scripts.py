"""The UniFi, Checkmk and Xen Orchestra export scripts (app/static/scripts).

Each script runs against a fake `curl` that answers like the product's API (the shapes
were read from real consoles); the file it writes is then read by revrook's importer.
They need bash and jq, as on the MSP's machine.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.importers.generic import ADAPTERS

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "app" / "static" / "scripts"
BY_CODE = {adapter.source_code: adapter for adapter in ADAPTERS}
BASH = shutil.which("bash")
STAMP = re.compile(r",\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
FAKE_CURL = """#!/usr/bin/env bash
for arg in "$@"; do case "$arg" in http*) url="$arg" ;; esac; done
for f in "$ANSWERS"/*.match; do
  if [[ "$url" == *"$(cat "$f")"* ]]; then cat "${f%.match}.json"; exit 0; fi
done
echo "unexpected request: $url" >&2; exit 22
"""


def run(tmp: Path, script: str, answers: list[tuple[str, object]], env: dict) -> Path:
    if BASH is None or shutil.which("jq") is None:
        pytest.skip("bash and jq are needed")
    folder = tmp / "answers"
    folder.mkdir()
    for number, (match, body) in enumerate(answers):  # the first match wins
        (folder / f"{number:02d}.match").write_text(match, encoding="utf-8")
        (folder / f"{number:02d}.json").write_text(json.dumps(body), encoding="utf-8")
    fake = tmp / "bin" / "curl"
    fake.parent.mkdir()
    fake.write_text(FAKE_CURL, encoding="utf-8", newline="\n")
    fake.chmod(0o755)
    out = tmp / "out"
    path = f"{fake.parent}{os.pathsep}{os.environ['PATH']}"
    environ = {**os.environ, **env, "PATH": path, "ANSWERS": folder.as_posix()}
    subprocess.run(
        [BASH, (SCRIPTS / script).as_posix(), out.as_posix()],
        check=True,
        env=environ,
        capture_output=True,
        text=True,
    )
    return out


def lines(file: Path) -> list[str]:
    """The lines of a written file without the exported_at column every line has."""
    text = file.read_text(encoding="utf-8").splitlines()
    assert text[0].endswith(",exported_at") and all(STAMP.search(x) for x in text[1:])
    return [text[0].removesuffix(",exported_at")] + [STAMP.sub("", x) for x in text[1:]]


def summary(code: str, file: Path) -> dict:
    result = BY_CODE[code].parse(file.read_bytes(), 1000)
    value = dict(result.facts[-1].value)
    assert value["rows_rejected"] == 0 and value["capture_time_source"] == "file"
    return value


def page(items: list) -> dict:
    return {"data": items, "totalCount": len(items)}


def ports(*values: int) -> dict:
    items = [{"type": "PORT_NUMBER", "value": v} for v in values]
    return {
        "trafficFilter": {
            "type": "PORT",
            "portFilter": {"type": "PORTS", "items": items},
        }
    }


def policy(
    name: str,
    source: str,
    target: str,
    *,
    origin: str = "USER_DEFINED",
    destination: dict | None = None,
    protocol: str = "TCP",
) -> dict:
    return {
        "name": name,
        "enabled": True,
        "action": {"type": "ALLOW"},
        "metadata": {"origin": origin},
        "source": {"zoneId": source},
        "destination": {"zoneId": target, **(destination or {})},
        "ipProtocolScope": {"protocolFilter": {"protocol": {"name": protocol}}},
    }


UNIFI = [
    (
        "firewall/zones",
        page(
            [
                {"id": "z-ext", "name": "External", "networkIds": []},
                {"id": "z-gw", "name": "Gateway", "networkIds": []},
                {"id": "z-int", "name": "Internal", "networkIds": ["n-lan"]},
                {"id": "z-guest", "name": "Guest", "networkIds": ["n-guest"]},
            ]
        ),
    ),
    (
        "firewall/policies",
        page(
            [
                policy(
                    "Allow SSH to the gateway", "z-ext", "z-gw", destination=ports(22)
                ),
                policy(
                    "Allow Return Traffic", "z-ext", "z-int", origin="SYSTEM_DEFINED"
                ),
                policy(
                    "Allow Router Advertisements",
                    "z-ext",
                    "z-gw",
                    origin="SYSTEM_DEFINED",
                    protocol="ICMPV6",
                ),
                policy(
                    "Allow Port Forward RDP", "z-ext", "z-int", origin="SYSTEM_DEFINED"
                ),
                policy("Guests to the printer", "z-guest", "z-int"),
            ]
        ),
    ),
    ("traffic-matching-lists", page([])),
    (
        "wifi/broadcasts",
        page(
            [
                {
                    "name": "Corp",
                    "network": {"networkId": "n-lan"},
                    "securityConfiguration": {"type": "WPA3_PERSONAL"},
                },
                {
                    "name": "Guests",
                    "network": {"networkId": "n-guest"},
                    "securityConfiguration": {"type": "OPEN"},
                },
            ]
        ),
    ),
    ("integration/v1/sites", page([{"id": "s1", "internalReference": "default"}])),
    (
        "stat/device",
        {
            "data": [
                {
                    "type": "udm",
                    "model": "UDMPRO",
                    "version": "5.1.35.1",
                    "name": "GW-1",
                },
                {"type": "usw", "name": "SW-1"},
            ]
        },
    ),
    (
        "rest/portforward",
        {
            "data": [
                {"name": "RDP", "enabled": True, "dst_port": "3389", "src": "any"},
                {"name": "Mail", "enabled": False, "dst_port": "25"},
            ]
        },
    ),
    (
        "rest/setting",
        {
            "data": [
                {
                    "key": "rsyslogd",
                    "enabled": True,
                    "this_controller": False,
                    "ip": "10.0.0.5",
                }
            ]
        },
    ),
    (
        "fw-update.ui.com",
        {
            "_embedded": {
                "firmware": [
                    {"version": "v5.1.34+aa", "created": "2026-10-28T16:55:59Z"},
                    {"version": "v5.1.35+bb", "created": "2026-11-04T20:24:51Z"},
                ]
            }
        },
    ),
]


def test_unifi_writes_the_gateway_inbound_rules_and_wifi(tmp_path: Path) -> None:
    out = run(
        tmp_path,
        "export-unifi.sh",
        UNIFI,
        {"UNIFI_URL": "https://gw.example", "UNIFI_API_KEY": "test-key"},
    )
    file = out / "network-export-unifi.csv"
    got = lines(file)
    tool = "unifi:GW-1"
    # Firmware dated from Ubiquiti's list; management (SSH) open from the internet.
    assert f"device,GW-1,true,2026-11-04,true,false,10.0.0.5,,,,,,,,,,{tool}" in got
    assert f"rule,RDP,,,,,,true,inbound,allow,any,3389,,,,,{tool}" in got
    assert (
        f"rule,Allow SSH to the gateway,,,,,,true,inbound,allow,any,22,,,,,{tool}"
        in got
    )
    assert "Allow Router Advertisements" not in got  # ICMP opens no port
    assert not any(
        "Mail" in x or "Return Traffic" in x or "Port Forward" in x for x in got
    )
    assert f"ssid,,,,,,,,,,,,Corp,wpa3,false,,{tool}" in got
    # A user-defined policy lets guests reach an internal zone: not isolated.
    assert f"ssid,,,,,,,,,,,,Guests,open,true,false,{tool}" in got
    value = summary("network-export", file)
    assert value["rules"] == 2 and value["perimeter_devices"] == 1
    assert value["tool"] == tool.lower()  # revrook keeps tools in lower case


CHECKMK = [
    (
        "domain-types/host/",
        {
            "value": [
                {
                    "extensions": {
                        "name": "SRV-1",
                        "labels": {
                            "cmk/os_family": "windows",
                            "cmk/os_version": "10.0.26100",
                            "cmk/os_name": "Microsoft Windows Server 2025 Standard",
                        },
                    }
                },
                {
                    "extensions": {
                        "name": "PC-1",
                        "labels": {
                            "cmk/os_family": "windows",
                            "cmk/os_version": "10.0.26200",
                            "cmk/os_name": "Microsoft Windows 11 Pro",
                        },
                    }
                },
                {
                    "extensions": {
                        "name": "LNX-1",
                        "labels": {"cmk/os_family": "linux", "cmk/os_version": "24.04"},
                    }
                },
                {"extensions": {"name": "SWITCH-1", "labels": {}}},
            ]
        },
    ),
    (
        "domain-types/service/",
        {
            "value": [
                {
                    "extensions": {
                        "host_name": "SRV-1",
                        "description": "Check_MK",
                        "state": 0,
                        "last_time_ok": 1794578400,
                    }
                },
                {
                    "extensions": {
                        "host_name": "PC-1",
                        "description": "Check_MK",
                        "state": 2,
                        "last_time_ok": 1791253084,
                    }
                },
                {
                    "extensions": {
                        "host_name": "LNX-1",
                        "description": "Check_MK",
                        "state": 0,
                        "last_time_ok": 1794578400,
                    }
                },
                {
                    "extensions": {
                        "host_name": "LNX-1",
                        "description": "APT Updates",
                        "state": 1,
                        "last_time_ok": 1794578400,
                    }
                },
            ]
        },
    ),
]


def test_checkmk_writes_the_agent_hosts(tmp_path: Path) -> None:
    out = run(
        tmp_path,
        "export-checkmk.sh",
        CHECKMK,
        {
            "CHECKMK_URL": "https://mon.example/site",
            "CHECKMK_USER": "reader",
            "CHECKMK_SECRET": "test-secret",
        },
    )
    file = out / "device-inventory-checkmk.csv"
    got = lines(file)
    assert got[1:] == [
        "SRV-1,windows,server,10.0.26100,2026-11-13T14:00:00Z,unknown,,,unknown,,,checkmk",
        "PC-1,windows,workstation,10.0.26200,2026-10-06T02:18:04Z,unknown,,,unknown,,,checkmk",
        "LNX-1,linux,server,24.04,2026-11-13T14:00:00Z,pending,,,unknown,,,checkmk",
    ]
    value = summary("device-inventory", file)
    assert value["devices"] == 3 and value["servers"] == 2


XO = [
    (
        "backup-jobs",
        [
            {
                "id": "j1",
                "name": "Nightly",
                "type": "backup",
                "remotes": {"id": "r1"},
                "settings": {"s1": {"exportRetention": 7}},
                "vms": {
                    "type": "VM",
                    "tags": {
                        "__and": [
                            {"__or": [["BACKUP-X"]]},
                            {"__not": {"__or": [["Continuous Replication"]]}},
                        ]
                    },
                },
            },
            {
                "id": "j2",
                "name": "Paused",
                "type": "backup",
                "remotes": {"id": "r1"},
                "settings": {},
                "vms": {"id": "vm1"},
            },
        ],
    ),
    (
        "schedules",
        [
            {"id": "s1", "jobId": "j1", "cron": "0 5 * * *", "enabled": True},
            {"id": "s2", "jobId": "j2", "cron": "0 5 * * *", "enabled": False},
        ],
    ),
    (
        "backup-logs",
        [
            {
                "jobId": "j1",
                "status": "success",
                "start": 1794376800000,
                "end": 1794378000000,
            },
            {
                "jobId": "j1",
                "status": "failure",
                "start": 1794463200000,
                "end": 1794464400000,
            },
        ],
    ),
    ("backup-repositories", [{"id": "r1", "url": "nfs://192.168.0.163:/backups"}]),
    (
        "vms",
        [
            {"id": "vm1", "name_label": "SRV-1 | Web", "tags": ["BACKUP-X"]},
            {
                "id": "vm2",
                "name_label": "SRV-2 | Copy",
                "tags": ["BACKUP-X", "Continuous Replication"],
            },
            {"id": "vm3", "name_label": "PC-9", "tags": []},
        ],
    ),
]


def test_xo_writes_one_line_per_vm_of_each_scheduled_job(tmp_path: Path) -> None:
    out = run(
        tmp_path,
        "export-xo.sh",
        XO,
        {
            "XO_URL": "https://xo.example",
            "XO_TOKEN": "test-token",
            "XO_NAME_SEPARATOR": " | ",
        },
    )
    file = out / "backup-export-xo.csv"
    got = lines(file)
    # Newest run failed; the success before it is the last success. A paused job and a
    # VM excluded by its tags are not written; the NFS share on a private address is on
    # site and unencrypted.
    assert got[1:] == [
        "SRV-1,Nightly,2026-11-11T06:20:00Z,failed,7,,server,24,false,,false,xo"
    ]
    value = summary("backup-export", file)
    assert value["jobs"] == 1 and value["failed"] == 1


@pytest.mark.parametrize(
    "script", ["export-unifi.sh", "export-checkmk.sh", "export-xo.sh"]
)
def test_the_scripts_only_read(script: str) -> None:
    code = [
        line
        for line in (SCRIPTS / script).read_text(encoding="utf-8").splitlines()
        if "curl " in line and not line.lstrip().startswith("#")
    ]
    assert code
    for line in code:
        for write in ("--data", " -d ", "-F ", "PUT", "DELETE", "PATCH"):
            assert write not in line, (script, line)
        # Checkmk's list endpoints take their query by POST (they change nothing).
        if " -X " in line:
            assert script == "export-checkmk.sh" and " -X POST " in line
