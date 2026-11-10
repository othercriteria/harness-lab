"""Audit first-submission review evidence without executing candidate code.

Migrated from frozen097's helper. A verified deadline interruption can leave the
last sandbox without a result; retain that unknown observation without inventing
output or treating a failed attempt as successful. Frozen audit output is unchanged.
"""

import hashlib
import json

from fresh_context import REVIEW_INSTRUCTION, validate_history_archive, visible_message


def read(path):
    return json.loads(path.read_text())


def require(ok, message):
    if not ok:
        raise ValueError(message)


def reset_conformance(path, protocol, raw):
    report = {"conforming": False, "interrupted_tools": []}
    try:
        policy = protocol["fresh_context"]
        require(policy["trigger"] == "first_submission", "Wrong trigger")
        state = raw["usage"]["fresh_context"]
        require(state["trigger"] == "first_submission", "Missing summary trigger")
        events = list(path.glob("fresh-context-reset-*.json"))
        offers = list(path.glob("fresh-context-submission-offer-*.json"))
        tools = sorted(path.glob("tool-*.request.json"))
        controls = []
        for p in tools:
            request = read(p)
            result_path = p.with_name(p.name.replace("request", "result"))
            if not result_path.exists():
                # Only the last ordinary sandbox may have been interrupted. Missing
                # intermediate outputs or atomic adapter controls are evidence gaps.
                require(
                    p == tools[-1]
                    and request.get("mode") == "tool"
                    and request.get("name") in ("execute", "edit_file", "write_file"),
                    "Missing nonterminal/control tool result",
                )
                require(
                    raw.get("agent_error", {}).get("type") == "DeadlineExceeded"
                    and raw.get("clean_agent_completion") is False
                    and raw.get("success") is False,
                    "Missing tool result without failed deadline outcome",
                )
                cleanup = read(p.with_name(p.name.replace("request", "cleanup")))
                require(
                    cleanup.get("verified") is True
                    and cleanup.get("owned_process_reaped") is True,
                    "Interrupted tool cleanup not verified",
                )
                messages = read(path / "trajectory.json")["messages"]
                require(
                    messages[-1].get("role") == "exit"
                    and messages[-1].get("extra", {}).get("exit_status")
                    == "DeadlineExceeded",
                    "Missing terminal deadline trace",
                )
                report["interrupted_tools"].append(
                    {
                        "request": p.name,
                        "result": None,
                        "reason": "terminal_deadline_interruption",
                        "cleanup_verified": True,
                    }
                )
                continue
            result = read(result_path)
            if result.get("review_control"):
                require(
                    request["mode"] == "adapter-control"
                    and request["name"] == "finish_attempt"
                    and request["executed"] is False
                    and request["arguments"]["disposition"] == "submitted"
                    and result["ok"] is True
                    and result["executed"] is False
                    and result["cleanup_required"] is False
                    and "terminal_control" not in result,
                    "Invalid provisional control",
                )
                require(
                    not p.with_name(p.name.replace("request", "cleanup")).exists(),
                    "Fake control cleanup",
                )
                controls.append(int(p.name.split("-")[1].split(".")[0]))
            elif request["name"] != "finish_attempt":
                require(
                    read(p.with_name(p.name.replace("request", "cleanup")))["verified"]
                    is True,
                    "Unverified tool cleanup",
                )
        require(
            len(controls) <= 1 and len(offers) == len(controls),
            "Repeated/unpaired review offer",
        )
        if not events:
            require(
                state["reset_applied"] is False and not (path / "history").exists(),
                "Unreported projection",
            )
            # Pending means no valid offered submission. Bypass/refusal remain visible;
            # accepted conformance here is conservative and requires manual review.
            require(
                not controls and state["decision"] in ("pending", "bypassed"),
                "Unverified no-reset branch",
            )
            report.update(
                conforming=True,
                status="no_review_delivered",
                decision=state["decision"],
            )
            return report
        require(
            len(events) == 1 and len(controls) == 1,
            "Reset without unique provisional handoff",
        )
        e = read(events[0])
        offer = read(offers[0])
        require(
            state["reset_applied"] is True and state["decision"] == "applied",
            "Summary/reset disagreement",
        )
        require(
            e["submission_tool"] == controls[0] == e["tool_calls"],
            "Review boundary has later work",
        )
        require(
            e["continuation_mode"] == "review"
            and e["notice"]["content"].endswith(REVIEW_INSTRUCTION),
            "Review continuation changed",
        )
        t = e["timing"]
        b = e["boundary_timing"]
        require(
            t["after_elapsed_agent_fraction"] is None
            and t["nominal_elapsed_seconds"] is None,
            "Elapsed trigger leaked",
        )
        require(
            t["remaining_agent_seconds"] >= policy["min_remaining_agent_seconds"],
            "Below remaining-time floor",
        )
        require(
            0 < t["original_agent_budget_seconds"] <= protocol["agent_wall_seconds"],
            "Original allowance changed",
        )
        require(
            t["original_agent_deadline_monotonic"]
            == t["original_agent_started_monotonic"]
            + t["original_agent_budget_seconds"],
            "Clock inconsistent",
        )
        require(
            t["original_agent_deadline_monotonic"]
            == b["original_agent_deadline_monotonic"]
            == offer["timing"]["original_agent_deadline_monotonic"],
            "Deadline renewed",
        )
        messages = read(path / "trajectory.json")["messages"]
        boundary = e["boundary_messages"]
        require(
            messages[boundary] == e["notice"], "Notice not in complete outer trajectory"
        )
        archive = validate_history_archive(path / "history", path / "tool-boundary")
        manifest = read(archive / "manifest.json")
        require(
            hashlib.sha256((archive / "manifest.json").read_bytes()).hexdigest()
            == e["archive_manifest_sha256"],
            "Archive digest",
        )
        archived = [read(archive / r["file"]) for r in manifest["messages"]]
        require(
            archived == [visible_message(m) for m in messages[:boundary]],
            "History not exact",
        )
        require(
            archived[-2]["tool_calls"][0]["function"]["name"] == "finish_attempt"
            and "not yet accepted" in archived[-1]["content"],
            "Provisional cycle absent",
        )
        total = sum(
            read(path / f"request-{i:03d}.response.bin")["usage"]["completion_tokens"]
            for i in range(1, e["model_calls"] + 1)
        )
        require(total == e["completion_tokens"], "Counter mismatch")
        r = e["remaining_at_notice"]
        require(
            r["completion_tokens"] == protocol["total_completion_token_limit"] - total
            and r["model_calls"] == protocol["step_limit"] - e["model_calls"]
            and r["tool_calls"] == protocol["tool_call_limit"] - e["tool_calls"],
            "Allowances renewed",
        )
        require(
            abs(r["agent_seconds"] - t["remaining_agent_seconds"]) <= 1,
            "Notice clock mismatch",
        )
        next_request = read(path / f"request-{e['model_calls'] + 1:03d}.request.json")
        tail = len(next_request["messages"]) - 2
        require(
            tail in (1, 2)
            and next_request["messages"]
            == [
                visible_message(m)
                for m in [*messages[:2], *messages[boundary : boundary + tail]]
            ],
            "Fresh request projection differs",
        )
        if tail == 2:
            require(
                "budget_notice" in messages[boundary + 1].get("extra", {}),
                "Unexpected continuation",
            )
        report.update(
            conforming=True,
            status="one_submission_review",
            tool=controls[0],
            model_calls_before_review=e["model_calls"],
            completion_tokens_before_review=total,
            remaining_agent_seconds=t["remaining_agent_seconds"],
            archive_messages=len(archived),
            exact_archive=True,
        )
    except (ValueError, KeyError, TypeError, IndexError, OSError) as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    return report
