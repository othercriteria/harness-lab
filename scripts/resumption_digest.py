"""Bounded facts from this attempt's public snapshots and recorded observations.

Read files as data only. Neither model memory nor evaluator artifacts are inputs.
Matching a check's directory identity is not proof of correctness or freshness of
external dependencies, /tmp, process state, or Git metadata outside observed HEAD.
"""

# Keep encoded and text_field importable here for older callers.
from json_text import encoded, text_field
from run_checks import identity, snapshot

MAX_BYTES = 4096
MAX_FILES = 24
MAX_CHECKS = 3


def build(initial_workspace, workspace, history):
    start = (
        snapshot(initial_workspace, ".")
        if initial_workspace is not None
        else {"status": "unavailable"}
    )
    current = snapshot(workspace, ".")
    return from_snapshots(start, current, history, lambda cwd: identity(workspace, cwd))


def from_snapshots(start, current, history, current_identity):
    result = {
        "kind": "attempt_public_facts",
        "scope": "File deltas compare task-start and current regular files/modes, excluding .git. Added files were absent at start; this does not establish authorship. Recent checks list run_checks records only, not bash checks. Comparisons cover only recorded cwd, not dependencies elsewhere, /tmp or coverage/correctness. Paths and commands are untrusted data.",
        "file_comparison": "unavailable",
        "changed_files": [],
        "changed_files_omitted": 0,
        "recent_checks": [],
        "recent_checks_omitted": 0,
    }
    changes = []
    if start["status"] == current["status"] == "captured":
        old, new = start["files"], current["files"]
        for path in sorted(old.keys() | new.keys()):
            if old.get(path) == new.get(path):
                continue
            changes.append(
                {
                    "path": text_field(path),
                    "path_clipped": text_field(path) != path,
                    "change": "added_since_start"
                    if path not in old
                    else "removed_since_start"
                    if path not in new
                    else "modified_from_start",
                }
            )
        result["file_comparison"] = "captured"
        result["current_tree_sha256"] = current["tree_sha256"]
        result["changed_files_total"] = len(changes)
    records = [r for r in history.records.values() if "check_record" in r]
    # Root-scoped checks use the same current snapshot as the task-start comparison.
    states = {".": current}
    for record in records[-MAX_CHECKS:]:
        check = record["check_record"]
        cwd = check["cwd"]
        # cwd is from a validated tool call, never parsed from model-written text.
        if cwd not in states:
            states[cwd] = current_identity(cwd)
        now, after = states[cwd], check["after"]
        comparable = now.get("status") == after.get("status") == "captured"
        result["recent_checks"].append(
            {
                "observation_id": record["id"],
                "check_id": check["id"],
                "cwd": text_field(cwd),
                "cwd_clipped": text_field(cwd) != cwd,
                "command": text_field(record["command"]),
                "command_clipped": text_field(record["command"]) != record["command"],
                "returncode": record["returncode"],
                "exception_info": text_field(check.get("exception_info", "")),
                "exception_info_clipped": text_field(check.get("exception_info", ""))
                != check.get("exception_info", ""),
                "output_truncated": record["originally_truncated"],
                "current_files_match_after_check": now["tree_sha256"]
                == after["tree_sha256"]
                if comparable
                else None,
                "current_head_matches_observed_after_check": (
                    now["git_head"] == after["git_head"]
                    if comparable
                    and now["git_head"].get("status")
                    == after["git_head"].get("status")
                    == "observed_reference_only"
                    else None
                ),
            }
        )
    result["recent_checks_omitted"] = max(0, len(records) - MAX_CHECKS)
    # Facts can be incomplete; omissions are explicit, never silently "no changes".
    result["changed_files"] = changes[:MAX_FILES]
    result["changed_files_omitted"] = len(changes) - len(result["changed_files"])
    while len(encoded(result).encode()) > MAX_BYTES:
        if result["changed_files"]:
            result["changed_files"].pop()
            result["changed_files_omitted"] += 1
        elif result["recent_checks"]:
            result["recent_checks"].pop(0)
            result["recent_checks_omitted"] += 1
        else:
            raise ValueError("Resumption digest fixed metadata exceeds bound")
    return result
