"""The topics of the insurance evidence pack (rnd-report-3 section 3.8).

Insurer forms differ and change every year, so the pack maps OUR topics and the
technician ticks which of them the client's form asks about. No insurer wording is
copied. Every control of the library belongs to exactly one topic (a test enforces
it), so adding a control cannot leave it out of the pack.

A topic is Met only when every control of it that applies is Protected. It is Not
checked when none of them could be checked, and Not met when none is Protected or
in need of attention and at least one is Not protected. Everything else is Partly.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.reports.status import (
    NEEDS_ATTENTION,
    NOT_APPLICABLE,
    NOT_CHECKED,
    NOT_PROTECTED,
    PROTECTED,
    StatusLabel,
)

MET = "Met"
PARTLY = "Partly"
NOT_MET = "Not met"
TOPIC_NOT_CHECKED = "Not checked"
TOPIC_STATUSES = (MET, PARTLY, NOT_MET, TOPIC_NOT_CHECKED)
# A topic shows like a control: an icon and the words, in the status colours.
LABEL_BY_TOPIC_STATUS = {
    MET: StatusLabel("protected", MET, "check"),
    PARTLY: StatusLabel("needs-attention", PARTLY, "alert"),
    NOT_MET: StatusLabel("not-protected", NOT_MET, "cross"),
    TOPIC_NOT_CHECKED: StatusLabel("not-checked", TOPIC_NOT_CHECKED, "question"),
}


@dataclass(frozen=True)
class Topic:
    key: str
    title: str
    question: str
    control_ids: tuple[str, ...]


TOPICS = (
    Topic(
        "mfa",
        "Multi-factor authentication for staff",
        "Do all staff sign in with more than a password, and is it enforced?",
        ("PC-ACC-01", "PC-ACC-03", "PC-ACC-04"),
    ),
    Topic(
        "privileged",
        "Privileged access",
        "Are administrators few, personal, protected and reviewed?",
        ("PC-ACC-02", "PC-ACC-05", "PC-ACC-06", "PC-ACC-08"),
    ),
    Topic(
        "endpoint",
        "Endpoint protection",
        "Is every device protected against malware, and can users switch it off?",
        ("PC-END-01", "PC-END-02", "PC-END-03", "PC-END-04", "PC-END-05"),
    ),
    Topic(
        "backup",
        "Backups and recovery",
        "Are backups recent, out of reach of an attacker and restore-tested?",
        (
            "PC-BCK-01",
            "PC-BCK-02",
            "PC-BCK-03",
            "PC-BCK-04",
            "PC-BCK-05",
            "PC-BCK-06",
        ),
    ),
    Topic(
        "patching",
        "Devices and patching",
        "Are devices managed and updated promptly, with no unsupported system?",
        ("PC-DEV-01", "PC-DEV-02", "PC-DEV-03"),
    ),
    Topic(
        "email",
        "Email security",
        "Are SPF, DKIM and DMARC in place and is inbound mail filtered?",
        (
            "PC-EML-01",
            "PC-EML-02",
            "PC-EML-03",
            "PC-EML-04",
            "PC-EML-05",
            "PC-EML-06",
            "PC-EML-07",
        ),
    ),
    Topic(
        "training",
        "Security awareness training",
        "Do staff complete security awareness training every year?",
        ("PC-GOV-03",),
    ),
    Topic(
        "incident",
        "Incident response and alerting",
        "Is there an incident response plan that was exercised, and do alerts reach "
        "a named person?",
        ("PC-GOV-05", "PC-LOG-03"),
    ),
    Topic(
        "vendors",
        "Supplier and guest access",
        "Are third-party apps, suppliers and guest accounts reviewed?",
        ("PC-GOV-06", "PC-ACC-07"),
    ),
    Topic(
        "other",
        "Other safeguards",
        "Device settings, network, logging and governance controls that insurer "
        "forms ask about in other words.",
        (
            "PC-DEV-04",
            "PC-DEV-05",
            "PC-DEV-06",
            "PC-DEV-07",
            "PC-NET-01",
            "PC-NET-02",
            "PC-NET-03",
            "PC-NET-04",
            "PC-NET-05",
            "PC-LOG-01",
            "PC-LOG-02",
            "PC-LOG-04",
            "PC-LOG-05",
            "PC-LOG-06",
            "PC-GOV-01",
            "PC-GOV-02",
            "PC-GOV-04",
            "PC-GOV-07",
        ),
    ),
)
TOPIC_KEYS = tuple(topic.key for topic in TOPICS)


def topic_status(labels: Sequence[StatusLabel]) -> str:
    """Met, Partly, Not met or Not checked for the labels of a topic's controls."""
    counted = [label for label in labels if label != NOT_APPLICABLE]
    if not counted or all(label == NOT_CHECKED for label in counted):
        return TOPIC_NOT_CHECKED
    if all(label == PROTECTED for label in counted):
        return MET
    helped = any(label in (PROTECTED, NEEDS_ATTENTION) for label in counted)
    if not helped and any(label == NOT_PROTECTED for label in counted):
        return NOT_MET
    return PARTLY
