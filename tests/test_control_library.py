"""The control library file: structure, counts and cross-references (phase 5, part 1).

data/controls.yaml holds the 51 controls of rnd-report-3 section 3.4. These tests
read the real file, check the numbers the report gives (51 controls, 8 domains,
weights adding up to 100, 3 gates, 8 manual-only controls) and prove that a file
that breaks the schema or a cross-reference is refused with the problem named.
"""

import copy
import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app import schemacheck
from app.checks.library import (
    CONTROLS_PATH,
    ControlLibraryError,
    Library,
    build_library,
    describe,
    load_library,
    load_schema,
    parse_yaml,
    validate_document,
    visible_mappings,
)

MANUAL_ONLY = {
    "PC-ACC-08",
    "PC-EML-07",
    "PC-BCK-06",
    "PC-LOG-05",
    "PC-GOV-01",
    "PC-GOV-02",
    "PC-GOV-05",
    "PC-GOV-07",
}
GATES = ["PC-ACC-01", "PC-ACC-02", "PC-BCK-01"]
# domain: (domain weight, number of controls, sum of the control weights)
DOMAINS = {
    "ACC": (22, 8, 17),
    "DEV": (14, 7, 15),
    "END": (10, 5, 10),
    "EML": (12, 7, 13),
    "BCK": (16, 6, 13),
    "NET": (6, 5, 8),
    "LOG": (8, 6, 11),
    "GOV": (12, 7, 12),
}
# Controls whose automatic measure CE cannot compute (a licence tier, a permission
# outside the verified list, or no importer): unknown, licence_or_scope.
AUTOMATIC_UNAVAILABLE = {
    "PC-ACC-06",
    "PC-ACC-07",
    "PC-BCK-02",
    "PC-DEV-06",
    "PC-END-03",
    "PC-END-05",
    "PC-GOV-06",
}
UNREADABLE_REASONS = {"licence_or_scope", "shipped_list"}
FRAMEWORKS = {"csf", "sp800-171", "cis", "iso27001", "cyber-essentials", "nis2"}
EXTERNAL_TEXT = re.compile(r"\b(CIS|ISO|SCF|CCM|SIG)\b")


