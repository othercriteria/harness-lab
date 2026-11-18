"""Small standard-library CSV work-log reporting utility."""

from .csvio import RowError, parse_minutes, read_records, write_records
from .model import Record, TeamSummary, select_records, summarize, totals
from .render import render_report

__all__ = [
    "Record", "TeamSummary", "RowError", "parse_minutes", "read_records",
    "write_records", "select_records", "summarize", "totals", "render_report",
    "compare_records", "render_diff",
]


def __getattr__(name):
    # Delay importing the executable submodule until an export is requested.
    if name in ("compare_records", "render_diff"):
        from .diff import compare_records, render_diff
        globals().update(compare_records=compare_records, render_diff=render_diff)
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
