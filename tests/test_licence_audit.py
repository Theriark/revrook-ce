from collections.abc import Sequence
from importlib import metadata
from pathlib import Path

import pytest

from tools import licence_audit


def write_distribution(
    root: Path,
    name: str,
    version: str = "1.0",
    *,
    expression: str | None = None,
    licence: str | None = None,
    classifiers: Sequence[str] = (),
) -> None:
    """Write fake installed-package metadata (a .dist-info directory)."""
    info = root / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir()
    lines = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}"]
    if expression:
        lines.append(f"License-Expression: {expression}")
    if licence:
        lines.append(f"License: {licence}")
    lines.extend(f"Classifier: {classifier}" for classifier in classifiers)
    (info / "METADATA").write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit_path(
    root: Path, **kwargs: object
) -> tuple[int, list[licence_audit.Finding]]:
    return licence_audit.audit(metadata.distributions(path=[str(root)]), **kwargs)  # type: ignore[arg-type]


def test_permissive_packages_pass(tmp_path: Path) -> None:
    write_distribution(tmp_path, "mit-pkg", expression="MIT")
    write_distribution(tmp_path, "legacy-apache", licence="Apache Software License")
    write_distribution(
        tmp_path, "classifier-only", classifiers=["License :: OSI Approved :: MIT License"]
    )
    write_distribution(tmp_path, "dual", expression="Apache-2.0 OR BSD-3-Clause")
    checked, findings = audit_path(tmp_path)
    assert checked == 4
    assert findings == []


def test_a_fake_lgpl_package_fails(tmp_path: Path) -> None:
    write_distribution(tmp_path, "mit-pkg", expression="MIT")
    write_distribution(tmp_path, "fake-lgpl", expression="LGPL-3.0-or-later")
    checked, findings = audit_path(tmp_path)
    assert checked == 2
    assert [finding.name for finding in findings] == ["fake-lgpl"]
    assert findings[0].expression == "LGPL-3.0-or-later"


def test_lgpl_declared_only_by_classifier_fails(tmp_path: Path) -> None:
    write_distribution(
        tmp_path,
        "fake-lgpl-classifier",
        classifiers=[
            "License :: OSI Approved :: "
            "GNU Lesser General Public License v3 (LGPLv3)"
        ],
    )
    _, findings = audit_path(tmp_path)
    assert [finding.name for finding in findings] == ["fake-lgpl-classifier"]


@pytest.mark.parametrize(
    "expression",
    [
        "GPL-3.0-only",
        "AGPL-3.0-or-later",
        "SSPL-1.0",
        "LGPL-2.1-only",
        "GPL-2.0-only WITH Classpath-exception-2.0",
        "LicenseRef-Proprietary",
    ],
)
def test_copyleft_and_unknown_licences_fail(tmp_path: Path, expression: str) -> None:
    write_distribution(tmp_path, "bad-pkg", expression=expression)
    _, findings = audit_path(tmp_path)
    assert len(findings) == 1


def test_a_package_without_licence_metadata_fails(tmp_path: Path) -> None:
    write_distribution(tmp_path, "mystery")
    _, findings = audit_path(tmp_path)
    assert [finding.expression for finding in findings] == ["UNKNOWN"]


def test_long_licence_text_in_the_licence_field_is_ignored(tmp_path: Path) -> None:
    write_distribution(
        tmp_path,
        "full-text",
        licence="Permission is hereby granted " * 20,
        classifiers=["License :: OSI Approved :: MIT License"],
    )
    _, findings = audit_path(tmp_path)
    assert findings == []


def test_the_generic_bsd_classifier_is_unresolved(tmp_path: Path) -> None:
    write_distribution(
        tmp_path, "bsd-pkg", classifiers=["License :: OSI Approved :: BSD License"]
    )
    _, findings = audit_path(tmp_path)
    assert [finding.name for finding in findings] == ["bsd-pkg"]


def test_a_recorded_exception_resolves_an_ambiguous_declaration(
    tmp_path: Path,
) -> None:
    write_distribution(
        tmp_path, "bsd-pkg", classifiers=["License :: OSI Approved :: BSD License"]
    )
    recorded = {"bsd-pkg": ("BSD-3-Clause", "LICENSE file read 2026-10-17")}
    _, findings = audit_path(tmp_path, exceptions=recorded)
    assert findings == []


