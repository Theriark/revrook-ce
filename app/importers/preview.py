"""The preview of the mapping profile editor (phase 4, part 2).

Before anything is stored, the editor shows what a CSV source adapter would read
from a file: which column of the file feeds which column of the contract, which
required columns are missing, and the first 20 rows as the adapter reads them.

The preview uses the same column resolution and the same cell readers as the
import, so what it shows is what the import stores:

* a cell is shown as the importer keeps it (a word from its fixed list, a flag,
  a whole number, a time in UTC, a short text that never starts like a
  spreadsheet formula); a time written without a time zone is marked as read
  as UTC;
* an identifier (a user, a device, a mailbox) is shown only as the client's
  pseudonym, never as written in the file;
* a rejected row shows its reason, which names the column and never repeats the
  content;
* only the columns of the contract are shown. Serial numbers, client names and
  any other column the adapter does not read never appear, and their header is
  not offered as a column to map.

Nothing here does I/O or keeps the file.
"""

import csv
import io
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass

from app.importers.base import FactValue, ImportRejectedError
from app.importers.framework import (
    EMAIL_LIKE,
    SEMICOLON_CSV,
    UNREADABLE_CSV,
    CsvFile,
    Flags,
    RowError,
    decode_text,
    looks_like_json,
    missing_columns,
    missing_message,
    read_text,
    resolve_columns,
    slug,
)
from app.importers.generic import (
    MAX_IDENTIFIER_LENGTH,
    UNREAD_HEADERS,
    CsvAdapter,
    Field,
)
from app.importers.profiles import MAX_HEADER_LENGTH
from app.importers.registry import ImporterRegistry

PREVIEW_ROWS = 20
MAX_OFFERED_HEADERS = 200

# What a preview cell holds.
VALUE = "value"
EMPTY = "empty"
PSEUDONYM = "pseudonym"
UNREADABLE = "unreadable"
NOT_READ = "not-read"

Pseudonymise = Callable[[str], str]


@dataclass(frozen=True)
class PreviewCell:
    """One cell as the importer would store it.

    `state` is one of value, empty, pseudonym, unreadable and not-read (the
    column does not apply to this record type). `assumed_utc` marks a time
    written without a time zone.
    """

    text: str
    state: str
    assumed_utc: bool = False


@dataclass(frozen=True)
class PreviewRow:
    """One data row: its number, the reason it is rejected (or None), its cells."""

    number: int
    reason: str | None
    cells: tuple[PreviewCell, ...]

    @property
    def assumed_utc(self) -> bool:
        return any(cell.assumed_utc for cell in self.cells)


@dataclass(frozen=True)
class ColumnChoice:
    """A column of the contract and the file column that feeds it, if any."""

    key: str
    label: str
    required: bool
    header: str | None


@dataclass(frozen=True)
class Preview:
    """What the editor shows for one file, one source and one mapping."""

    choices: tuple[ColumnChoice, ...]
    offered: tuple[str, ...]
    hidden_headers: int
    missing: tuple[str, ...]
    problem: str | None
    rows: tuple[PreviewRow, ...]
    more_rows: bool

    @property
    def importable(self) -> bool:
        """Whether the importer would accept the file (rows may still be rejected)."""
        return self.problem is None

    @property
    def shown(self) -> tuple[ColumnChoice, ...]:
        """The columns of the preview table: those the file feeds."""
        return tuple(choice for choice in self.choices if choice.header is not None)

    @property
    def rejected(self) -> int:
        return sum(1 for row in self.rows if row.reason is not None)

    @property
    def assumed_utc(self) -> bool:
        return any(row.assumed_utc for row in self.rows)

    def mapping(self) -> dict[str, str]:
        """The mapping to save: file column, exactly as written, to column key."""
        mapping: dict[str, str] = {}
        for choice in self.choices:
            if choice.header is not None:
                mapping[choice.header] = choice.key
        return mapping


def editor_adapters(registry: ImporterRegistry) -> list[CsvAdapter]:
    """The sources the editor maps: the CSV contracts of phase 4, by source code."""
    found: list[CsvAdapter] = []
    for code in registry.source_codes():
        importer = registry.get(code)
        if isinstance(importer, CsvAdapter):
            found.append(importer)
    return found


def _first_row(reader: Iterator[list[str]]) -> list[str]:
    """The first line of the file that is not blank: its header."""
    try:
        for raw in reader:
            if any(cell.strip() for cell in raw):
                return raw
    except csv.Error:
        raise ImportRejectedError(UNREADABLE_CSV) from None
    raise ImportRejectedError("The file is empty.")


def offered_headers(header: list[str]) -> tuple[tuple[str, ...], int]:
    """The file columns that may be mapped, and how many others there are.

    A column is offered when its name is 1 to 100 printable characters, is not
    a column the adapters never read (serial numbers, client names), does not
    look like an email address, and was not offered already. At most 200 are
    offered.
    """
    offered: list[str] = []
    hidden = 0
    for cell in header:
        name = cell.strip()
        if not name:
            continue
        if (
            len(name) > MAX_HEADER_LENGTH
            or not name.isprintable()
            or slug(name) in UNREAD_HEADERS
            or EMAIL_LIKE.search(name)
            or name in offered
            or len(offered) >= MAX_OFFERED_HEADERS
        ):
            hidden += 1
            continue
        offered.append(name)
    return tuple(offered), hidden


