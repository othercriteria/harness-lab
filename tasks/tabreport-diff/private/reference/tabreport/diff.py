"""Compare exact work-log identities and serialize snapshot changes."""

import argparse
import csv
import io
import json
import sys

from .cli import _read, _write


COLUMNS = (
    "team", "item", "kind", "before_minutes", "after_minutes",
    "before_status", "after_status", "delta_minutes",
)


def _index(records):
    result = {}
    for record in records:
        key = (record.team, record.item)
        if key in result:
            raise ValueError(f"duplicate identity: {key!r}")
        result[key] = record
    return result


def compare_records(before, after):
    old, new = _index(before), _index(after)
    identities = sorted(
        old.keys() | new.keys(),
        key=lambda pair: (pair[0].casefold(), pair[0], pair[1].casefold(), pair[1]),
    )
    changes = []
    for team, item in identities:
        previous, current = old.get((team, item)), new.get((team, item))
        if previous is None:
            kind = "added"
        elif current is None:
            kind = "removed"
        elif (previous.minutes, previous.status) == (current.minutes, current.status):
            continue
        else:
            kind = "modified"
        previous_minutes = previous.minutes if previous is not None else None
        current_minutes = current.minutes if current is not None else None
        changes.append({
            "team": team,
            "item": item,
            "kind": kind,
            "before_minutes": previous_minutes,
            "after_minutes": current_minutes,
            "before_status": previous.status if previous is not None else None,
            "after_status": current.status if current is not None else None,
            "delta_minutes": (current_minutes or 0) - (previous_minutes or 0),
        })
    return changes


def render_diff(changes, *, format="json"):
    if format == "json":
        return json.dumps(list(changes)) + "\n"
    if format != "csv":
        raise ValueError("format must be json or csv")
    destination = io.StringIO(newline="")
    # Quoting every cell also protects bare CR characters with LF record endings.
    writer = csv.writer(destination, lineterminator="\n", quoting=csv.QUOTE_ALL)
    writer.writerow(COLUMNS)
    for change in changes:
        writer.writerow([change[column] for column in COLUMNS])
    return destination.getvalue()


def main(argv=None, *, stdin=None, stdout=None, stderr=None):
    if stdin is None:
        stdin = sys.stdin
    if stdout is None:
        stdout = sys.stdout
    if stderr is None:
        stderr = sys.stderr
    parser = argparse.ArgumentParser(description="Compare two work-log snapshots.")
    parser.add_argument("before", help="UTF-8 CSV file, or - for stdin")
    parser.add_argument("after", help="UTF-8 CSV file, or - for stdin")
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    parser.add_argument("--output", help="Write the UTF-8 report to this path")
    args = parser.parse_args(argv)
    try:
        if args.before == "-" and args.after == "-":
            raise ValueError("only one input may read stdin")
        before = _read(args.before, stdin)
        after = _read(args.after, stdin)
        report = render_diff(compare_records(before, after), format=args.format)
        _write(args.output, report, stdout)
    except (ValueError, OSError, UnicodeError) as error:
        stderr.write(f"error: {error}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
