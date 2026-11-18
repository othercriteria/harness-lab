"""CSV input with useful row diagnostics; input streams belong to their callers."""

import csv
import re
from collections.abc import Iterable
from typing import TextIO

from .model import STATUSES, Record

COLUMNS = ("team", "item", "minutes", "status")
_INTEGER = re.compile(r"[0-9]+\Z")


class RowError(ValueError):
    def __init__(self, line: int, message: str):
        super().__init__(f"line {line}: {message}")
        self.line = line
        self.detail = message


def parse_minutes(value: str) -> int:
    """Parse a stripped ASCII nonnegative integer duration."""
    value = value.strip()
    if not _INTEGER.fullmatch(value):
        raise ValueError("minutes must be a nonnegative ASCII integer")
    return int(value)


def _header(raw: list[str]) -> dict[str, int]:
    names = [name.strip() for name in raw]
    if len(names) != len(set(names)):
        raise ValueError("duplicate header name")
    missing = sorted(set(COLUMNS) - set(names))
    extra = sorted(set(names) - set(COLUMNS))
    problems = []
    if missing:
        problems.append("missing columns: " + ", ".join(missing))
    if extra:
        problems.append("unexpected columns: " + ", ".join(extra))
    if problems:
        raise ValueError("; ".join(problems))
    return {name: names.index(name) for name in COLUMNS}


def _record(raw: list[str], positions: dict[str, int]) -> Record:
    if len(raw) != len(COLUMNS):
        raise ValueError(f"expected {len(COLUMNS)} fields, got {len(raw)}")
    fields = {name: raw[index].strip() for name, index in positions.items()}
    if not fields["team"]:
        raise ValueError("team must not be empty")
    if not fields["item"]:
        raise ValueError("item must not be empty")
    if fields["status"] not in STATUSES:
        raise ValueError("status must be 'open' or 'done'")
    return Record(
        team=fields["team"],
        item=fields["item"],
        minutes=parse_minutes(fields["minutes"]),
        status=fields["status"],
    )


def read_records(source: TextIO) -> list[Record]:
    """Read one CSV table, allowing ordinary empty physical lines."""
    reader = csv.reader(source, strict=True)
    positions = None
    result = []
    try:
        for row in reader:
            if not row:
                continue
            if positions is None:
                try:
                    positions = _header(row)
                except ValueError as error:
                    raise RowError(reader.line_num, str(error)) from error
                continue
            try:
                result.append(_record(row, positions))
            except ValueError as error:
                raise RowError(reader.line_num, str(error)) from error
    except csv.Error as error:
        raise RowError(reader.line_num, "invalid CSV: " + str(error)) from error
    if positions is None:
        raise RowError(1, "missing header")
    return result


def write_records(records: Iterable[Record], destination: TextIO) -> None:
    """Write ordinary normalized input records; keep ownership of the stream external."""
    writer = csv.writer(destination, lineterminator="\n")
    writer.writerow(COLUMNS)
    for record in records:
        writer.writerow((record.team, record.item, record.minutes, record.status))