def chosen_mapping(
    adapter: CsvAdapter, chosen: Mapping[str, str], offered: tuple[str, ...]
) -> dict[str, str]:
    """The mapping (file column to column key) of the editor's choices.

    `chosen` maps a column key to a file column. A choice of a column the
    contract does not have, or of a file column that is not offered, is
    ignored. One file column chosen for two columns is refused.
    """
    labels = {column.key: column.label for column in adapter.columns}
    mapping: dict[str, str] = {}
    for key, header in chosen.items():
        name = header.strip()
        if key not in labels or name not in offered:
            continue
        if name in mapping:
            first, second = sorted((labels[mapping[name]], labels[key]))
            raise ImportRejectedError(
                f"One file column is chosen for two columns: {first} and {second}."
            )
        mapping[name] = key
    return mapping


def _display(value: FactValue) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def preview_cell(
    adapter: CsvAdapter,
    item: Field,
    raw: Mapping[str, object],
    kind: str | None,
    pseudonymise: Pseudonymise,
) -> PreviewCell:
    """One cell of a row, read the way the adapter reads it."""
    key, label = item.column.key, item.column.label
    if key == adapter.kind_key:
        return PreviewCell(kind, VALUE) if kind else PreviewCell("", UNREADABLE)
    if item.kinds is not None and (kind is None or kind not in item.kinds):
        return PreviewCell("", NOT_READ)
    if item.target is not None:
        text = read_text(raw, key)
        if text is None:
            return PreviewCell("", EMPTY)
        if len(text) > MAX_IDENTIFIER_LENGTH:
            return PreviewCell("", UNREADABLE)
        try:
            return PreviewCell(pseudonymise(text), PSEUDONYM)
        except ValueError:
            return PreviewCell("", EMPTY)
    flags = Flags()
    try:
        value = item.read(raw, key, label, flags)
    except RowError:
        return PreviewCell("", UNREADABLE)
    if value is None:
        return PreviewCell("", EMPTY)
    return PreviewCell(_display(value), VALUE, flags.assumed_utc)


def preview_row(
    adapter: CsvAdapter,
    number: int,
    raw: Mapping[str, object],
    shown: tuple[ColumnChoice, ...],
    pseudonymise: Pseudonymise,
) -> PreviewRow:
    """One data row: the adapter's verdict, and the cells of the shown columns."""
    reason: str | None = None
    try:
        adapter.read_row(raw, Flags())
    except RowError as error:
        reason = str(error)
    try:
        kind: str | None = adapter.kind_of(raw)
    except RowError:
        kind = None
    by_key = {item.column.key: item for item in adapter.fields}
    cells = tuple(
        preview_cell(adapter, by_key[choice.key], raw, kind, pseudonymise)
        for choice in shown
    )
    return PreviewRow(number, reason, cells)


def _choices(
    adapter: CsvAdapter, header: list[str], positions: Mapping[str, int]
) -> tuple[ColumnChoice, ...]:
    choices: list[ColumnChoice] = []
    for column in adapter.columns:
        index = positions.get(column.key)
        name = header[index].strip() if index is not None else None
        choices.append(ColumnChoice(column.key, column.label, column.required, name))
    return tuple(choices)


def _kept(header: str | None, offered: tuple[str, ...]) -> str | None:
    """A choice of the editor kept as it was, when it names an offered column."""
    if header is None or header.strip() not in offered:
        return None
    return header.strip()


def _missing(adapter: CsvAdapter, positions: Mapping[str, int]) -> list[str]:
    """The required columns not found; a group needs one of its columns."""
    missing = missing_columns(adapter.columns, positions)
    for group in adapter.any_of:
        if not any(key in positions for key in group):
            labels = [c.label for c in adapter.columns if c.key in group]
            missing.append(" or ".join(labels))
    return missing


def build_preview(
    adapter: CsvAdapter,
    data: bytes,
    chosen: Mapping[str, str],
    pseudonymise: Pseudonymise,
    max_rows: int,
) -> Preview:
    """The preview of one file read by one adapter through the editor's choices.

    Raises ImportRejectedError when the file cannot be read at all (not text,
    JSON, empty, not a CSV). Any other reason the import would refuse the file
    is the preview's `problem`.
    """
    text = decode_text(data)
    if looks_like_json(text):
        raise ImportRejectedError(f"The file must be a CSV file ({adapter.label}).")
    reader = csv.reader(io.StringIO(text, newline=""))
    header = _first_row(reader)
    offered, hidden = offered_headers(header)
    try:
        mapping = chosen_mapping(adapter, chosen, offered)
        positions = resolve_columns(header, adapter.columns, mapping)
    except ImportRejectedError as error:
        kept = tuple(
            ColumnChoice(c.key, c.label, c.required, _kept(chosen.get(c.key), offered))
            for c in adapter.columns
        )
        return Preview(kept, offered, hidden, (), str(error), (), False)
    choices = _choices(adapter, header, positions)
    missing = _missing(adapter, positions)
    if missing:
        problem = missing_message(missing)
        if len(header) == 1 and ";" in header[0]:
            problem = f"{SEMICOLON_CSV} {problem}"
        return Preview(choices, offered, hidden, tuple(missing), problem, (), False)
    shown = tuple(choice for choice in choices if choice.header is not None)
    rows: list[PreviewRow] = []
    more = False
    problem_found: str | None = None
    table = CsvFile(reader, header, dict(positions), max_rows)
    try:
        for number, raw in table.rows():
            if len(rows) == PREVIEW_ROWS:
                more = True
                break
            rows.append(preview_row(adapter, number, raw, shown, pseudonymise))
    except ImportRejectedError as error:
        problem_found = str(error)
    if (
        problem_found is None
        and rows
        and not more
        and all(row.reason is not None for row in rows)
    ):
        # The whole file is on show and no row can be read: the import refuses it
        # (Rejects.require_usable), so the preview must not offer it for saving.
        problem_found = f"No row of the file could be read. {rows[0].reason}"
    return Preview(choices, offered, hidden, (), problem_found, tuple(rows), more)
