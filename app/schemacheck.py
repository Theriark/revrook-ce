"""Validation of a document against a JSON Schema (draft 2020-12).

The one place that talks to the jsonschema package, so the strictly typed
packages (app.checks and the others) call a typed function of ours and never the
library directly.
"""

from typing import Any

from jsonschema import Draft202012Validator

MAX_PROBLEM_LENGTH = 300


def check_schema(schema: dict[str, Any]) -> None:
    """Raise an exception when the schema is not itself a valid schema."""
    Draft202012Validator.check_schema(schema)


def schema_problems(schema: dict[str, Any], document: object) -> list[str]:
    """Every way the document breaks the schema, as `where: message` lines.

    The list is sorted and each line is cut at 300 characters, so the same
    document always gives the same text and a huge value is never echoed whole.
    """
    validator = Draft202012Validator(schema)
    problems: list[str] = []
    for error in validator.iter_errors(document):
        where = "/".join(str(part) for part in error.absolute_path) or "(top level)"
        text = f"{where}: {error.message}"
        problems.append(text[:MAX_PROBLEM_LENGTH])
    return sorted(problems)
