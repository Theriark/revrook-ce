"""The reference importer: a small user list that proves the whole pipeline.

Phase 2 ships it so that the evidence store, the pseudonymisation and the
end-to-end script can run an upload through the API before the real source
adapters exist (phase 3). It reads a CSV with two columns:

    user_principal_name,mfa_registered

and produces one fact per user (the flag only; the name becomes a pseudonym in
the evidence store) and one summary fact with the counts.
"""

import csv
import io

from app.importers.base import ImportRejectedError, ParsedFact, ParseResult

USER_COLUMN = "user_principal_name"
FLAG_COLUMN = "mfa_registered"
TRUE_WORDS = frozenset({"true", "yes", "1"})
FALSE_WORDS = frozenset({"false", "no", "0"})


class ReferenceCsvImporter:
    """CSV of users with an MFA flag (reference source, not a product source)."""

    source_code = "reference-csv"
    version = "reference-1"

    def parse(self, data: bytes, max_rows: int) -> ParseResult:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ImportRejectedError("The file is not UTF-8 text.") from None
        reader = csv.DictReader(io.StringIO(text, newline=""))
        try:
            columns = reader.fieldnames or []
            missing = [
                name for name in (USER_COLUMN, FLAG_COLUMN) if name not in columns
            ]
            if missing:
                raise ImportRejectedError(
                    "The file is missing the column " + ", ".join(missing) + "."
                )
            facts: list[ParsedFact] = []
            registered = 0
            for number, row in enumerate(reader, start=1):
                if number > max_rows:
                    raise ImportRejectedError(
                        f"The file has more than {max_rows} rows."
                    )
                user = (row.get(USER_COLUMN) or "").strip()
                flag = (row.get(FLAG_COLUMN) or "").strip().lower()
                if not user:
                    raise ImportRejectedError(f"Row {number} has no {USER_COLUMN}.")
                if flag in TRUE_WORDS:
                    is_registered = True
                elif flag in FALSE_WORDS:
                    is_registered = False
                else:
                    raise ImportRejectedError(
                        f"Row {number}: {FLAG_COLUMN} must be true or false."
                    )
                registered += is_registered
                facts.append(
                    ParsedFact(
                        key="reference.user",
                        value={"mfa_registered": is_registered},
                        identifiers={"user": user},
                    )
                )
        except csv.Error:
            raise ImportRejectedError("The file is not a readable CSV file.") from None
        facts.append(
            ParsedFact(
                key="reference.summary",
                value={"users": len(facts), "mfa_registered": registered},
            )
        )
        return ParseResult(facts=tuple(facts))
