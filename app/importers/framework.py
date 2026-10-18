"""The shared parts of the source adapters (phase 3).

What every adapter needs, written once:

* reading text (BOM, UTF-16, charset detection) and CSV (rows are read one at a
  time from the text in memory, which the evidence store has already limited to
  20 MB; header detection by column names and never by file name, saved column
  mappings);
* reading JSON with a size limit, a depth limit and a limit on list length;
* turning a cell into a flag, a number, a time or a short safe text;
* per-row rejects: a row that cannot be read is skipped and counted, with a
  reason that names the column and never repeats what the file said.

Nothing in this module does I/O. Everything works on bytes already in memory,
and the evidence store has already refused a file over the size limit.
"""

import codecs
import csv
import io
import json
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from charset_normalizer import from_bytes

from app.importers.base import FactValue, ImportRejectedError, ParsedFact

DEFAULT_MAX_ROWS = 200_000
MAX_JSON_BYTES = 20 * 1024 * 1024
MAX_JSON_DEPTH = 12
MAX_TEXT_LENGTH = 100
MAX_REJECT_FACTS = 50
MAX_NUMBER = Decimal(1_000_000_000)
MAX_DECIMAL_PLACES = 6
MAX_NUMBER_DIGITS = 10
MAX_COUNT_DIGITS = 18
NUMBER_SCALE = Decimal(1).scaleb(-MAX_DECIMAL_PLACES)
EARLIEST_TIME = datetime(2000, 1, 1, tzinfo=UTC)
LATEST_TIME = datetime(2100, 1, 1, tzinfo=UTC)
FORMULA_STARTS = ("=", "+", "-", "@")
# What the evidence store treats as an email address in a stored value.
EMAIL_LIKE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
TRUE_WORDS = frozenset({"true", "yes", "1"})
FALSE_WORDS = frozenset({"false", "no", "0"})
SEMICOLON_CSV = (
    "The delimiter looks like a semicolon; the file must be comma separated."
)
UNREADABLE_CSV = (
    "The file is not a readable CSV file, or one field is larger than "
    f"{csv.field_size_limit()} characters."
)


class MissingStructureError(ImportRejectedError):
    """The file lacks a column or a field this source needs."""


class RowError(Exception):
    """One row cannot be read. The message names the column, never the content."""


@dataclass(frozen=True)
class Column:
    """A column of a CSV contract.

    `key` is our name for it (the target of a saved mapping). `label` is the
    name Microsoft or the contract uses; it is shown in messages and matched
    without regard to case, spaces and punctuation, as are the `aliases`.
    """

    key: str
    label: str
    required: bool = False
    aliases: tuple[str, ...] = ()


@dataclass
class Flags:
    """What the reading of a file noticed along the way."""

    assumed_utc: bool = False


