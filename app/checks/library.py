"""The control library: ruleset PC-RULES, loaded from data/controls.yaml.

Phase 5, part 1. This module reads and validates the file; it does not evaluate a
control (the check engine is part 2).

Validation has two steps. The JSON Schema in controls.schema.json checks the
structure: every key, its type, the allowed words, and the rules that follow from
a control being manual-only. Then the cross-references that a schema cannot
express are checked: control ids are unique and agree with their domain, domain
weights add up to 100, every field a control reads is declared (mapped to an
adapter column, or listed as unavailable) and read by a control, and a threshold
pair is in order. A file that fails either step is refused with every problem
named, never half loaded.

Nothing from the CIS Controls, the Secure Controls Framework, ISO 27001, the CSA
CCM or SIG is in the file. The external framework entries of a control are
identifiers only, and a mapping row is shown in a report only once a person who
read the source has marked it verified (`visible_mappings`).
"""

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import yaml

from app.schemacheck import schema_problems

ROOT = Path(__file__).resolve().parents[2]
CONTROLS_PATH = ROOT / "data" / "controls.yaml"
SCHEMA_PATH = Path(__file__).with_name("controls.schema.json")
MAX_REPORTED_PROBLEMS = 10
# The numbers of rnd-report-3 section 3.4: counted, not chosen.
EXPECTED_COUNTS = {
    "controls": 51,
    "domains": 8,
    "domain weights": 100,
    "gates": 3,
    "manual-only controls": 8,
}


class ControlLibraryError(Exception):
    """The control file (or a reference dataset) is not valid.

    `problems` lists every problem found; the message shows the first ten.
    """

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        shown = self.problems[:MAX_REPORTED_PROBLEMS]
        more = len(self.problems) - len(shown)
        text = "; ".join(shown)
        if more > 0:
            text += f"; and {more} more"
        super().__init__(text)


@dataclass(frozen=True)
class Domain:
    code: str
    name: str
    weight: int


@dataclass(frozen=True)
class MaxAge:
    """Freshness maximum ages in days; None where the report names none."""

    automatic: int | None
    manual: int | None


@dataclass(frozen=True)
class Threshold:
    """One side of a rule: a share at least (exact decimal) or a count at most."""

    at_least: Decimal | None
    at_most: int | None


@dataclass(frozen=True)
class Rule:
    """The rule of a control: its text, and exact numbers when it is a plain one.

    kind is share (pass and partial are shares), count (pass, and perhaps partial,
    are counts), state (written out in `text` only) or manual.
    """

    kind: str
    text: str
    pass_: Threshold | None
    partial: Threshold | None


@dataclass(frozen=True)
class MappingRow:
    """One external framework identifier of a control.

    `uncertain` is the [U] marker: recalled with lower confidence. A row is shown
    in a report only when `verified` is true.
    """

    framework: str
    id: str
    verified: bool
    uncertain: bool


@dataclass(frozen=True)
class FieldTarget:
    adapter: str
    column: str


Param = int | str | tuple[int, ...] | tuple[str, ...]


@dataclass(frozen=True)
class Control:
    """One control. `params` are the numbers and words a rule uses besides its
    pass and partial thresholds (a window in days, a list of risky ports); the
    check engine reads them from here and holds none of its own.
    """

    id: str
    domain: str
    title: str
    weight: int
    gate: bool
    manual_only: bool
    max_age_days: MaxAge
    sources: tuple[str, ...]
    fields: tuple[str, ...]
    automatic_unavailable: str | None
    rule: Rule
    manual_alternative: bool
    artefact: str | None
    mappings: tuple[MappingRow, ...]
    params: Mapping[str, Param]

    def whole(self, name: str) -> int:
        """A whole-number parameter (KeyError when the control has none)."""
        value = self.params[name]
        if isinstance(value, int):
            return value
        raise KeyError(f"{self.id}: parameter {name} is not a whole number")

    def number(self, name: str) -> Decimal:
        """A parameter as an exact decimal (a whole number or a decimal text)."""
        value = self.params[name]
        if isinstance(value, int | str):
            return Decimal(value)
        raise KeyError(f"{self.id}: parameter {name} is not a number")

    def whole_list(self, name: str) -> tuple[int, ...]:
        value = self.params[name]
        if isinstance(value, tuple) and all(isinstance(item, int) for item in value):
            return cast(tuple[int, ...], value)
        raise KeyError(f"{self.id}: parameter {name} is not a list of numbers")

    def words(self, name: str) -> tuple[str, ...]:
        value = self.params[name]
        if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
            return cast(tuple[str, ...], value)
        raise KeyError(f"{self.id}: parameter {name} is not a list of words")


