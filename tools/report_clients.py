"""The three worked clients (A, B, C) as reports, for the phase 8 tests.

The scores come from tests/scoring_vectors/clients.json through `tools/score_inputs`;
this module adds what a technician writes for a report: names, findings, exceptions
and the decision that a control is not applicable. Everything here is synthetic and
fixed, so the golden reports in tests/golden/reports are stable.
"""

from datetime import date, datetime, timedelta

from app.checks.library import Library
from app.checks.model import NaReview
from app.exceptions import ExceptionEntry
from app.reports.view import Finding, ReportContext
from app.scoring.engine import domain_weights
from app.scoring.model import DEFAULT_THRESHOLDS
from app.scoring.snapshot import EvidenceRef, SnapshotInput, render_snapshot
from tools.score_inputs import AS_OF, client_spec, inputs_for, load_clients

MSP = "Harbour IT Services"
PREPARED_BY = "Sam Technician"
GENERATED_ON = date(2026, 10, 17)
PERIOD = (date(2026, 7, 1), date(2026, 9, 30))
PREVIOUS_AS_OF = AS_OF - timedelta(days=92)
IMPORTER_VERSION = "importers-1"
NAMES = {
    "A": "Alder and Finch Ltd",
    "B": "Birch Logistics",
    "C": "Cedar Dental Group",
}
# The client whose scores stand in for "last quarter" (None: no earlier report).
EARLIER = {"A": "C", "B": None, "C": "A"}
EVIDENCE = (
    EvidenceRef("evidence-0001", "0123456789abcdef" * 4),
    EvidenceRef("evidence-0002", "fedcba9876543210" * 4),
    EvidenceRef("evidence-0003", "00ff" * 16),
)
SOURCES = (
    "Microsoft Entra registration export",
    "Intune device export",
    "Backup report",
    "Public DNS check",
    "Technician attestations",
)

FINDINGS = {
    "A": {
        "PC-EML-03": Finding(
            did="Published a DMARC record in monitoring mode.",
            recommend="Move the DMARC policy to quarantine once reports are clean.",
            need="A decision on the date to enforce.",
            by_when="2026-11-30",
        ),
        "PC-BCK-04": Finding(
            recommend="Keep one backup copy where an administrator account cannot "
            "delete it.",
            need="Approval of the extra storage.",
            by_when="2026-12-15",
        ),
        "PC-ACC-06": Finding(did="Disabled two dormant accounts."),
    },
    "B": {
        "PC-ACC-01": Finding(
            did="Registered 28 of 35 people for multi-factor sign-in.",
            recommend="Register the remaining people and then enforce it by policy.",
            need="Seven people to attend a 15 minute session.",
            by_when="2026-11-15",
        ),
        "PC-ACC-04": Finding(
            recommend="Block the legacy sign-in methods that skip multi-factor checks.",
            need="A list of the devices that still use them.",
            by_when="2026-11-30",
        ),
        "PC-DEV-07": Finding(
            recommend="Remove local administrator rights from daily accounts.",
            by_when="2027-01-31",
        ),
    },
    "C": {
        "PC-ACC-02": Finding(
            did="Found one administrator without multi-factor sign-in.",
            recommend="Enrol that administrator today.",
            need="Fifteen minutes with the administrator.",
            by_when="2026-10-24",
        ),
    },
}
EXCEPTIONS = {
    "A": (
        ExceptionEntry(
            "PC-DEV-05",
            "Office manager",
            "One reception laptop cannot meet the baseline until it is replaced.",
            "The laptop holds no client data and is reimaged every month.",
            date(2026, 12, 1),
        ),
    ),
    "B": (
        ExceptionEntry(
            "PC-NET-05",
            "Managing director",
            "The warehouse scanners cannot use web filtering.",
            None,
            date(2026, 9, 30),
        ),
    ),
    "C": (),
}
NA_REVIEWS = {
    "A": {
        "PC-NET-04": NaReview(
            "The office has no wireless network.", PREPARED_BY, "Alex Reviewer"
        ),
    },
    "B": {},
    "C": {},
}
OWNERS = {
    "A": {"backup": "Sam Technician", "mfa": "Client IT contact"},
    "B": {"backup": "Sam Technician"},
    "C": {},
}
ASKED = {
    "A": None,
    "B": frozenset({"mfa", "privileged", "backup", "email", "endpoint"}),
    "C": None,
}


def inputs(library: Library, name: str, as_of: datetime) -> SnapshotInput:
    spec = client_spec(library, load_clients(), name)
    return SnapshotInput(
        ruleset_id=library.ruleset_id,
        ruleset_version=library.version,
        importer_version=IMPORTER_VERSION,
        as_of=as_of,
        thresholds=DEFAULT_THRESHOLDS,
        domains=domain_weights(library),
        controls=inputs_for(library, spec, as_of),
        evidence=EVIDENCE,
    )


def snapshot_bytes(library: Library, name: str) -> bytes:
    """The stored snapshot of a worked client at the pack date."""
    return render_snapshot(inputs(library, name, AS_OF))


def previous_bytes(library: Library, name: str) -> bytes | None:
    """The snapshot of the earlier report (None for a client without one)."""
    earlier = EARLIER[name]
    if earlier is None:
        return None
    return render_snapshot(inputs(library, earlier, PREVIOUS_AS_OF))


def context_for(name: str) -> ReportContext:
    return ReportContext(
        msp_name=MSP,
        client_name=NAMES[name],
        period_start=PERIOD[0],
        period_end=PERIOD[1],
        prepared_by=PREPARED_BY,
        generated_on=GENERATED_ON,
        data_sources=SOURCES,
        findings=FINDINGS[name],
        next_quarter_plan=(
            "Review the evidence that expires first.",
            "Re-run the public DNS check after any mail change.",
            "Agree the dates in the table of actions with the client.",
        ),
        exceptions=EXCEPTIONS[name],
        na_reviews=NA_REVIEWS[name],
        topic_owners=OWNERS[name],
        asked_topics=ASKED[name],
    )
