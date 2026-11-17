"""Read accepted checkpoint JSON as data and summarize unverified claims."""

import argparse
import json
from pathlib import Path
import re
import stat

from progress_summary import CHANGE_VALUES, CHECK_RESULT_VALUES, summarize
from progress_values import PAYLOAD_UTF8_BYTES, TEXT_BOUND

CHECKPOINT_NAME = re.compile(r"context-checkpoint-([0-9]{3,})\.json\Z")
REPORT_FIELDS = {
    "change", "implemented", "checks", "remaining", "obstacle",
    "next_action", "evidence",
}


def _text(value, label, allow_empty=False):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    if allow_empty and value == "":
        return
    if not value.strip() or len(value.encode("utf-8")) > TEXT_BOUND:
        raise ValueError(
            f"{label} must be nonblank and at most {TEXT_BOUND} UTF-8 bytes"
        )
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError(f"{label} contains control characters")


def _report_shape(report):
    """Check documented structure, without resolving historical citations."""
    if not isinstance(report, dict) or set(report) != REPORT_FIELDS:
        raise ValueError("progress must be an object with exactly seven report fields")
    if report["change"] not in CHANGE_VALUES:
        raise ValueError("progress.change has an unknown value")
    for field, limit in (("implemented", 2), ("remaining", 4)):
        items = report[field]
        if not isinstance(items, list) or len(items) > limit:
            raise ValueError(f"progress.{field} must be an array of at most {limit} items")
        for item in items:
            _text(item, "progress." + field)
    checks = report["checks"]
    if not isinstance(checks, list) or len(checks) > 2:
        raise ValueError("progress.checks must be an array of at most two entries")
    for entry in checks:
        if not isinstance(entry, dict) or set(entry) != {"result", "summary"}:
            raise ValueError("each check must contain exactly result and summary")
        if entry["result"] not in CHECK_RESULT_VALUES:
            raise ValueError("check.result has an unknown value")
        _text(entry["summary"], "check.summary")
    _text(report["obstacle"], "progress.obstacle", allow_empty=True)
    _text(report["next_action"], "progress.next_action")
    evidence = report["evidence"]
    if not isinstance(evidence, list) or any(not isinstance(item, dict) for item in evidence):
        raise ValueError("progress.evidence must be an array of citation objects")
    if len(json.dumps(report, ensure_ascii=False, allow_nan=False).encode("utf-8")) > PAYLOAD_UTF8_BYTES:
        raise ValueError(f"progress exceeds {PAYLOAD_UTF8_BYTES} serialized UTF-8 bytes")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError(f"non-JSON numeric constant: {value}")


def inspect_trial(directory):
    """Return a JSON-compatible report; directory access errors propagate."""
    directory = Path(directory)
    paths = sorted(
        (path for path in directory.iterdir() if CHECKPOINT_NAME.fullmatch(path.name)),
        key=lambda path: (int(CHECKPOINT_NAME.fullmatch(path.name)[1]), path.name),
    )
    counts = dict.fromkeys((
        "checkpoint_file_count", "report_count", "missing_progress_count",
        "malformed_record_count", "malformed_report_count", "unreadable_file_count",
    ), 0)
    counts["checkpoint_file_count"] = len(paths)
    diagnostics, reports, report_files = [], [], []

    def diagnostic(path, kind, message):
        counts[kind + "_count"] += 1
        diagnostics.append({"file": path.name, "kind": kind, "message": message})

    for path in paths:
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                raise OSError("checkpoint is not a regular file (symlinks are not followed)")
            content = path.read_text(encoding="utf-8")
        except OSError as error:
            diagnostic(path, "unreadable_file", str(error))
            continue
        except UnicodeError as error:
            diagnostic(path, "malformed_record", str(error))
            continue
        try:
            record = json.loads(content, object_pairs_hook=_object, parse_constant=_nonfinite)
            if not isinstance(record, dict):
                raise ValueError("checkpoint must be a JSON object")
        except (ValueError, RecursionError) as error:
            diagnostic(path, "malformed_record", str(error))
            continue
        if "progress" not in record:
            diagnostic(path, "missing_progress", "checkpoint has no progress field")
            continue
        try:
            _report_shape(record["progress"])
        except (ValueError, UnicodeError, RecursionError) as error:
            diagnostic(path, "malformed_report", str(error))
            continue
        reports.append(record["progress"])
        report_files.append(path.name)
    counts["report_count"] = len(reports)
    if not paths:
        diagnostics.append({"file": None, "kind": "no_checkpoints", "message": "no accepted checkpoint filenames found"})
    return {
        "counts": counts,
        "report_files": report_files,
        "diagnostics": diagnostics,
        "summary": summarize(reports),
        "notice": "Unverified model claims; counts establish neither completion nor futility. Evidence citations are not resolved.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial_directory", type=Path)
    args = parser.parse_args(argv)
    try:
        result = inspect_trial(args.trial_directory)
    except OSError as error:
        print(json.dumps({"error": str(error)}))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return int(any(item["kind"] != "no_checkpoints" for item in result["diagnostics"]))


if __name__ == "__main__":
    raise SystemExit(main())