@dataclass(frozen=True)
class Library:
    """The whole control file, validated."""

    ruleset_id: str
    version: str
    manual_alternative_quality: Decimal
    attestation_quality: Decimal
    domains: tuple[Domain, ...]
    controls: tuple[Control, ...]
    field_map: Mapping[str, FieldTarget]
    unavailable: Mapping[str, str]
    source_codes: Mapping[str, str]
    populations: Mapping[str, str]

    def control(self, control_id: str) -> Control:
        for item in self.controls:
            if item.id == control_id:
                return item
        raise KeyError(control_id)

    def in_domain(self, code: str) -> tuple[Control, ...]:
        return tuple(item for item in self.controls if item.domain == code)

    @property
    def gates(self) -> tuple[Control, ...]:
        return tuple(item for item in self.controls if item.gate)

    @property
    def manual_only(self) -> tuple[Control, ...]:
        return tuple(item for item in self.controls if item.manual_only)

    @property
    def domain_weight_total(self) -> int:
        return sum(item.weight for item in self.domains)


def visible_mappings(control: Control) -> tuple[MappingRow, ...]:
    """The mapping rows a report may print: only those a person has verified.

    Anything that renders a control must take its external identifiers from here,
    so an identifier that nobody has checked against its source never reaches a
    client.
    """
    return tuple(row for row in control.mappings if row.verified)


def load_schema() -> dict[str, Any]:
    document = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ControlLibraryError(["controls.schema.json is not an object"])
    return cast(dict[str, Any], document)


def _duplicate_keys(node: Any, path: str = "") -> list[str]:
    """Keys written twice in one YAML mapping (safe_load would keep the last)."""
    found: list[str] = []
    if isinstance(node, yaml.MappingNode):
        seen: set[str] = set()
        for key_node, value_node in node.value:
            key = str(key_node.value)
            where = f"{path}/{key}"
            if key in seen:
                found.append(f"{where}: the key is written twice")
            seen.add(key)
            found.extend(_duplicate_keys(value_node, where))
    elif isinstance(node, yaml.SequenceNode):
        for index, item in enumerate(node.value):
            found.extend(_duplicate_keys(item, f"{path}/{index}"))
    return found


def parse_yaml(text: str) -> object:
    """Parse the YAML text, refusing a key that is written twice."""
    try:
        duplicates = _duplicate_keys(yaml.compose(text, Loader=yaml.SafeLoader))
        if duplicates:
            raise ControlLibraryError(duplicates)
        document: object = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ControlLibraryError([f"not readable YAML: {error}"]) from None
    return document


