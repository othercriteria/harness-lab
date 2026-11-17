"""Offline, data-only summary helper for model-authored progress reports.

summarize() accepts a chronological list of already-validated
progress-report dicts (the seven-field contract) and returns plain
descriptive counts: the report count, per-value counts for the four
change strings and the four check-result strings (including zeros), the
number of reports naming a non-empty obstacle, the per-report
remaining-list lengths in report order, a deep copy of the latest
report, and the number of adjacent report pairs that repeated exactly
the same next_action text (exact string equality, no normalization).

These are descriptive counts of model assertions, not a certification of
correctness, not a calibrated completion or finish-probability score,
and not a futility or termination decision. Truth, relevance, and
next-action concreteness remain outer review, not mechanical rules here.

The module is data only: standard library, no I/O, no execution, no
model calls, no import of progress_report, no validation of individual
reports, no evidence resolution, and no mutation of, or retained
mutable references to, its inputs.
"""

import copy

CHANGE_VALUES = ("advanced", "unchanged", "regressed", "uncertain")
CHECK_RESULT_VALUES = ("passing", "failing", "stale", "unknown")


def summarize(reports):
    """Return descriptive counts for a chronological list of reports.

    ``reports`` must be a list of already-validated progress-report
    dicts following the seven-field contract, in chronological order;
    any other top-level input raises ValueError. Individual reports are
    not validated and evidence citations are not resolved. Inputs are
    never mutated and the returned structure holds no mutable
    references to them: ``latest`` is a deep copy of the last report
    (or None for an empty list), and every other value is an int or a
    freshly built dict/list of ints.
    """
    if not isinstance(reports, list):
        raise ValueError("reports must be a list of progress reports")

    change_counts = {value: 0 for value in CHANGE_VALUES}
    check_counts = {value: 0 for value in CHECK_RESULT_VALUES}
    reports_with_obstacle = 0
    remaining_counts = []
    repeated_next_action_transitions = 0
    latest = None

    previous_next_action = None
    for report in reports:
        change_counts[report["change"]] += 1
        for entry in report["checks"]:
            check_counts[entry["result"]] += 1
        if report["obstacle"] != "":
            reports_with_obstacle += 1
        remaining_counts.append(len(report["remaining"]))
        next_action = report["next_action"]
        if (
            previous_next_action is not None
            and next_action == previous_next_action
        ):
            repeated_next_action_transitions += 1
        previous_next_action = next_action

    if reports:
        latest = copy.deepcopy(reports[-1])

    return {
        "report_count": len(reports),
        "change_counts": change_counts,
        "check_counts": check_counts,
        "reports_with_obstacle": reports_with_obstacle,
        "remaining_counts": remaining_counts,
        "latest": latest,
        "repeated_next_action_transitions": repeated_next_action_transitions,
    }