def slug(value: object) -> str:
    """Lower-case letters and digits only: a safe, comparable form of a word."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def column_key(name: str) -> str:
    """The comparable form of a column name.

    A `_loc` suffix (a localised Intune column) is ignored.
    """
    cleaned = name.strip()
    if cleaned.lower().endswith("_loc"):
        cleaned = cleaned[: -len("_loc")]
    return slug(cleaned)


def decode_text(data: bytes) -> str:
    """The text of a file.

    UTF-8 (with or without a BOM) and UTF-16 with a BOM are read directly; any
    other file goes through charset detection.
    """
    utf16 = data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
    if b"\x00" in data and not utf16:
        raise ImportRejectedError("The file is not readable text.")
    text: str | None
    try:
        text = data.decode("utf-16" if utf16 else "utf-8-sig")
    except UnicodeDecodeError:
        found = from_bytes(data).best()
        text = str(found) if found is not None else None
    if text is None or "\x00" in text:
        raise ImportRejectedError("The file is not readable text.")
    return text.lstrip("﻿")


# --- CSV ------------------------------------------------------------------


def resolve_columns(
    header: Sequence[str],
    spec: Sequence[Column],
    mapping: Mapping[str, str] | None = None,
) -> dict[str, int]:
    """Which header cell holds which column of the contract.

    A saved mapping (vendor header, exactly as written, to our column key) wins
    over name matching. A column found twice rejects the file.
    """
    by_name: dict[str, str] = {}
    for column in spec:
        for name in (column.label, *column.aliases):
            by_name[column_key(name)] = column.key
    saved = mapping or {}
    positions: dict[str, int] = {}
    for index, cell in enumerate(header):
        target = saved.get(cell.strip()) or by_name.get(column_key(cell))
        if target is None:
            continue
        if target in positions:
            label = next((c.label for c in spec if c.key == target), target)
            raise ImportRejectedError(f"The file has the column {label} twice.")
        positions[target] = index
    return positions


def missing_columns(
    spec: Sequence[Column],
    positions: Mapping[str, int],
) -> list[str]:
    """The labels of the required columns that were not found."""
    return [c.label for c in spec if c.required and c.key not in positions]


def missing_message(names: Sequence[str], kind: str = "column") -> str:
    listed = ", ".join(names)
    return f"The file is missing the {kind} {listed}."


@dataclass
class CsvFile:
    """An opened CSV: where the columns are, and the rows to read."""

    reader: Iterator[list[str]]
    header: list[str]
    positions: dict[str, int]
    max_rows: int

    def rows(self) -> Iterator[tuple[int, dict[str, str]]]:
        """Data rows as (row number, column key to text); blank lines are skipped.

        Row numbers count data rows from 1. A short row simply lacks the keys
        it has no cell for.
        """
        number = 0
        try:
            for raw in self.reader:
                if not any(cell.strip() for cell in raw):
                    continue
                number += 1
                if number > self.max_rows:
                    raise ImportRejectedError(
                        f"The file has more than {self.max_rows} rows."
                    )
                yield (
                    number,
                    {
                        key: raw[index].strip()
                        for key, index in self.positions.items()
                        if index < len(raw)
                    },
                )
        except csv.Error:
            raise ImportRejectedError(UNREADABLE_CSV) from None


def _first_header(reader: Iterator[list[str]]) -> list[str]:
    """The first line that is not blank."""
    try:
        for raw in reader:
            if any(cell.strip() for cell in raw):
                return raw
    except csv.Error:
        raise ImportRejectedError(UNREADABLE_CSV) from None
    raise ImportRejectedError("The file is empty.")


def read_header(text: str) -> list[str]:
    """The header cells of a CSV text."""
    return _first_header(csv.reader(io.StringIO(text, newline="")))


def open_csv(
    text: str,
    spec: Sequence[Column],
    max_rows: int,
    mapping: Mapping[str, str] | None = None,
) -> CsvFile:
    """Read the header and resolve the columns.

    A file that lacks a required column is rejected, naming the column.
    """
    reader = csv.reader(io.StringIO(text, newline=""))
    header = _first_header(reader)
    positions = resolve_columns(header, spec, mapping)
    missing = missing_columns(spec, positions)
    if missing:
        message = missing_message(missing)
        if len(header) == 1 and ";" in header[0]:
            message = f"{SEMICOLON_CSV} {message}"
        raise MissingStructureError(message)
    return CsvFile(reader, header, positions, max_rows)


# --- JSON -----------------------------------------------------------------


def _no_constant(name: str) -> object:
    raise ValueError(name)


def looks_like_json(text: str) -> bool:
    return text.lstrip().startswith(("{", "["))


def check_json_size(data: bytes) -> None:
    if len(data) > MAX_JSON_BYTES:
        raise ImportRejectedError(
            f"The JSON file is larger than {MAX_JSON_BYTES // 1_048_576} MB."
        )


def check_json_shape(root: object, max_rows: int) -> None:
    """Reject nesting deeper than the limit and any list longer than max_rows."""
    stack: list[tuple[object, int]] = [(root, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            raise ImportRejectedError(
                f"The JSON is nested deeper than {MAX_JSON_DEPTH} levels."
            )
        children: Sequence[object]
        if isinstance(node, dict):
            children = list(node.values())
        elif isinstance(node, list):
            if len(node) > max_rows:
                raise ImportRejectedError(
                    f"The JSON has a list of more than {max_rows} items."
                )
            children = node
        else:
            continue
        stack.extend((child, depth + 1) for child in children)


def parse_json_text(text: str, max_rows: int) -> object:
    """Parse JSON text within the limits. A number with a fraction is a Decimal."""
    try:
        root: object = json.loads(
            text, parse_float=Decimal, parse_constant=_no_constant
        )
    except RecursionError:
        raise ImportRejectedError(
            f"The JSON is nested deeper than {MAX_JSON_DEPTH} levels."
        ) from None
    except ValueError:
        raise ImportRejectedError("The file is not valid JSON.") from None
    check_json_shape(root, max_rows)
    return root


def load_json(data: bytes, max_rows: int) -> object:
    check_json_size(data)
    return parse_json_text(decode_text(data), max_rows)


def json_records(root: object) -> list[object]:
    """The records of a Graph answer.

    A list, or an object with a `value` list; any other object is one record.
    """
    if isinstance(root, list):
        return list(root)
    if isinstance(root, dict):
        value = root.get("value")
        if isinstance(value, list):
            return list(value)
        return [root]
    raise ImportRejectedError("The file must hold a JSON object or a list.")


def require_fields(records: Sequence[object], fields: Sequence[str]) -> None:
    """The first record must have every field, or this is another kind of file.

    Later records are checked one by one, as rows.
    """
    if not records:
        return
    first = records[0]
    present = first if isinstance(first, dict) else {}
    missing = [name for name in fields if name not in present]
    if missing:
        raise MissingStructureError(missing_message(missing, "field"))


def json_rows(
    records: Sequence[object], names: Mapping[str, str]
) -> Iterator[tuple[int, Mapping[str, object] | RowError]]:
    """JSON records as rows keyed like a CSV row (our column key to value)."""
    for number, record in enumerate(records, start=1):
        if isinstance(record, dict):
            yield number, {key: record.get(name) for key, name in names.items()}
        else:
            yield number, RowError("The record is not an object")


def json_capture_time(root: object) -> tuple[datetime | None, bool]:
    """The time the file was saved, when the file says so.

    That is the top-level `capturedAt` of an object (null counts as absent).
    Returns the time and whether UTC was assumed because the file gave no time
    zone.
    """
    if isinstance(root, dict) and root.get("capturedAt") is not None:
        try:
            moment, assumed = parse_moment(root["capturedAt"])
        except ValueError:
            raise ImportRejectedError(
                "The field capturedAt is not a date and time."
            ) from None
        return moment, assumed
    return None, False


# --- values ---------------------------------------------------------------


def parse_moment(value: object) -> tuple[datetime, bool]:
    """A time from a file, as UTC, and whether the file gave no time zone.

    Raises ValueError when it is not an ISO 8601 time between 2000 and 2100.
    """
    if not isinstance(value, str):
        raise ValueError("not a time")
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        raise ValueError("not a time") from None
    assumed = moment.tzinfo is None
    if assumed:
        moment = moment.replace(tzinfo=UTC)
    if not EARLIEST_TIME <= moment < LATEST_TIME:
        raise ValueError("not a plausible time")
    return moment.astimezone(UTC), assumed


def parse_bool(value: object) -> bool:
    """true/false, yes/no or 1/0 in any case. Raises ValueError otherwise."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        word = value.strip().lower()
        if word in TRUE_WORDS:
            return True
        if word in FALSE_WORDS:
            return False
    raise ValueError("not a flag")


