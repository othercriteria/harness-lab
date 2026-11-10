"""Read-only evidence checks for repeated measured-headroom context recovery."""

import hashlib
from pathlib import Path

from checkpoint_evidence import read, require, verify_checkpoint_evidence
from fresh_context import validate_history_archive, visible_message


def verify_pressure_recovery(directory, limits, raw):
    root = Path(directory)
    policy = limits["fresh_context"]
    require(policy["trigger"] == "context_headroom", "Wrong recovery policy")
    trajectory = read(root / "trajectory.json")["messages"]
    events = sorted(root.glob("fresh-context-reset-*.json"))
    require(len(events) <= policy["max_resets"], "Reset allowance exceeded")
    checkpoints = verify_checkpoint_evidence(root, limits)
    state = raw.get("usage", {}).get("fresh_context", {})
    require(state.get("reset_count") == len(events), "Summary/reset count mismatch")
    require(
        state.get("max_resets") == policy["max_resets"], "Summary/reset limit mismatch"
    )
    deadline = None
    previous_boundary = 2
    previous_calls = -1
    archive_names = set()
    rows = []
    for sequence, path in enumerate(events, 1):
        require(
            path.name == f"fresh-context-reset-{sequence:03d}.json",
            "Reset sequence gap",
        )
        event = read(path)
        timing = event["timing"]
        if deadline is None:
            deadline = timing["original_agent_deadline_monotonic"]
        for clock in (timing, event["boundary_timing"]):
            require(
                clock["original_agent_deadline_monotonic"] == deadline,
                "Reset renewed deadline",
            )
            require(
                0
                < clock["original_agent_budget_seconds"]
                <= limits["agent_wall_seconds"],
                "Invalid original clock",
            )
            require(
                clock["original_agent_started_monotonic"]
                + clock["original_agent_budget_seconds"]
                == deadline,
                "Clock arithmetic",
            )
            require(
                clock["minimum_remaining_agent_seconds"]
                == policy["min_remaining_agent_seconds"]
                and clock["remaining_agent_seconds"]
                >= policy["min_remaining_agent_seconds"],
                "Reset time floor",
            )
        boundary = event["boundary_messages"]
        calls = event["model_calls"]
        require(
            previous_boundary < boundary < len(trajectory) and calls > previous_calls,
            "Reset without progress",
        )
        previous_boundary, previous_calls = boundary, calls
        require(
            event["status"] == "applied"
            and event["trigger"]
            == "measured context headroom at a completed tool-cycle boundary",
            "Reset trigger changed",
        )
        require(
            trajectory[boundary] == event["notice"], "Reset notice differs from trace"
        )
        archive_name = "history" if sequence == 1 else f"history-{sequence:03d}"
        require(event["archive_directory"] == archive_name, "Archive identity")
        archive_names.add(archive_name)
        archive = validate_history_archive(root / archive_name, root / "tool-boundary")
        manifest = read(archive / "manifest.json")
        require(
            hashlib.sha256((archive / "manifest.json").read_bytes()).hexdigest()
            == event["archive_manifest_sha256"],
            "Archive hash",
        )
        require(len(manifest["messages"]) == boundary, "Archive boundary mismatch")
        for i, message in enumerate(trajectory[:boundary], 1):
            require(
                read(archive / f"m{i:04d}.json") == visible_message(message),
                "Archive leaked or changed history",
            )
        pressure = event["context_pressure"]
        require(
            pressure["threshold_tokens"] == policy["headroom_tokens"]
            and pressure["available_completion_tokens"] <= policy["headroom_tokens"],
            "Unjustified context trigger",
        )
        idx = pressure["model_calls"] + 1
        measured = read(root / f"context-{idx:03d}.pressure.json")
        require(
            measured["input_tokens_after"] == pressure["input_tokens"]
            and measured["available_completion_tokens"]
            == pressure["available_completion_tokens"],
            "Pressure measurement changed",
        )
        tokenization = (
            root / f"context-{idx:03d}.pressure.before.tokenize.response.json"
        )
        require(
            len(read(tokenization)["tokens"]) == pressure["input_tokens"],
            "Pressure rendered count mismatch",
        )
        require(
            limits["context_capacity_tokens"]
            - pressure["input_tokens"]
            - limits["context_policy"]["safety_tokens"]
            == pressure["available_completion_tokens"],
            "Pressure arithmetic",
        )
        skipped = pressure["available_completion_tokens"] < 2560
        require(
            event["summary_skipped_insufficient_headroom"] == skipped,
            "Summary fallback trigger",
        )
        offer = root / f"context-checkpoint-request-{sequence:03d}.json"
        if skipped:
            require(
                not offer.exists()
                and event["summary_checkpoint"]
                == {
                    "status": "fallback_without_summary",
                    "tool_call": None,
                    "summary_sha256": None,
                },
                "Unexpected summary after headroom fallback",
            )
        else:
            require(
                read(offer)["context_pressure"] == pressure,
                "Checkpoint pressure provenance",
            )
        measurement = read(root / f"fresh-context-measurement-{sequence:03d}.json")
        post = read(root / f"context-{calls + 1:03d}.json")
        require(
            measurement["input_tokens_after_reset_and_notices"]
            == post["input_tokens_after"]
            and measurement["wire_sha256"] == post["wire_sha256"],
            "Reset measurement mismatch",
        )
        before_tokens = read(
            root / f"context-{calls + 1:03d}.reset-before.tokenize.response.json"
        )["tokens"]
        require(
            measurement["input_tokens_before_reset"] == len(before_tokens)
            and measurement["rendered_tokens_reclaimed"]
            == len(before_tokens) - post["input_tokens_after"],
            "Reclaimed-token arithmetic",
        )
        require(
            event["remaining_at_notice"]["completion_tokens"]
            == limits["total_completion_token_limit"] - event["completion_tokens"],
            "Reset renewed tokens",
        )
        require(
            event["remaining_at_notice"]["model_calls"] == limits["step_limit"] - calls
            and event["remaining_at_notice"]["tool_calls"]
            == limits["tool_call_limit"] - event["tool_calls"],
            "Reset renewed calls",
        )
        require(
            abs(
                event["remaining_at_notice"]["agent_seconds"]
                - timing["remaining_agent_seconds"]
            )
            <= 1,
            "Notice clock differs",
        )
        rows.append(
            {
                "sequence": sequence,
                "model_calls": calls,
                "tokens_reclaimed": measurement["rendered_tokens_reclaimed"],
            }
        )
    # Every execution sees the latest completed archive, never an attempt root or
    # the private evaluator. Earlier immutable generations remain outer evidence.
    for path in root.glob("tool-*.invocation.json"):
        number = int(path.name.split("-")[1].split(".")[0])
        applicable = [read(p) for p in events if read(p)["tool_calls"] < number]
        argv = read(path)["argv"]
        if applicable:
            expected = str(root / applicable[-1]["archive_directory"])
            index = argv.index("/history")
            require(
                argv[index - 2 : index + 1] == ["--ro-bind", expected, "/history"],
                "History mount is not current/read-only",
            )
        else:
            require("/history" not in argv, "Archive mounted before reset")
    return {
        "conforming": True,
        "status": "measured_recovery",
        "resets": rows,
        "checkpoint": checkpoints,
    }
