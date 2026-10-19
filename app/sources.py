"""Plain-language names of the evidence sources, and what to do to refresh one."""

SOURCE_NAMES = {
    "entra-registration": "Microsoft Entra registration export",
    "secure-score": "Microsoft Secure Score export",
    "intune-devices": "Intune device export",
    "conditional-access": "Conditional Access policies export",
    "directory-roles": "Directory roles export",
    "device-inventory": "Device inventory, patch and antivirus export",
    "backup-export": "Backup jobs export",
    "network-export": "Network export",
    "training-csv": "Training completions export",
    "leavers-csv": "Leavers list",
    "exchange-export": "Exchange Online settings export",
    "dns-check": "Public DNS check",
    "reference-csv": "Reference user list",
}
DNS_SOURCE = "dns-check"


def source_name(code: str) -> str:
    """The name of a source for a person; an unknown code is shown as it is."""
    return SOURCE_NAMES.get(code, code)


def refresh_instruction(code: str) -> str:
    """What the MSP does to bring the evidence of a source up to date."""
    if code == DNS_SOURCE:
        return "Run the public DNS check again for the mail domains of this client."
    return "Export it again from the source system and import it."
