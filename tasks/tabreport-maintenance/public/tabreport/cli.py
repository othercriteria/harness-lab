"""Command-line adapter; validate and construct reports before writing output."""

import argparse
import sys
from pathlib import Path
from typing import TextIO

from .csvio import read_records
from .model import select_records, summarize
from .render import FORMATS, render_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize a small CSV work log by team.")
    parser.add_argument("input", help="UTF-8 CSV file, or - for stdin")
    parser.add_argument("--output", help="Write UTF-8 report to this file instead of stdout")
    parser.add_argument("--format", choices=FORMATS, default="text")
    parser.add_argument("--team", help="Select one exact team label")
    parser.add_argument("--status", choices=("open", "done"))
    parser.add_argument("--sort", choices=("team",), default="team")
    parser.add_argument("--no-total", action="store_true", help="Omit the final total row")
    return parser


def _read(path: str, stdin: TextIO):
    if path == "-":
        return read_records(stdin)
    with Path(path).open("r", encoding="utf-8", newline="") as source:
        return read_records(source)


def _write(path: str | None, report: str, stdout: TextIO) -> None:
    if path is None:
        stdout.write(report)
        return
    with Path(path).open("w", encoding="utf-8", newline="") as destination:
        destination.write(report)


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the CLI. Optional streams make embedding/testing straightforward."""
    if stdin is None:
        stdin = sys.stdin
    if stdout is None:
        stdout = sys.stdout
    if stderr is None:
        stderr = sys.stderr
    args = build_parser().parse_args(argv)
    try:
        records = _read(args.input, stdin)
        selected = select_records(records, team=args.team, status=args.status)
        summaries = summarize(selected, sort_by=args.sort)
        report = render_report(
            summaries, format=args.format, include_total=not args.no_total
        )
        _write(args.output, report, stdout)
    except (ValueError, OSError, UnicodeError) as error:
        stderr.write(f"error: {error}\n")
        return 2
    return 0
