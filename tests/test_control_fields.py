"""Every field a control reads has a column in exactly one adapter (phase 4).

tests/control_fields.yaml lists, for each of the 51 controls of rnd-report-3
section 3.4, the fields its rule names, and which adapter column carries each. The
test cross-checks that list against the importers that are registered and fails on
an orphan: a field that a control names and that neither an adapter nor the list of
unavailable fields accounts for. Phase 5 must keep the list equal to
data/controls.yaml.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.checks.library import (
    CONTROLS_PATH,
    build_library,
    derived_field_list,
    load_library,
    parse_yaml,
    validate_document,
)
from app.importers.registry import build_default_registry
from tools import make_fixtures

MAX_ROWS = 1000
SPEC_PATH = Path(__file__).parent / "control_fields.yaml"
REASONS = {"licence_or_scope", "dnscheck", "shipped_list"}
CONTROL_ID = re.compile(r"PC-(?P<domain>[A-Z]{3})-\d\d")
CONTROLS_PER_DOMAIN = {
    "ACC": 8,
    "DEV": 7,
    "END": 5,
    "EML": 7,
    "BCK": 6,
    "NET": 5,
    "LOG": 6,
    "GOV": 7,
}
# Manual-only controls (section 3.4) read no field; PC-LOG-02 reads our own versioned
# table of log retention and a manual artefact.
READS_NO_FIELD = {
    "PC-ACC-08",
    "PC-EML-07",
    "PC-BCK-06",
    "PC-LOG-02",
    "PC-LOG-05",
    "PC-GOV-01",
    "PC-GOV-02",
    "PC-GOV-05",
    "PC-GOV-07",
}


class StrictLoader(yaml.SafeLoader):
    """A YAML loader that refuses a key written twice instead of keeping the last."""

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        twice = sorted({str(key) for key in keys if keys.count(key) > 1})
        if twice:
            raise yaml.constructor.ConstructorError(
                None, None, f"the key {twice[0]} is written twice", node.start_mark
            )
        return super().construct_mapping(node, deep)


def load_spec() -> dict[str, Any]:
    spec = yaml.load(SPEC_PATH.read_text(encoding="utf-8"), Loader=StrictLoader)
    assert isinstance(spec, dict)
    assert set(spec) == {"controls", "fields", "unavailable"}
    return spec


def provided_by() -> dict[str, set[str]]:
    """What each registered importer can carry.

    The column keys of an adapter that reads CSV; for a JSON-only source (it has no
    columns) the values its own fixture produces.
    """
    registry = build_default_registry()
    fixtures = [*make_fixtures.main_fixtures(), *make_fixtures.variant_fixtures()]
    found: dict[str, set[str]] = {}
    for code in registry.source_codes():
        importer = registry.get(code)
        assert importer is not None
        keys = {column.key for column in getattr(importer, "columns", ())}
        if not keys:
            for fixture in fixtures:
                if fixture.source_code == code:
                    for fact in importer.parse(fixture.data, MAX_ROWS).facts:
                        keys.update(fact.value)
        found[code] = keys
    return found


def find_problems(spec: dict[str, Any], provided: dict[str, set[str]]) -> list[str]:
    """Everything wrong with the list: orphans, missing columns, stale entries."""
    problems: list[str] = []
    controls = spec["controls"]
    fields = spec["fields"]
    unavailable = spec["unavailable"]
    for field_id in sorted(set(fields) & set(unavailable)):
        problems.append(f"{field_id} is both mapped to a column and unavailable")
    used: set[str] = set()
    for control, field_ids in controls.items():
        for field_id in field_ids:
            used.add(field_id)
            if field_id not in fields and field_id not in unavailable:
                problems.append(f"orphan field {field_id} of {control}")
    for field_id in sorted((set(fields) | set(unavailable)) - used):
        problems.append(f"{field_id} is read by no control")
    for field_id, target in fields.items():
        if set(target) != {"adapter", "column"}:
            problems.append(f"{field_id} must name exactly one adapter and one column")
        elif target["adapter"] not in provided:
            problems.append(f"{field_id}: no importer {target['adapter']}")
        elif target["column"] not in provided[target["adapter"]]:
            problems.append(
                f"{field_id}: {target['adapter']} has no column {target['column']}"
            )
    for field_id, reason in unavailable.items():
        if reason not in REASONS:
            problems.append(f"{field_id}: {reason!r} is not a known reason")
    return problems


def test_the_list_has_the_51_controls_of_the_eight_domains() -> None:
    controls = load_spec()["controls"]
    assert len(controls) == 51
    per_domain: dict[str, int] = {}
    for control in controls:
        match = CONTROL_ID.fullmatch(control)
        assert match is not None, control
        domain = match.group("domain")
        per_domain[domain] = per_domain.get(domain, 0) + 1
    assert per_domain == CONTROLS_PER_DOMAIN


def test_only_the_manual_controls_and_the_log_table_read_no_field() -> None:
    controls = load_spec()["controls"]
    empty = {name for name, field_ids in controls.items() if not field_ids}
    assert empty == READS_NO_FIELD


def test_every_field_of_a_control_has_a_column_in_exactly_one_adapter() -> None:
    assert find_problems(load_spec(), provided_by()) == []


def test_an_orphan_field_fails_the_cross_check() -> None:
    spec = load_spec()
    spec["controls"]["PC-NET-05"].append("N.invented_field")
    problems = find_problems(spec, provided_by())
    assert problems == ["orphan field N.invented_field of PC-NET-05"]


def test_a_mapped_field_whose_column_is_gone_fails_the_cross_check() -> None:
    spec = load_spec()
    spec["fields"]["R.dns_filter_active"]["column"] = "renamed_column"
    problems = find_problems(spec, provided_by())
    assert problems == [
        "R.dns_filter_active: device-inventory has no column renamed_column"
    ]
    spec = load_spec()
    spec["fields"]["R.dns_filter_active"]["adapter"] = "no-such-importer"
    assert find_problems(spec, provided_by()) == [
        "R.dns_filter_active: no importer no-such-importer"
    ]


def test_a_field_in_two_places_or_in_no_control_fails_the_cross_check() -> None:
    spec = load_spec()
    spec["unavailable"]["R.dns_filter_active"] = "licence_or_scope"
    assert find_problems(spec, provided_by()) == [
        "R.dns_filter_active is both mapped to a column and unavailable"
    ]
    spec = load_spec()
    spec["controls"]["PC-NET-05"] = []
    assert find_problems(spec, provided_by()) == [
        "R.dns_filter_active is read by no control"
    ]
    spec = load_spec()
    spec["fields"]["X.alert.kind"]["extra"] = "adapter"
    assert find_problems(spec, provided_by()) == [
        "X.alert.kind must name exactly one adapter and one column"
    ]
    spec = load_spec()
    spec["unavailable"]["D.spf"] = "because"
    problems = find_problems(spec, provided_by())
    assert problems == ["D.spf: 'because' is not a known reason"]


def test_a_key_written_twice_is_an_error_not_a_silent_override() -> None:
    text = "controls:\n  PC-ACC-01: []\n  PC-ACC-01: [G.x]\n"
    with pytest.raises(yaml.constructor.ConstructorError, match="written twice"):
        yaml.load(text, Loader=StrictLoader)


def test_every_unavailable_field_is_explained_in_the_importer_docs() -> None:
    docs = (Path(__file__).parent.parent / "docs" / "importers.md").read_text()
    for field_id in load_spec()["unavailable"]:
        assert f"`{field_id}`" in docs, field_id


# --- phase 5: the list must stay equal to data/controls.yaml -----------------------


def raw_controls() -> dict[str, Any]:
    document = parse_yaml(CONTROLS_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_the_field_list_equals_the_one_derived_from_controls_yaml() -> None:
    assert derived_field_list(load_library()) == load_spec()


def test_the_derived_field_list_passes_the_adapter_cross_check() -> None:
    assert find_problems(derived_field_list(load_library()), provided_by()) == []


def test_an_orphan_field_in_controls_yaml_is_refused_and_breaks_the_equality() -> None:
    document = raw_controls()
    for control in document["controls"]:
        if control["id"] == "PC-NET-05":
            control["fields"].append("N.invented_field")
    problems = validate_document(document)
    assert "PC-NET-05: orphan field N.invented_field" in problems
    derived = derived_field_list(build_library(document))
    assert derived != load_spec()
    assert find_problems(derived, provided_by()) == [
        "orphan field N.invented_field of PC-NET-05"
    ]


def test_a_changed_column_or_reason_in_controls_yaml_breaks_the_equality() -> None:
    document = raw_controls()
    document["field_map"]["R.dns_filter_active"]["column"] = "renamed_column"
    assert derived_field_list(build_library(document)) != load_spec()
    document = raw_controls()
    document["unavailable"]["G.securityAlerts"] = "dnscheck"
    assert derived_field_list(build_library(document)) != load_spec()
    document = raw_controls()
    for control in document["controls"]:
        if control["id"] == "PC-NET-05":
            control["fields"] = []
    assert derived_field_list(build_library(document)) != load_spec()