def _decimal_places(number: Decimal) -> int:
    """How many places after the point a finite number needs.

    Trailing zeros do not count (1.500000000 needs one place). Only the
    exponent and the last digits are looked at, so a number written as
    1e-999990 costs nothing to measure.
    """
    _, digits, exponent = number.as_tuple()
    if not isinstance(exponent, int) or exponent >= 0:
        return 0
    trailing = 0
    for digit in reversed(digits):
        if digit != 0:
            break
        trailing += 1
    return max(0, -(exponent + trailing))


def parse_number(value: object) -> Decimal:
    """A non-negative finite number of at most 6 decimal places.

    Raises ValueError otherwise. Zero is accepted however it is written.
    """
    number: Decimal
    if isinstance(value, bool):
        raise ValueError("not a number")
    if isinstance(value, int | Decimal):
        number = Decimal(value)
    elif isinstance(value, str):
        try:
            number = Decimal(value.strip())
        except InvalidOperation:
            raise ValueError("not a number") from None
    else:
        raise ValueError("not a number")
    if not number.is_finite() or number < 0 or number > MAX_NUMBER:
        raise ValueError("not a plausible number")
    if number != 0 and _decimal_places(number) > MAX_DECIMAL_PLACES:
        raise ValueError("not a plausible number")
    return number


