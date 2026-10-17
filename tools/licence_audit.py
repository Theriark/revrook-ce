"""SPDX allow-list licence audit for installed Python distributions (check 6).

Reads the metadata of every distribution on the given paths (default: the
running interpreter, transitive packages included) and fails on anything outside
the allow-list. LGPL, GPL, AGPL, SSPL and unknown licences all fail.

Where a package declares its licence ambiguously (for example the generic
"BSD License" classifier) the audit fails and a reviewer records the identifier
found in the package's LICENSE file in licence-exceptions.txt, one line per
package: ``name | SPDX expression | reason``. A recorded line only resolves the
declaration; the resolved expression is still checked against the allow-list,
so an exception can never admit a disallowed licence.
"""

import argparse
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

ALLOWED = frozenset(
    {
        "MIT",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "Apache-2.0",
        "ISC",
        "PSF-2.0",
        "Python-2.0",
        "CNRI-Python",
        "0BSD",
        "Unlicense",
        "CC0-1.0",
    }
)
# Allowed for development packages only (--allow-mpl-dev).
MPL = "MPL-2.0"
CANONICAL = {name.lower(): name for name in ALLOWED | {MPL}}

# Legacy values of the free-text License field.
ALIASES = {
    "mit license": "MIT",
    "apache software license": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "isc license": "ISC",
    "isc license (iscl)": "ISC",
    "python software foundation license": "PSF-2.0",
    "the unlicense (unlicense)": "Unlicense",
}

# Last segment of "License :: ..." trove classifiers. The generic "BSD License"
# does not say which clause and is deliberately unresolved. "Apache Software
# License" is taken as Apache-2.0, the only Apache version in practice.
CLASSIFIERS = {
    "MIT License": "MIT",
    "BSD License": "BSD-UNSPECIFIED",
    "Apache Software License": "Apache-2.0",
    "ISC License (ISCL)": "ISC",
    "Python Software Foundation License": "PSF-2.0",
    "The Unlicense (Unlicense)": "Unlicense",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "Creative Commons CC0 1.0 Universal (CC0 1.0) Public Domain Dedication": "CC0-1.0",
    "GNU Lesser General Public License v2 (LGPLv2)": "LGPL-2.0-only",
    "GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.0-or-later",
    "GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    "GNU Lesser General Public License v3 or later (LGPLv3+)": "LGPL-3.0-or-later",
    "GNU Library or Lesser General Public License (LGPL)": "LGPL-UNSPECIFIED",
    "GNU General Public License (GPL)": "GPL-UNSPECIFIED",
    "GNU General Public License v2 (GPLv2)": "GPL-2.0-only",
    "GNU General Public License v2 or later (GPLv2+)": "GPL-2.0-or-later",
    "GNU General Public License v3 (GPLv3)": "GPL-3.0-only",
    "GNU General Public License v3 or later (GPLv3+)": "GPL-3.0-or-later",
    "GNU Affero General Public License v3": "AGPL-3.0-only",
    "GNU Affero General Public License v3 or later (AGPLv3+)": "AGPL-3.0-or-later",
}

TOKEN = re.compile(r"\(|\)|[^\s()]+")
RESERVED = {"AND", "OR", "WITH"}


@dataclass(frozen=True)
class Finding:
    """A distribution whose licence is not on the allow-list."""

    name: str
    version: str
    expression: str
    source: str


class _Evaluator:
    """Evaluates an SPDX expression: OR needs one allowed side, AND needs both."""

    def __init__(self, text: str, is_allowed: Callable[[str], bool]) -> None:
        self.tokens = TOKEN.findall(text)
        self.position = 0
        self.is_allowed = is_allowed

    def _peek(self) -> str | None:
        if self.position < len(self.tokens):
            return self.tokens[self.position]
        return None

    def _take(self) -> str:
        token = self._peek()
        if token is None:
            raise ValueError("unexpected end of expression")
        self.position += 1
        return token

    def _is_operator(self, word: str) -> bool:
        token = self._peek()
        return token is not None and token.upper() == word

    def evaluate(self) -> bool:
        result = self._or()
        if self._peek() is not None:
            raise ValueError(f"unexpected token {self._peek()!r}")
        return result

    def _or(self) -> bool:
        result = self._and()
        while self._is_operator("OR"):
            self._take()
            right = self._and()
            result = result or right
        return result

    def _and(self) -> bool:
        result = self._atom()
        while self._is_operator("AND"):
            self._take()
            right = self._atom()
            result = result and right
        return result

    def _atom(self) -> bool:
        token = self._take()
        if token == "(":
            result = self._or()
            if self._take() != ")":
                raise ValueError("expected a closing parenthesis")
            return result
        if token == ")" or token.upper() in RESERVED:
            raise ValueError(f"unexpected token {token!r}")
        if self._is_operator("WITH"):
            self._take()
            self._take()
        return self.is_allowed(token)