def test_a_recorded_exception_cannot_admit_a_disallowed_licence(
    tmp_path: Path,
) -> None:
    write_distribution(tmp_path, "gpl-pkg", expression="MIT")
    recorded = {"gpl-pkg": ("GPL-3.0-only", "wrongly recorded")}
    _, findings = audit_path(tmp_path, exceptions=recorded)
    assert [finding.name for finding in findings] == ["gpl-pkg"]


def test_mpl_is_allowed_only_for_development_packages(tmp_path: Path) -> None:
    write_distribution(tmp_path, "mpl-pkg", expression="MPL-2.0")
    assert len(audit_path(tmp_path)[1]) == 1
    assert audit_path(tmp_path, allow_mpl=True)[1] == []


def test_a_package_seen_twice_is_counted_once(tmp_path: Path) -> None:
    write_distribution(tmp_path, "twice", version="1.0", expression="MIT")
    write_distribution(tmp_path, "twice", version="2.0", expression="MIT")
    checked, findings = audit_path(tmp_path)
    assert checked == 1
    assert findings == []


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("MIT", True),
        ("mit", True),
        ("Apache-2.0 OR BSD-3-Clause", True),
        ("MIT OR GPL-3.0-only", True),
        ("MIT AND GPL-3.0-only", False),
        ("MIT AND PSF-2.0", True),
        ("(MIT OR LGPL-3.0-only) AND BSD-3-Clause", True),
        ("(GPL-3.0-only OR LGPL-3.0-only) AND MIT", False),
        ("Apache-2.0 WITH LLVM-exception", True),
        ("MPL-2.0", False),
        ("0BSD", True),
        ("LicenseRef-Proprietary", False),
    ],
)
def test_expression_evaluation(expression: str, expected: bool) -> None:
    assert licence_audit.is_allowed_expression(expression) is expected


@pytest.mark.parametrize("expression", ["MIT AND", "(MIT", "MIT BSD-3-Clause", "OR MIT", ")"])
def test_malformed_expressions_raise(expression: str) -> None:
    with pytest.raises(ValueError):
        licence_audit.is_allowed_expression(expression)


def test_exceptions_file_is_parsed(tmp_path: Path) -> None:
    path = tmp_path / "licence-exceptions.txt"
    path.write_text(
        "# comment\n\nSome_Package | BSD-3-Clause | LICENSE read 2026-10-17\n",
        encoding="utf-8",
    )
    assert licence_audit.load_exceptions(path) == {
        "some-package": ("BSD-3-Clause", "LICENSE read 2026-10-17")
    }
    assert licence_audit.load_exceptions(tmp_path / "absent.txt") == {}


@pytest.mark.parametrize("line", ["name only", "a | b", "a | | reason", "a | b | c | d"])
def test_malformed_exceptions_lines_are_rejected(tmp_path: Path, line: str) -> None:
    path = tmp_path / "licence-exceptions.txt"
    path.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected"):
        licence_audit.load_exceptions(path)


def test_main_exits_one_and_names_the_package_when_lgpl_is_present(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_distribution(tmp_path, "fake-lgpl", expression="LGPL-3.0-or-later")
    code = licence_audit.main(["--path", str(tmp_path), "--exceptions", "absent.txt"])
    output = capsys.readouterr().out
    assert code == 1
    assert "FAIL fake-lgpl 1.0: LGPL-3.0-or-later" in output


def test_main_exits_zero_for_a_clean_environment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_distribution(tmp_path, "mit-pkg", expression="MIT")
    code = licence_audit.main(["--path", str(tmp_path), "--exceptions", "absent.txt"])
    assert code == 0
    assert "licence audit: passed" in capsys.readouterr().out


def test_main_honours_allow_mpl_dev_and_the_exceptions_file(
    tmp_path: Path,
) -> None:
    write_distribution(tmp_path, "mpl-pkg", expression="MPL-2.0")
    write_distribution(
        tmp_path, "bsd-pkg", classifiers=["License :: OSI Approved :: BSD License"]
    )
    exceptions = tmp_path / "exceptions.txt"
    exceptions.write_text("bsd-pkg | BSD-3-Clause | LICENSE read\n", encoding="utf-8")
    base = ["--path", str(tmp_path), "--exceptions", str(exceptions)]
    assert licence_audit.main(base) == 1
    assert licence_audit.main([*base, "--allow-mpl-dev"]) == 0


def test_main_rejects_a_malformed_exceptions_file(tmp_path: Path) -> None:
    exceptions = tmp_path / "exceptions.txt"
    exceptions.write_text("broken line\n", encoding="utf-8")
    assert licence_audit.main(["--exceptions", str(exceptions)]) == 2