def number_text(number: Decimal) -> str:
    """An exact decimal as text ('48.5', '100'), the way scores are stored.

    The text is at most 17 characters for a number `parse_number` accepted;
    any other number raises ValueError instead of expanding into a huge string.
    """
    if number == 0:
        return "0"
    if (
        not number.is_finite()
        or number.adjusted() >= MAX_NUMBER_DIGITS
        or _decimal_places(number) > MAX_DECIMAL_PLACES
    ):
        raise ValueError("not a plausible number")
    return format(number.quantize(NUMBER_SCALE).normalize(), "f")


def safe_text(
    value: object, limit: int = MAX_TEXT_LENGTH, label: str = "A text field"
) -> str:
    """Text kept in a fact.

    Printable characters only, cut to `limit`, and never starting like a
    spreadsheet formula. Text that looks like an email address is a row error
    (RowError names `label`): the evidence store would refuse the whole upload
    for it, and a short text field is never meant to hold a person's address.
    The check runs on the text as it will be stored, after the formula prefix:
    the prefix can supply the part before an at sign (@acme.com becomes
    '@acme.com), which the store would then refuse for the whole upload.
    Call it only while reading a row.
    """
    text = value if isinstance(value, str) else ""
    cleaned = "".join(char for char in text if char.isprintable()).strip()[:limit]
    kept = "'" + cleaned if cleaned.startswith(FORMULA_STARTS) else cleaned
    if EMAIL_LIKE.search(kept):
        raise RowError(f"{label} must not contain an email address")
    return kept


def choice(value: object, allowed: Mapping[str, str]) -> str:
    """A word from a fixed vocabulary, or 'other' for anything else."""
    return allowed.get(slug(value), "other")


