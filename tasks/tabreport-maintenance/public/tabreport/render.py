"""Text, Markdown and CSV reports with the same five-column data model."""

import csv
import io
from collections.abc import Iterable

from .model import TeamSummary, report_rows

HEADINGS = ("Team", "Rows", "Minutes", "Done", "Open")
CSV_HEADINGS = tuple(heading.lower() for heading in HEADINGS)
FORMATS = ("text", "markdown", "csv")


def _table(
    summaries: Iterable[TeamSummary], include_total: bool
) -> list[tuple[str, str, str, str, str]]:
    return [summary.cells() for summary in report_rows(summaries, include_total=include_total)]


def _display_cell(value: str) -> str:
    """Keep an ordinary text report on one line per row."""
    return value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")


def _text_row(cells: Iterable[str], widths: list[int]) -> str:
    pieces = []
    for column, (value, width) in enumerate(zip(cells, widths, strict=True)):
        if column == 0:
            pieces.append(value.ljust(width))
        else:
            pieces.append(value.rjust(width))
    return "  ".join(pieces).rstrip()


def render_text(
    summaries: Iterable[TeamSummary], *, include_total: bool = True
) -> str:
    rows = _table(summaries, include_total)
    displayed = [tuple(_display_cell(value) for value in row) for row in rows]
    widths = [len(heading) for heading in HEADINGS]
    for row in displayed:
        for column, value in enumerate(row):
            widths[column] = max(widths[column], len(value))
    lines = [_text_row(HEADINGS, widths)]
    lines.append("  ".join("-" * width for width in widths))
    lines.extend(_text_row(row, widths) for row in displayed)
    return "\n".join(lines) + "\n"


def _markdown_cell(value: str) -> str:
    return value


def render_markdown(
    summaries: Iterable[TeamSummary], *, include_total: bool = True
) -> str:
    rows = _table(summaries, include_total)
    lines = ["| " + " | ".join(HEADINGS) + " |"]
    lines.append("| :--- | ---: | ---: | ---: | ---: |")
    for row in rows:
        lines.append("| " + " | ".join(_markdown_cell(value) for value in row) + " |")
    return "\n".join(lines) + "\n"


def render_csv(
    summaries: Iterable[TeamSummary], *, include_total: bool = True
) -> str:
    destination = io.StringIO(newline="")
    writer = csv.writer(destination)
    writer.writerow(CSV_HEADINGS)
    writer.writerows(_table(summaries, include_total))
    return destination.getvalue()


def render_report(
    summaries: Iterable[TeamSummary], *, format: str = "text", include_total: bool = True
) -> str:
    """Choose a serializer without reordering the supplied summaries."""
    renderers = {
        "text": render_text,
        "markdown": render_markdown,
        "csv": render_csv,
    }
    try:
        renderer = renderers[format]
    except KeyError as error:
        raise ValueError("format must be one of: " + ", ".join(FORMATS)) from error
    return renderer(summaries, include_total=include_total)
