"""Selection and aggregation of small work-log tables."""

from collections.abc import Iterable
from dataclasses import dataclass

STATUSES = ("open", "done")


@dataclass(frozen=True)
class Record:
    team: str
    item: str
    minutes: int
    status: str


@dataclass(frozen=True)
class TeamSummary:
    team: str
    rows: int
    minutes: int
    done: int
    open: int

    @property
    def completion_percent(self) -> int:
        """Whole percent, rounded down; an empty summary has zero completion."""
        if self.rows == 0:
            return 0
        return self.done * 100 // self.rows

    def cells(self) -> tuple[str, str, str, str, str]:
        """Stable report column order, shared by all serializers."""
        return (
            self.team,
            str(self.rows),
            str(self.minutes),
            str(self.done),
            str(self.open),
        )


def select_records(
    records: Iterable[Record], *, team: str | None = None, status: str | None = None
) -> list[Record]:
    """Return matching records in input order without changing the input."""
    if status is not None and status not in STATUSES:
        raise ValueError("status must be 'open' or 'done'")
    selected = []
    for record in records:
        if team is not None and record.team != team:
            continue
        if status is not None and record.status != status:
            continue
        selected.append(record)
    return selected


def summarize(
    records: Iterable[Record], *, sort_by: str = "team"
) -> list[TeamSummary]:
    """Aggregate exact team labels; default ordering is case-insensitive by name."""
    if sort_by != "team":
        raise ValueError("sort_by must be 'team'")
    buckets = {}
    for record in records:
        counts = buckets.setdefault(record.team, [0, 0, 0, 0])
        counts[0] += 1
        counts[1] += record.minutes
        if record.status == "done":
            counts[2] += 1
        else:
            counts[3] += 1
    result = [
        TeamSummary(team, counts[0], counts[1], counts[2], counts[3])
        for team, counts in buckets.items()
    ]
    result.sort(key=lambda summary: (summary.team.casefold(), summary.team))
    return result


def totals(summaries: Iterable[TeamSummary]) -> TeamSummary:
    """Make a separate TOTAL row; a real team named TOTAL stays an ordinary team."""
    rows = minutes = done = opened = 0
    for summary in summaries:
        rows += summary.rows
        minutes += summary.minutes
        done += summary.done
        opened += summary.open
    return TeamSummary("TOTAL", rows, minutes, done, opened)


def report_rows(
    summaries: Iterable[TeamSummary], *, include_total: bool = True
) -> list[TeamSummary]:
    """Materialize once, preserving group order and optionally append totals."""
    result = list(summaries)
    if include_total:
        result.append(totals(result))
    return result
