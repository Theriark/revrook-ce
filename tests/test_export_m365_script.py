"""The Microsoft 365 export script (app/static/scripts/export-m365.ps1).

The script runs on the MSP's machine, not in the test suite; these checks read it.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (ROOT / "app" / "static" / "scripts" / "export-m365.ps1").read_text(
    encoding="utf-8"
)


def test_device_code_is_an_option_of_every_sign_in() -> None:
    # Without a sign-in window (embedded terminal, remote session) the export must
    # still be possible: -UseDeviceCode reaches Graph, Exchange and Compliance.
    assert "[switch]$UseDeviceCode" in SCRIPT
    assert "if ($UseDeviceCode) { $connect['UseDeviceCode'] = $true }" in SCRIPT
    assert "if ($UseDeviceCode) { $exchange['Device'] = $true }" in SCRIPT
    assert "if ($UseDeviceCode) { $compliance['Device'] = $true }" in SCRIPT
    assert "Connect-IPPSSession @compliance" in SCRIPT


def test_the_script_only_reads_the_tenant() -> None:
    code = [line for line in SCRIPT.splitlines() if not line.lstrip().startswith("#")]
    calls = [line for line in code if "Invoke-MgGraphRequest" in line]
    assert calls and all("-Method GET" in line for line in calls)
    writes = ("Set-Org", "Set-Mailbox", "New-Inbound", "Remove-", "Enable-", "Disable-")
    for verb in writes:
        assert not any(verb in line for line in code), verb
