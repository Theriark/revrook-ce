"""Plain-language names of the evidence sources, what to do to refresh one, which
controls read each source and how old an export of it may get."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.checks.library import Library

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
# The DNS controls read the DNS check, which is not a column of `field_map`.
DNS_CONTROLS = ("PC-EML-01", "PC-EML-02", "PC-EML-03")
# Sources that only prove the import pipeline in tests: no control reads them, and
# no page, list or report shows them to a person.
INTERNAL_SOURCES = frozenset({"reference-csv"})
# The mark drawn beside a source (app/ui/templates/_icons.html, source_mark): one
# drawing per family of export, never a vendor logo. A code that is not listed
# gets the generic list mark.
SOURCE_ICONS = {
    "entra-registration": "cloud",
    "secure-score": "cloud",
    "intune-devices": "devices",
    "conditional-access": "cloud",
    "directory-roles": "cloud",
    "device-inventory": "devices",
    "backup-export": "backup",
    "network-export": "network",
    "training-csv": "training",
    "leavers-csv": "leavers",
    "exchange-export": "mail",
    "dns-check": "globe",
    "reference-csv": "list",
}
DEFAULT_SOURCE_ICON = "list"


def source_name(code: str) -> str:
    """The name of a source for a person; an unknown code is shown as it is."""
    return SOURCE_NAMES.get(code, code)


def is_shown(code: str) -> bool:
    """Whether a source is one a person sees (not an internal test source)."""
    return code not in INTERNAL_SOURCES


def refresh_instruction(code: str) -> str:
    """What the MSP does to bring the evidence of a source up to date."""
    if code == DNS_SOURCE:
        return "Run the public DNS check again for the mail domains of this client."
    return "Export it again from the source system and import it on Import evidence."


def control_sources(library: "Library") -> dict[str, tuple[str, ...]]:
    """The sources (importer codes) each control reads, by control id.

    A field is mapped to an adapter column in `field_map`; the three mail controls
    also read the public DNS check, which is not a file and so not in `field_map`.
    A manual-only control reads no source and gets an empty tuple.
    """
    found: dict[str, tuple[str, ...]] = {}
    for control in library.controls:
        codes = {
            library.field_map[field].adapter
            for field in control.fields
            if field in library.field_map
        }
        if control.id in DNS_CONTROLS:
            codes.add(DNS_SOURCE)
        found[control.id] = tuple(sorted(codes))
    return found


def source_max_ages(library: "Library") -> dict[str, int]:
    """The strictest automatic maximum age, in days, of the controls reading a source.

    An export goes stale for the checks as soon as the strictest control that reads
    it says so (a device export after 7 days, not after the 35 days of the store),
    so the evidence pages and the expiry reminders measure a source by this age and
    agree with the checklist.
    """
    ages: dict[str, int] = {}
    reads = control_sources(library)
    for control in library.controls:
        days = control.max_age_days.automatic
        if days is None:
            continue
        for code in reads[control.id]:
            ages[code] = min(days, ages.get(code, days))
    return ages


def source_icon(code: str) -> str:
    """The name of the icon drawn beside a source (the generic mark when unknown)."""
    return SOURCE_ICONS.get(code, DEFAULT_SOURCE_ICON)
