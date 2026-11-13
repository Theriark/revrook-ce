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


def test_a_refused_source_is_skipped_not_fatal() -> None:
    # A tenant without Entra ID P1 or Intune must still get the other files.
    save = SCRIPT[SCRIPT.index("function Save-Graph") :]
    save = save[: save.index("\n}\n")]
    assert "try {" in save and "catch {" in save
    assert "[void]$Skipped.Add($Name)" in save
    assert SCRIPT.count('Write-Warning ("Not written: "') == 2


def test_exchange_signs_in_through_the_browser_when_it_can() -> None:
    assert "Parameters.ContainsKey('DisableWAM')" in SCRIPT
    assert "$exchange['DisableWAM'] = $true" in SCRIPT


def test_every_exchange_line_says_when_it_was_exported() -> None:
    # revrook reads exported_at as the capture time of the Exchange CSV.
    assert "'recipient_count', 'last_acknowledged', 'exported_at'" in SCRIPT
    assert "$row['exported_at'] = $ExportedAt" in SCRIPT
    assert "ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')" in SCRIPT