def _check_rule(control_id: str, rule: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    kind = rule["kind"]
    passing = rule.get("pass")
    partial = rule.get("partial")
    if kind == "share" and passing is not None and partial is not None:
        if Decimal(partial["at_least"]) >= Decimal(passing["at_least"]):
            problems.append(f"{control_id}: partial must be below pass")
    if kind == "count" and passing is not None and partial is not None:
        if partial["at_most"] <= passing["at_most"]:
            problems.append(f"{control_id}: partial must allow more than pass")
    return problems


def _check_control(
    control: Mapping[str, Any],
    domains: set[str],
    source_codes: set[str],
    declared: set[str],
    used: set[str],
) -> list[str]:
    problems: list[str] = []
    control_id: str = control["id"]
    domain: str = control["domain"]
    if control_id.split("-")[1] != domain:
        problems.append(f"{control_id}: the id does not match domain {domain}")
    if domain not in domains:
        problems.append(f"{control_id}: there is no domain {domain}")
    for code in control["sources"]:
        if code not in source_codes:
            problems.append(f"{control_id}: unknown source code {code}")
    for field_id in control["fields"]:
        used.add(field_id)
        if field_id not in declared:
            problems.append(f"{control_id}: orphan field {field_id}")
        elif field_id[0] not in control["sources"]:
            problems.append(f"{control_id}: {field_id} is not from one of its sources")
    rows = Counter((row["framework"], row["id"]) for row in control["mappings"])
    for (framework, identifier), count in sorted(rows.items()):
        if count > 1:
            problems.append(f"{control_id}: mapping {framework} {identifier} twice")
    problems.extend(_check_rule(control_id, control["rule"]))
    return problems


def cross_check(document: Mapping[str, Any]) -> list[str]:
    """The checks a schema cannot make: references, uniqueness and sums."""
    problems: list[str] = []
    domain_codes = [item["code"] for item in document["domains"]]
    for code, count in sorted(Counter(domain_codes).items()):
        if count > 1:
            problems.append(f"domain {code} is written twice")
    total = sum(item["weight"] for item in document["domains"])
    if total != 100:
        problems.append(f"the domain weights add up to {total}, not 100")
    field_map: Mapping[str, Any] = document["field_map"]
    unavailable: Mapping[str, Any] = document["unavailable"]
    for field_id in sorted(set(field_map) & set(unavailable)):
        problems.append(f"{field_id} is both mapped to a column and unavailable")
    declared = set(field_map) | set(unavailable)
    controls: list[Mapping[str, Any]] = document["controls"]
    for control_id, count in sorted(Counter(c["id"] for c in controls).items()):
        if count > 1:
            problems.append(f"control {control_id} is written twice")
    used: set[str] = set()
    source_codes = set(document["source_codes"])
    for control in controls:
        problems.extend(
            _check_control(control, set(domain_codes), source_codes, declared, used)
        )
    for field_id in sorted(declared - used):
        problems.append(f"{field_id} is read by no control")
    return problems


def validate_document(document: object) -> list[str]:
    """Every problem of a parsed control file; empty means valid."""
    problems = schema_problems(load_schema(), document)
    if problems:
        return problems
    return cross_check(cast(Mapping[str, Any], document))


def _threshold(raw: Mapping[str, Any] | None) -> Threshold | None:
    if raw is None:
        return None
    least = raw.get("at_least")
    return Threshold(
        at_least=Decimal(least) if least is not None else None,
        at_most=raw.get("at_most"),
    )


def _param(raw: object) -> Param:
    if isinstance(raw, list):
        if all(isinstance(item, int) for item in raw):
            return tuple(cast(list[int], raw))
        return tuple(cast(list[str], raw))
    return cast(int | str, raw)


def _control(raw: Mapping[str, Any]) -> Control:
    rule = raw["rule"]
    ages = raw["max_age_days"]
    return Control(
        id=raw["id"],
        domain=raw["domain"],
        title=raw["title"],
        weight=raw["weight"],
        gate=raw["gate"],
        manual_only=raw["manual_only"],
        max_age_days=MaxAge(ages["automatic"], ages["manual"]),
        sources=tuple(raw["sources"]),
        fields=tuple(raw["fields"]),
        automatic_unavailable=raw.get("automatic_unavailable"),
        rule=Rule(
            kind=rule["kind"],
            text=rule["text"],
            pass_=_threshold(rule.get("pass")),
            partial=_threshold(rule.get("partial")),
        ),
        manual_alternative=raw["manual_alternative"],
        artefact=raw.get("artefact"),
        mappings=tuple(
            MappingRow(
                framework=row["framework"],
                id=row["id"],
                verified=row["verified"],
                uncertain=row.get("uncertain", False),
            )
            for row in raw["mappings"]
        ),
        params={name: _param(value) for name, value in raw.get("params", {}).items()},
    )


def build_library(document: Mapping[str, Any]) -> Library:
    """The typed library of a document that passed validate_document."""
    ruleset = document["ruleset"]
    return Library(
        ruleset_id=ruleset["id"],
        version=ruleset["version"],
        manual_alternative_quality=Decimal(ruleset["manual_alternative_quality"]),
        attestation_quality=Decimal(ruleset["attestation_quality"]),
        domains=tuple(
            Domain(item["code"], item["name"], item["weight"])
            for item in document["domains"]
        ),
        controls=tuple(_control(raw) for raw in document["controls"]),
        field_map={
            field_id: FieldTarget(target["adapter"], target["column"])
            for field_id, target in document["field_map"].items()
        },
        unavailable=dict(document["unavailable"]),
        source_codes=dict(document["source_codes"]),
        populations=dict(document["populations"]),
    )


def load_library(path: Path = CONTROLS_PATH) -> Library:
    """Read, validate and build the control library.

    Raises ControlLibraryError, naming every problem, when the file is missing,
    is not YAML, breaks the schema or fails the cross-checks.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError) as error:
        raise ControlLibraryError([f"{path.name} cannot be read: {error}"]) from None
    document = parse_yaml(text)
    problems = validate_document(document)
    if problems:
        raise ControlLibraryError(problems)
    return build_library(cast(Mapping[str, Any], document))


def derived_field_list(library: Library) -> dict[str, Any]:
    """The field list the library implies, in the shape of tests/control_fields.yaml.

    `controls` maps a control id to the fields it reads, `fields` a field to its one
    adapter and column, `unavailable` a field no importer reads to the reason.
    """
    return {
        "controls": {item.id: list(item.fields) for item in library.controls},
        "fields": {
            field_id: {"adapter": target.adapter, "column": target.column}
            for field_id, target in library.field_map.items()
        },
        "unavailable": dict(library.unavailable),
    }


def count_problems(library: Library) -> list[str]:
    """Where the library does not have the numbers of rnd-report-3 section 3.4.

    51 controls in 8 domains whose weights add up to 100, 3 gates and 8
    manual-only controls. `revrook verify-controls` exits non-zero on any problem.
    """
    found = {
        "controls": len(library.controls),
        "domains": len(library.domains),
        "domain weights": library.domain_weight_total,
        "gates": len(library.gates),
        "manual-only controls": len(library.manual_only),
    }
    return [
        f"the library has {found[name]} {name}, not {expected}"
        for name, expected in EXPECTED_COUNTS.items()
        if found[name] != expected
    ]


def describe(library: Library) -> str:
    """One line of counts, for the command line and the end-to-end script."""
    gates = ", ".join(item.id for item in library.gates)
    total = library.domain_weight_total
    return (
        f"{library.ruleset_id} v{library.version}: "
        f"{len(library.controls)} controls, {len(library.domains)} domains, "
        f"domain weights {total}, {len(library.gates)} gates ({gates}), "
        f"{len(library.manual_only)} manual-only"
    )