def raw_document() -> dict[str, Any]:
    document = parse_yaml(CONTROLS_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def control_of(document: dict[str, Any], control_id: str) -> dict[str, Any]:
    for control in document["controls"]:
        if control["id"] == control_id:
            assert isinstance(control, dict)
            return control
    raise AssertionError(control_id)


def problems_after(change: Callable[[dict[str, Any]], None]) -> list[str]:
    document = raw_document()
    change(document)
    return validate_document(document)


@pytest.fixture(scope="module")
def library() -> Library:
    return load_library()


def test_the_file_has_51_controls_in_8_domains_with_weights_adding_up_to_100(
    library: Library,
) -> None:
    assert len(library.controls) == 51
    assert len(library.domains) == 8
    assert library.domain_weight_total == 100
    assert [item.code for item in library.domains] == list(DOMAINS)
    for domain in library.domains:
        weight, count, control_weights = DOMAINS[domain.code]
        controls = library.in_domain(domain.code)
        assert domain.weight == weight, domain.code
        assert len(controls) == count, domain.code
        assert sum(item.weight for item in controls) == control_weights, domain.code


def test_three_gates_and_eight_manual_only_controls(library: Library) -> None:
    assert [item.id for item in library.gates] == GATES
    assert {item.id for item in library.manual_only} == MANUAL_ONLY
    assert len(library.controls) - len(library.manual_only) == 43


def test_control_ids_run_from_01_in_each_domain_and_are_unique(
    library: Library,
) -> None:
    ids = [item.id for item in library.controls]
    assert len(set(ids)) == 51
    for code, (_, count, _) in DOMAINS.items():
        expected = [f"PC-{code}-{number:02d}" for number in range(1, count + 1)]
        assert [item.id for item in library.in_domain(code)] == expected


def test_the_ruleset_is_pc_rules_0_1_and_a_manual_artefact_scores_0_9(
    library: Library,
) -> None:
    assert library.ruleset_id == "PC-RULES"
    assert library.version == "0.1"
    assert library.manual_alternative_quality == Decimal("0.9")
    assert set(library.source_codes) == set("GXRBNDTHM")
    assert set(library.populations) == {"U", "A", "DV"}


def test_weights_ages_and_thresholds_follow_the_report(library: Library) -> None:
    first = library.control("PC-ACC-01")
    assert (first.weight, first.gate) == (3, True)
    assert (first.max_age_days.automatic, first.max_age_days.manual) == (35, 365)
    assert first.rule.kind == "share"
    assert first.rule.pass_ is not None and first.rule.partial is not None
    assert first.rule.pass_.at_least == Decimal("0.98")
    assert first.rule.partial.at_least == Decimal("0.80")
    assert library.control("PC-BCK-03").max_age_days.manual == 100
    assert library.control("PC-BCK-03").max_age_days.automatic == 100
    assert library.control("PC-DEV-02").max_age_days.automatic == 7
    assert library.control("PC-DEV-02").max_age_days.manual is None
    assert library.control("PC-LOG-05").max_age_days.manual == 35
    assert library.control("PC-LOG-05").max_age_days.automatic is None
    admin = library.control("PC-ACC-02")
    assert admin.rule.kind == "count"
    assert admin.rule.pass_ is not None and admin.rule.pass_.at_most == 0
    assert admin.rule.partial is None
    alerts = library.control("PC-END-03")
    assert alerts.rule.partial is not None and alerts.rule.partial.at_most == 2
    kinds = [item.rule.kind for item in library.controls]
    assert {kind: kinds.count(kind) for kind in set(kinds)} == {
        "share": 16,
        "count": 6,
        "state": 21,
        "manual": 8,
    }


def test_manual_only_controls_name_an_artefact_and_the_rest_accept_one(
    library: Library,
) -> None:
    for item in library.controls:
        if item.manual_only:
            assert item.artefact, item.id
            assert not item.manual_alternative, item.id
            assert item.fields == (), item.id
            assert item.max_age_days.automatic is None, item.id
            assert item.rule.kind == "manual", item.id
            assert item.sources == ("M",), item.id
            assert not item.gate, item.id
        else:
            assert item.artefact is None, item.id
            assert item.manual_alternative, item.id
            assert item.max_age_days.automatic is not None, item.id


def test_a_control_without_a_readable_field_is_unknown_with_licence_or_scope(
    library: Library,
) -> None:
    flagged = {
        item.id for item in library.controls if item.automatic_unavailable is not None
    }
    assert flagged == AUTOMATIC_UNAVAILABLE
    for item in library.controls:
        if item.automatic_unavailable is not None:
            assert item.automatic_unavailable == "licence_or_scope", item.id
            assert not item.manual_only, item.id
            reasons = {library.unavailable.get(field_id) for field_id in item.fields}
            assert reasons & UNREADABLE_REASONS, item.id
        elif item.fields and all(
            library.unavailable.get(field_id) in UNREADABLE_REASONS
            for field_id in item.fields
        ):
            raise AssertionError(f"{item.id} reads no field but is not flagged")


def test_external_frameworks_are_identifiers_only_and_unverified(
    library: Library,
) -> None:
    rows = [row for item in library.controls for row in item.mappings]
    assert len(rows) > 200
    assert {row.framework for row in rows} == FRAMEWORKS
    assert all(row.id and not row.verified for row in rows)
    assert any(row.uncertain for row in rows)
    for item in library.controls:
        assert visible_mappings(item) == (), item.id


def test_a_mapping_row_is_visible_only_once_it_is_verified() -> None:
    document = raw_document()
    row = control_of(document, "PC-ACC-01")["mappings"][0]
    row["verified"] = True
    assert validate_document(document) == []
    changed = build_library(document)
    shown = visible_mappings(changed.control("PC-ACC-01"))
    assert [(item.framework, item.id) for item in shown] == [("csf", "PR.AA-03")]
    assert visible_mappings(changed.control("PC-ACC-02")) == ()


def test_no_text_of_a_licensed_framework_is_embedded(library: Library) -> None:
    for item in library.controls:
        texts = [item.title, item.rule.text, item.artefact or ""]
        for text in texts:
            assert not EXTERNAL_TEXT.search(text), (item.id, text)


def test_the_json_schema_is_itself_valid() -> None:
    schemacheck.check_schema(load_schema())


def test_the_real_file_passes_the_schema_and_the_cross_checks() -> None:
    assert validate_document(raw_document()) == []


def add_orphan(document: dict[str, Any]) -> None:
    control_of(document, "PC-ACC-01")["fields"].append("G.invented")


def duplicate_control(document: dict[str, Any]) -> None:
    document["controls"].append(copy.deepcopy(document["controls"][0]))


def heavier_domain(document: dict[str, Any]) -> None:
    document["domains"][0]["weight"] += 1


def unread_field(document: dict[str, Any]) -> None:
    document["field_map"]["R.extra"] = {"adapter": "device-inventory", "column": "x"}


def field_twice(document: dict[str, Any]) -> None:
    document["unavailable"]["G.isAdmin"] = "dnscheck"


def wrong_domain(document: dict[str, Any]) -> None:
    control_of(document, "PC-ACC-01")["domain"] = "ZZZ"


def foreign_source(document: dict[str, Any]) -> None:
    control_of(document, "PC-ACC-01")["sources"] = ["M"]


def partial_above_pass(document: dict[str, Any]) -> None:
    control_of(document, "PC-ACC-01")["rule"]["partial"]["at_least"] = "0.99"


def partial_count_not_above_pass(document: dict[str, Any]) -> None:
    control_of(document, "PC-END-03")["rule"]["partial"]["at_most"] = 0


def share_too_precise(document: dict[str, Any]) -> None:
    control_of(document, "PC-ACC-01")["rule"]["pass"]["at_least"] = "0.999999"


def extra_key(document: dict[str, Any]) -> None:
    control_of(document, "PC-ACC-01")["colour"] = "red"


def manual_control_reads_a_field(document: dict[str, Any]) -> None:
    control_of(document, "PC-ACC-08")["fields"] = ["G.isAdmin"]


def automatic_without_alternative(document: dict[str, Any]) -> None:
    control_of(document, "PC-ACC-01")["manual_alternative"] = False


def share_without_partial(document: dict[str, Any]) -> None:
    del control_of(document, "PC-ACC-01")["rule"]["partial"]


def state_with_a_threshold(document: dict[str, Any]) -> None:
    control_of(document, "PC-ACC-03")["rule"]["pass"] = {"at_most": 0}


def unknown_framework(document: dict[str, Any]) -> None:
    control_of(document, "PC-ACC-01")["mappings"][0]["framework"] = "iso27002"


def missing_section(document: dict[str, Any]) -> None:
    del document["unavailable"]


def duplicate_mapping(document: dict[str, Any]) -> None:
    rows = control_of(document, "PC-ACC-01")["mappings"]
    rows.append(copy.deepcopy(rows[0]))


def weight_four(document: dict[str, Any]) -> None:
    control_of(document, "PC-ACC-01")["weight"] = 4


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (add_orphan, "PC-ACC-01: orphan field G.invented"),
        (duplicate_control, "control PC-ACC-01 is written twice"),
        (heavier_domain, "the domain weights add up to 101, not 100"),
        (unread_field, "R.extra is read by no control"),
        (field_twice, "G.isAdmin is both mapped to a column and unavailable"),
        (wrong_domain, "PC-ACC-01: the id does not match domain ZZZ"),
        (foreign_source, "G.isMfaRegistered is not from one of its sources"),
        (partial_above_pass, "PC-ACC-01: partial must be below pass"),
        (partial_count_not_above_pass, "PC-END-03: partial must allow more"),
        (share_too_precise, "controls/0/rule/pass/at_least"),
        (extra_key, "Additional properties are not allowed ('colour'"),
        (manual_control_reads_a_field, "controls/7/fields"),
        (automatic_without_alternative, "controls/0/manual_alternative"),
        (share_without_partial, "'partial' is a required property"),
        (state_with_a_threshold, "controls/2/rule"),
        (unknown_framework, "'iso27002' is not one of"),
        (missing_section, "'unavailable' is a required property"),
        (duplicate_mapping, "PC-ACC-01: mapping csf PR.AA-03 twice"),
        (weight_four, "controls/0/weight"),
    ],
)
def test_a_file_that_breaks_a_rule_is_refused_with_the_problem_named(
    change: Callable[[dict[str, Any]], None], expected: str
) -> None:
    problems = problems_after(change)
    assert any(expected in problem for problem in problems), problems


