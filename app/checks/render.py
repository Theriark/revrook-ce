"""Plain text for a control and its result, with the external framework references.

An external framework identifier (a NIST CSF subcategory, a CIS safeguard, an ISO
control, a Cyber Essentials theme, a NIS2 letter) is printed only for a mapping row
that a person who read the source has verified. A row that is still verified=false
never reaches any rendered output: not its identifier, not its framework, not the
NIST name or the NIST credit that would give it away. Everything that renders a
control must take its references from `reference_lines`.

The report renderers of phase 8 use these functions; the words for a status are the
four labels of the reports plus the label of a control that does not apply.
"""

from collections.abc import Mapping

from app.checks.library import Control, visible_mappings
from app.checks.model import ControlResult, Status
from app.checks.reference import ReferenceSet

FRAMEWORK_LABELS = {
    "csf": "NIST CSF 2.0",
    "sp800-171": "NIST SP 800-171 Rev 3",
    "cis": "CIS Controls",
    "iso27001": "ISO/IEC 27001",
    "cyber-essentials": "Cyber Essentials",
    "nis2": "NIS2",
}
STATUS_LABELS: Mapping[Status, str] = {
    "pass": "Protected",
    "partial": "Needs attention",
    "fail": "Not protected",
    "unknown": "Not checked",
    "na": "Not applicable",
}


def reference_lines(
    control: Control, references: Mapping[str, ReferenceSet]
) -> list[str]:
    """One line per verified mapping row of the control; none for the others."""
    lines: list[str] = []
    for row in visible_mappings(control):
        line = f"{FRAMEWORK_LABELS[row.framework]} {row.id}"
        dataset = references.get(row.framework)
        name = dataset.names.get(row.id) if dataset is not None else None
        if name is not None:
            line += f" ({name})"
        lines.append(line)
    return lines


def credit_lines(control: Control, references: Mapping[str, ReferenceSet]) -> list[str]:
    """The NIST credit of every dataset that a verified row of the control uses."""
    used = {
        row.framework
        for row in visible_mappings(control)
        if row.framework in references and row.id in references[row.framework].names
    }
    return [references[key].credit for key in sorted(used)]


def render_control(
    control: Control,
    result: ControlResult,
    references: Mapping[str, ReferenceSet],
) -> str:
    """The control, how it stands and why, then its verified references."""
    lines = [
        f"{control.id} {control.title}",
        f"{STATUS_LABELS[result.status]}. {result.detail}",
        *reference_lines(control, references),
        *credit_lines(control, references),
    ]
    return "\n".join(lines)