def optional_choice(value: object, allowed: Mapping[str, str]) -> str | None:
    """Like `choice`, and None when the cell is empty."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return choice(value, allowed)


def prefix_choice(value: object, allowed: Sequence[tuple[str, str]]) -> str:
    """Like `choice`, matching on the start of the word."""
    word = slug(value)
    return next((name for start, name in allowed if word.startswith(start)), "other")


def read_text(raw: Mapping[str, object], key: str) -> str | None:
    """A non-empty string of a record, or None."""
    value = raw.get(key)
    if isinstance(value, str):
        return value.strip() or None
    return None


def _is_empty(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def read_flag(
    raw: Mapping[str, object],
    key: str,
    label: str,
    *,
    required: bool = False,
) -> bool | None:
    value = raw.get(key)
    if _is_empty(value):
        if required:
            raise RowError(f"{label} is empty")
        return None
    try:
        return parse_bool(value)
    except ValueError:
        raise RowError(f"{label} must be true or false") from None


def read_count(raw: Mapping[str, object], key: str, label: str) -> int | None:
    """A whole number of zero or more, or None when the cell is empty.

    At most 18 digits: a longer number is a row error, never an exception.
    """
    value = raw.get(key)
    if _is_empty(value):
        return None
    if isinstance(value, str):
        digits = value.strip()
        if digits.isdecimal() and len(digits) <= MAX_COUNT_DIGITS:
            return int(digits)
    elif (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value < 10**MAX_COUNT_DIGITS
    ):
        return value
    raise RowError(f"{label} must be a whole number")


def read_time(
    raw: Mapping[str, object],
    key: str,
    label: str,
    flags: Flags,
    *,
    required: bool = False,
) -> datetime | None:
    value = raw.get(key)
    if _is_empty(value):
        if required:
            raise RowError(f"{label} is empty")
        return None
    try:
        moment, assumed = parse_moment(value)
    except ValueError:
        raise RowError(f"{label} must be an ISO 8601 date and time") from None
    flags.assumed_utc = flags.assumed_utc or assumed
    return moment


def read_required_time(
    raw: Mapping[str, object],
    key: str,
    label: str,
    flags: Flags,
) -> datetime:
    moment = read_time(raw, key, label, flags, required=True)
    assert moment is not None  # required=True raised for an empty cell
    return moment


def iso(moment: datetime | None) -> str | None:
    return moment.astimezone(UTC).isoformat() if moment else None


# --- rejects and the summary ----------------------------------------------


def as_row(raw: Mapping[str, object] | RowError) -> Mapping[str, object]:
    """The row itself, or raise the reason it could not be made into one."""
    if isinstance(raw, RowError):
        raise raw
    return raw


@dataclass
class Rejects:
    """The rows that could not be read: counted, and the first 50 recorded."""

    prefix: str
    facts: list[ParsedFact] = field(default_factory=list)
    count: int = 0
    first: str | None = None

    def add(self, number: int, error: RowError) -> None:
        self.count += 1
        message = str(error)
        if self.first is None:
            self.first = f"Row {number}: {message}."
        if len(self.facts) < MAX_REJECT_FACTS:
            reason: dict[str, FactValue] = {"row": number, "reason": message}
            self.facts.append(ParsedFact(f"{self.prefix}.reject", reason))

    @contextmanager
    def row(self, number: int) -> Iterator[None]:
        """Run the body for one row; a RowError rejects the row, nothing more."""
        try:
            yield
        except RowError as error:
            self.add(number, error)

    def require_usable(self, usable: int) -> None:
        """A file in which not one row could be read is not a file of this kind."""
        if self.count and usable == 0:
            raise ImportRejectedError(f"No row of the file could be read. {self.first}")


RowReader = Callable[[Mapping[str, object], Flags], ParsedFact]


def read_rows(
    rows: Iterable[tuple[int, Mapping[str, object] | RowError]],
    read: RowReader,
    flags: Flags,
    rejects: Rejects,
) -> list[ParsedFact]:
    """Read every row with `read`; a row that cannot be read is rejected."""
    facts: list[ParsedFact] = []
    for number, raw in rows:
        with rejects.row(number):
            facts.append(read(as_row(raw), flags))
    rejects.require_usable(len(facts))
    return facts


def summary_fact(
    prefix: str,
    counts: Mapping[str, FactValue],
    rejects: Rejects,
    flags: Flags,
    *,
    capture_in_file: bool,
) -> ParsedFact:
    """The summary of one file: its counts and its flags.

    capture_time_source is `file` when the file or its tool said when it was
    captured, and `upload` when it did not (the evidence store then uses the
    time given at upload).
    """
    value: dict[str, FactValue] = dict(counts)
    value["rows_rejected"] = rejects.count
    value["capture_time_source"] = "file" if capture_in_file else "upload"
    value["timezone_assumed_utc"] = flags.assumed_utc
    return ParsedFact(f"{prefix}.summary", value)