def is_allowed_expression(expression: str, allow_mpl: bool = False) -> bool:
    """True when the SPDX expression satisfies the allow-list.

    Raises ValueError when the expression cannot be parsed.
    """

    def is_allowed(identifier: str) -> bool:
        canonical = CANONICAL.get(identifier.lower())
        if canonical is None:
            return False
        return canonical != MPL or allow_mpl

    return _Evaluator(expression, is_allowed).evaluate()


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def load_exceptions(path: Path) -> dict[str, tuple[str, str]]:
    """Read recorded exceptions: ``name | SPDX expression | reason`` per line."""
    if not path.is_file():
        return {}
    exceptions: dict[str, tuple[str, str]] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        parts = [part.strip() for part in text.split("|")]
        if len(parts) != 3 or not all(parts):
            raise ValueError(
                f"{path}:{number}: expected 'name | SPDX expression | reason'"
            )
        exceptions[normalise(parts[0])] = (parts[1], parts[2])
    return exceptions


def _parses(expression: str) -> bool:
    try:
        _Evaluator(expression, lambda _: False).evaluate()
    except ValueError:
        return False
    return True


def declared_licence(
    meta: metadata.PackageMetadata,
    exceptions: Mapping[str, tuple[str, str]],
) -> tuple[str, str]:
    """Return (SPDX expression, where it came from) for one distribution."""
    recorded = exceptions.get(normalise(meta["Name"]))
    if recorded is not None:
        return recorded[0], f"recorded exception ({recorded[1]})"

    expression = (meta.get("License-Expression") or "").strip()
    if expression:
        return expression, "License-Expression"

    legacy = (meta.get("License") or "").strip()
    if legacy and "\n" not in legacy and len(legacy) <= 120 and legacy != "UNKNOWN":
        candidate = ALIASES.get(legacy.lower(), legacy)
        if _parses(candidate):
            return candidate, "License field"

    tails = [
        classifier.split(" :: ")[-1]
        for classifier in meta.get_all("Classifier") or []
        if classifier.startswith("License ::")
    ]
    tails = [tail for tail in tails if tail != "OSI Approved"]
    if tails:
        mapped = [CLASSIFIERS.get(tail, "UNRECOGNISED") for tail in tails]
        return " AND ".join(mapped), "classifier " + "; ".join(tails)
    return "UNKNOWN", "no licence metadata"


def audit(
    distributions: Iterable[metadata.Distribution],
    allow_mpl: bool = False,
    exceptions: Mapping[str, tuple[str, str]] | None = None,
) -> tuple[int, list[Finding]]:
    """Return (distributions checked, findings). No findings means a pass."""
    recorded = exceptions or {}
    seen: set[str] = set()
    findings: list[Finding] = []
    for distribution in distributions:
        meta = distribution.metadata
        name = meta["Name"]
        if name is None or normalise(name) in seen:
            continue
        seen.add(normalise(name))
        expression, source = declared_licence(meta, recorded)
        try:
            allowed = is_allowed_expression(expression, allow_mpl)
        except ValueError:
            allowed = False
        if not allowed:
            findings.append(Finding(name, distribution.version, expression, source))
    return len(seen), findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SPDX allow-list licence audit")
    parser.add_argument(
        "--path",
        action="append",
        help="directory holding *.dist-info metadata (repeatable; default: sys.path)",
    )
    parser.add_argument(
        "--allow-mpl-dev",
        action="store_true",
        help="allow MPL-2.0 (for a development environment only)",
    )
    parser.add_argument(
        "--exceptions",
        default="licence-exceptions.txt",
        help="recorded exceptions file (default: %(default)s; may be absent)",
    )
    args = parser.parse_args(argv)

    try:
        exceptions = load_exceptions(Path(args.exceptions))
    except ValueError as error:
        print(f"licence audit: {error}", file=sys.stderr)
        return 2

    if args.path:
        distributions = metadata.distributions(path=args.path)
    else:
        distributions = metadata.distributions()
    checked, findings = audit(distributions, args.allow_mpl_dev, exceptions)

    print(f"licence audit: {checked} distributions checked")
    for finding in findings:
        print(
            f"FAIL {finding.name} {finding.version}: {finding.expression} "
            f"({finding.source})"
        )
    if findings:
        print(f"licence audit: {len(findings)} disallowed or unknown licence(s)")
        return 1
    print("licence audit: passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