def test_a_key_written_twice_is_refused_and_not_silently_overridden(
    tmp_path: Path,
) -> None:
    path = tmp_path / "controls.yaml"
    path.write_text("ruleset: {}\nruleset: {}\n", encoding="utf-8")
    with pytest.raises(ControlLibraryError, match="/ruleset: the key is written twice"):
        load_library(path)


def test_a_missing_or_unreadable_file_is_a_named_error(tmp_path: Path) -> None:
    with pytest.raises(ControlLibraryError, match="missing.yaml cannot be read"):
        load_library(tmp_path / "missing.yaml")
    broken = tmp_path / "broken.yaml"
    broken.write_text("controls: [\n", encoding="utf-8")
    with pytest.raises(ControlLibraryError, match="not readable YAML"):
        load_library(broken)
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ControlLibraryError, match="is not of type 'object'"):
        load_library(empty)


def test_every_problem_is_listed_and_the_message_is_short() -> None:
    document = raw_document()
    for control in document["controls"]:
        control["weight"] = 9
    problems = validate_document(document)
    assert len(problems) >= 51
    error = ControlLibraryError(problems)
    assert error.problems == problems
    assert str(error).endswith(f"and {len(problems) - 10} more")


def test_the_description_line_gives_the_counts(library: Library) -> None:
    assert describe(library) == (
        "PC-RULES v0.1: 51 controls, 8 domains, domain weights 100, "
        "3 gates (PC-ACC-01, PC-ACC-02, PC-BCK-01), 8 manual-only"
    )
