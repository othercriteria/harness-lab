"""Read-only checkpoint audit supplement; not a coding or lifecycle verdict.

Campaign audits must also check ordinary requests, reset/archive conformance,
isolation, cleanup and evaluator outcomes. No candidate code is imported here.
"""

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

from context_checkpoint import (
    REPLY_TOKENS,
    THINK_TOKENS,
    action,
    citations,
    repair_request,
    request,
    tool,
)
from mini_bootstrap import FormatError
from checkpoint_policy import allow_finalization


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    with path.open("rb") as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    require(len(raw) <= 4 * 1024 * 1024, "Checkpoint evidence size bound")
    return json.loads(raw)


def terminal_checkpoint(root, sequence, model_index, tool_index, action, request_count):
    """Audit terminal dispatch separately from merely accepting its response."""
    require(model_index == request_count, "Continued inference after terminal checkpoint response")
    require(
        not (root / f"context-checkpoint-{sequence:03d}.json").exists()
        and not (root / f"fresh-context-reset-{sequence:03d}.json").exists(),
        "Terminal checkpoint produced memory or reset",
    )
    later = [
        p for p in root.glob("tool-*.request.json")
        if re.fullmatch(r"tool-[0-9]+\.request\.json", p.name)
        and int(p.name.split("-")[1].split(".")[0]) > tool_index
    ]
    require(not later, "Continued tools after terminal checkpoint response")
    control_path = root / f"tool-{tool_index:03d}.request.json"
    result_path = root / f"tool-{tool_index:03d}.result.json"
    handoff_path = root / "final-handoff.json"
    summary_path = root / "summary.json"
    claimed_complete = summary_path.exists() and read(summary_path).get("clean_agent_completion") is True
    if not control_path.exists():
        require(not result_path.exists() and not handoff_path.exists() and not claimed_complete,
                "Terminal completion claimed without dispatch")
        return "valid_finalization_not_dispatched"
    control = read(control_path)
    require(
        control.get("mode") == "adapter-control"
        and control.get("name") == "finish_attempt"
        and control.get("executed") is False
        and control.get("arguments") == action["payload"],
        "Invalid checkpoint finalization dispatch",
    )
    if not result_path.exists():
        require(not claimed_complete, "Terminal completion claimed without result")
        return "finalization_dispatch_incomplete"
    result = read(result_path)
    expected = "Submitted" if action["payload"]["disposition"] == "submitted" else "Blocked"
    require(
        result.get("terminal_control") == expected
        and result.get("ok") is True
        and result.get("executed") is False
        and result.get("cleanup_required") is False
        and result.get("handoff_status") == "unverified_model_handoff"
        and "review_control" not in result
        and "checkpoint_control" not in result,
        "Invalid checkpoint terminal receipt",
    )
    handoff = read(handoff_path)
    require(handoff.get("handoff") == action["payload"], "Terminal handoff differs from response")
    require(handoff.get("status") == "unverified_model_handoff", "Terminal handoff claimed verification")
    return "finalized"


def verify_checkpoint_evidence(directory, limits):
    """Raise on mismatches; retain explicit unknown usage on interrupted requests."""
    root = Path(directory)
    policy = limits.get("fresh_context") or {}
    maximum = policy.get("max_resets", 1)
    sequences = sorted(
        {
            int(p.stem.rsplit("-", 1)[1])
            for p in root.glob("context-checkpoint-request-*.json")
        }
    )
    allowed = {
        f"{stem}-{n:03d}.json"
        for n in sequences
        for stem in (
            "context-checkpoint-request",
            "context-checkpoint-response",
            "context-checkpoint",
            "context-checkpoint-repair-request",
            "context-checkpoint-repair-response",
            "context-checkpoint-repair-decision",
        )
    }
    require(
        all(p.name in allowed for p in root.glob("context-checkpoint-*.json")),
        "Unexpected checkpoint artifact",
    )
    require(
        all(1 <= n <= maximum for n in sequences), "Checkpoint reset bound exceeded"
    )
    indices = {
        read(root / f"context-checkpoint-request-{n:03d}.json")["model_calls"] + 1
        for n in sequences
    }
    require(len(indices) == len(sequences), "Duplicate checkpoint request")
    repairs = {}
    for n in sequences:
        path = root / f"context-checkpoint-repair-request-{n:03d}.json"
        if path.exists():
            offer = read(path)
            original = read(root / f"context-checkpoint-request-{n:03d}.json")
            rejected = read(root / f"context-checkpoint-response-{n:03d}.json")
            decision = read(root / f"context-checkpoint-repair-decision-{n:03d}.json")
            require(
                rejected["status"] == "rejected_response",
                "Repair after accepted checkpoint",
            )
            require(
                offer["model_calls"]
                == rejected["model_calls"]
                == original["model_calls"] + 1,
                "Repair is not immediately after rejection",
            )
            require(
                offer["tool_calls"] == original["tool_calls"],
                "Rejected checkpoint executed tools",
            )
            require(
                offer.get("observation_manifest")
                == original.get("observation_manifest"),
                "Repair evidence changed",
            )
            require(
                decision["status"] == "offered"
                and offer["context"] == decision["context"],
                "Repair decision mismatch",
            )
            require(
                offer["context"]["available_completion_tokens"] >= 2560
                and offer["context"]["available_completion_tokens"]
                == limits["context_capacity_tokens"]
                - offer["context"]["input_tokens"]
                - limits["context_policy"]["safety_tokens"],
                "Repair lacks context reserve",
            )
            require(
                offer["timing"]["original_agent_deadline_monotonic"]
                == original["timing"]["original_agent_deadline_monotonic"]
                and offer["timing"]["remaining_agent_seconds"]
                >= policy["min_remaining_agent_seconds"],
                "Repair renewed or exhausted deadline",
            )
            require(
                offer["model_calls"] + 1 < limits["step_limit"]
                and offer["tool_calls"] + 1 < limits.get("tool_call_limit", 128)
                and limits["total_completion_token_limit"] - offer["completion_tokens"]
                > REPLY_TOKENS,
                "Repair lacks continuation allowance",
            )
            index = offer["model_calls"] + 1
            measured_path = root / f"context-{index:03d}.json"
            if measured_path.exists():
                require(
                    read(measured_path)["input_tokens_after"]
                    == offer["context"]["input_tokens"],
                    "Repair context measurement differs from actual request",
                )
            require(index not in indices, "Duplicate repair request")
            indices.add(index)
            repairs[n] = True
    rows = []
    for n in sequences or [1]:
        first = _verify_checkpoint(
            root, limits, n, indices, followed_by_repair=n in repairs
        )
        if n in repairs:
            row = _verify_checkpoint(root, limits, n, indices, repair=True)
            row["initial_attempt"] = first
            rows.append(row)
        else:
            rows.append(first)
    if policy.get("trigger") == "context_headroom":
        return {
            "status": "repeated_policy",
            "checkpoints": rows if sequences else [],
            "checkpoint_requests": sorted(indices),
            "known_completion_tokens": rows[0]["known_completion_tokens"],
            "all_usage_known": rows[0]["all_usage_known"],
        }
    return rows[0]


def _verify_checkpoint(
    root,
    limits,
    sequence,
    checkpoint_indices,
    *,
    repair=False,
    followed_by_repair=False,
):
    artifacts = list(root.glob(f"context-checkpoint*-{sequence:03d}.json"))
    enabled = (limits.get("fresh_context") or {}).get("summary_checkpoint", False)
    require(enabled or not artifacts, "Checkpoint artifacts without enabled policy")
    requests = sorted(root.glob("request-*.request.json"))
    require(len(requests) <= limits["step_limit"], "Model-call allowance exceeded")
    prefix = "context-checkpoint-repair" if repair else "context-checkpoint"
    offer_path = root / f"{prefix}-request-{sequence:03d}.json"
    offer = read(offer_path) if offer_path.exists() else None
    shared = limits.get("shared_evidence", False)
    # Pressure checkpoints are offered only outside active scoped subtasks.
    # Scoped projection/return conformance remains a separate audit.
    can_finish = allow_finalization(limits)
    history = None
    if offer is not None and shared:
        pointer = offer["observation_manifest"]
        require(
            re.fullmatch(r"observations-[0-9]{3}\.manifest\.json", pointer["name"]),
            "Invalid observation manifest pointer",
        )
        manifest_path = root / pointer["name"]
        require(
            hashlib.sha256(manifest_path.read_bytes()).hexdigest() == pointer["sha256"],
            "Observation manifest changed",
        )
        records = read(manifest_path)["observations"]
        visible = {}
        for item in records:
            identifier = item["id"]
            require(re.fullmatch(r"o[0-9]{4}", identifier), "Invalid observation ID")
            require(
                item["message_file"]
                in (identifier + ".json", identifier + ".message.txt"),
                "Invalid observation message filename",
            )
            path = root / "observations" / item["message_file"]
            require(
                path.stat().st_size <= 131072 and not path.is_symlink(),
                "Invalid observation message file",
            )
            visible[identifier] = path.read_text()
        history = SimpleNamespace(
            expose_ids=True,
            records={r["id"]: r for r in records},
            visible_messages=visible,
        )
    checkpoint_index = offer["model_calls"] + 1 if offer else None
    total = 0
    tools = None
    checkpoint_response = None
    before_tokens = None
    unknown_requests = []
    for index, path in enumerate(requests, 1):
        require(
            path.name == f"request-{index:03d}.request.json", "Noncontiguous requests"
        )
        payload = read(path)
        if tools is None:
            tools = payload["tools"]
        require(payload["tools"] == tools, "Tool prefix changed during attempt")
        require(
            sum(
                t == tool(shared, progress=limits.get("checkpoint_progress", False))
                for t in tools
            )
            == int(enabled),
            "Checkpoint schema differs from enabled policy",
        )
        context = read(root / f"context-{index:03d}.json")
        cap = min(
            limits["max_completion_tokens_per_request"],
            limits["total_completion_token_limit"] - total,
            limits["context_capacity_tokens"]
            - context["input_tokens_after"]
            - limits["context_policy"]["safety_tokens"],
        )
        if index in checkpoint_indices:
            cap = min(cap, REPLY_TOKENS)
        if index == checkpoint_index:
            before_tokens = total
            require(
                offer["completion_tokens"] == total, "Checkpoint offer renewed tokens"
            )
            notice = {
                "role": "user",
                "content": repair_request(
                    shared, progress=limits.get("checkpoint_progress", False),
                    allow_finish=can_finish,
                )
                if repair
                else request(shared, progress=limits.get("checkpoint_progress", False),
                             allow_finish=can_finish),
            }
            require(offer["notice"] == notice, "Checkpoint instructions changed")
            require(
                notice in payload["messages"], "Checkpoint request lacks invitation"
            )
        require(
            payload["max_tokens"] == cap > 0, "Cumulative/context/reply cap differs"
        )
        if "reasoning_budget_tokens" in limits:
            expected = limits["reasoning_budget_tokens"]
            if index in checkpoint_indices:
                expected = min(expected, THINK_TOKENS)
            if "reasoning_deadline" in limits:
                from reasoning_deadline import allocate

                allocation = read(root / f"request-{index:03d}.reasoning-budget.json")
                expected_allocation = allocate(
                    limits["reasoning_deadline"],
                    expected,
                    allocation["agent_deadline_monotonic"],
                    allocation["allocated_at_monotonic"],
                )
                require(
                    allocation == expected_allocation, "Reasoning allocation differs"
                )
                expected = allocation["effective_reasoning_cap"]
            require(
                payload["reasoning_budget_tokens"] == expected, "Thinking cap differs"
            )
        else:
            require("reasoning_budget_tokens" not in payload, "Undeclared thinking cap")
        response_path = root / f"request-{index:03d}.response.bin"
        try:
            response = read(response_path)
            usage = response["usage"]
            require(
                all(
                    type(usage.get(k)) is int and usage[k] >= 0
                    for k in ("completion_tokens", "prompt_tokens")
                ),
                "Invalid usage",
            )
        except (OSError, ValueError, KeyError, TypeError):
            require(index == len(requests), "Continued after unknown request usage")
            unknown_requests.append(index)
            # A later timeout does not erase earlier checkpoint evidence. Check
            # its provenance/receipts below without inventing final usage.
            break
        require(usage["completion_tokens"] <= cap, "Response exceeded reply cap")
        total += usage["completion_tokens"]
        if index == checkpoint_index:
            checkpoint_response = response
    accounting = {
        "known_completion_tokens": total,
        "all_usage_known": not unknown_requests,
        "unknown_requests": unknown_requests,
        "checkpoint_request": checkpoint_index,
    }
    if offer is None:
        require(not artifacts, "Checkpoint output without invitation")
        return {
            "status": "not_requested",
            **accounting,
        }
    if checkpoint_response is None:
        require(
            not (root / f"{prefix}-response-{sequence:03d}.json").exists(),
            "Response without request",
        )
        return {
            "status": "checkpoint_response_unavailable"
            if checkpoint_index in unknown_requests
            else "offered_without_response",
            **accounting,
        }
    choice = checkpoint_response["choices"][0]
    try:
        accepted = action(
            choice["message"],
            checkpoint_response,
            choice.get("finish_reason"),
            requested=True,
            shared=shared,
            progress=limits.get("checkpoint_progress", False),
            history=history,
            allow_finish=can_finish,
        )[0]
    except FormatError:
        accepted = None
    receipt = read(root / f"{prefix}-response-{sequence:03d}.json")
    require(
        receipt["model_calls"] == checkpoint_index,
        "Checkpoint response request mismatch",
    )
    require(
        receipt["completion_tokens"]
        == before_tokens + checkpoint_response["usage"]["completion_tokens"],
        "Checkpoint response usage mismatch",
    )
    require(
        receipt["status"] == ("valid_response" if accepted else "rejected_response"),
        "Parser verdict differs",
    )
    require(receipt["executed"] is False, "Response claimed command execution")
    require(receipt.get("accepted_tool") == (accepted["tool"] if accepted else None),
            "Checkpoint response tool differs from parser verdict")
    if followed_by_repair:
        require(accepted is None, "Only rejected responses may be repaired")
        return {
            "status": "rejected",
            "summary_completion_tokens": checkpoint_response["usage"][
                "completion_tokens"
            ],
            **accounting,
        }
    tool_index = offer["tool_calls"] + 1
    if accepted is not None and accepted["tool"] == "finish_attempt":
        status = terminal_checkpoint(
            root, sequence, checkpoint_index, tool_index, accepted, len(requests)
        )
        return {
            "status": status,
            "disposition": accepted["payload"]["disposition"],
            "summary_completion_tokens": 0,
            "finalization_completion_tokens": checkpoint_response["usage"]["completion_tokens"],
            **accounting,
        }
    control_path = root / f"tool-{tool_index:03d}.request.json"
    saved_path = root / f"context-checkpoint-{sequence:03d}.json"
    saved = read(saved_path) if saved_path.exists() else None
    if saved:
        require(accepted is not None, "Rejected response produced saved memory")
        require(
            saved["summary"] == accepted["payload"]["summary"],
            "Saved memory differs from response",
        )
        require(
            saved.get("progress") == accepted["payload"].get("progress"),
            "Saved progress differs from model report",
        )
        if "progress" in accepted["payload"]:
            measurement = saved.get("progress_measurement", {})
            require(
                measurement.get("status") == "unverified_model_report"
                and measurement.get("elicitation") == "context_checkpoint"
                and measurement.get("report_utf8_bytes")
                == len(json.dumps(saved["progress"], ensure_ascii=False).encode()),
                "Saved progress measurement differs",
            )
        if shared:
            from evidence import resolve

            expected = citations(accepted["payload"])
            require(
                saved["evidence"] == expected, "Saved evidence differs from response"
            )
            require(
                saved["observations"] == resolve(expected, history),
                "Saved observations differ from historical evidence",
            )
        require(
            saved["tool_call"] == tool_index
            and saved["model_call"] == checkpoint_index,
            "Control counters differ",
        )
        control = read(control_path)
        result = read(root / f"tool-{tool_index:03d}.result.json")
        require(
            control["mode"] == "adapter-control"
            and control["name"] == "checkpoint_context"
            and control["executed"] is False
            and control["arguments"] == accepted["payload"],
            "Invalid checkpoint control",
        )
        require(
            result["checkpoint_control"] == "summary_saved"
            and result["executed"] is False
            and result["cleanup_required"] is False
            and "terminal_control" not in result,
            "Invalid checkpoint result",
        )
    elif control_path.exists():
        require(
            read(control_path).get("name") != "checkpoint_context",
            "Checkpoint control without saved memory",
        )
    reset_path = root / f"fresh-context-reset-{sequence:03d}.json"
    if reset_path.exists():
        reset = read(reset_path)
        expected = {
            "status": "retained" if saved else "fallback_without_summary",
            "tool_call": tool_index if saved else None,
            "summary_sha256": hashlib.sha256(saved["summary"].encode()).hexdigest()
            if saved
            else None,
        }
        require(
            reset["summary_checkpoint"] == expected, "Reset memory provenance differs"
        )
        if saved:
            suffix = json.dumps(accepted["payload"], ensure_ascii=False)
            if shared:
                from evidence import render

                suffix += "\nHistorical evidence:\n" + render(
                    citations(accepted["payload"]), history
                )
            require(
                reset["notice"]["content"].endswith(suffix),
                "Reset omitted/changed saved memory",
            )
        require(
            reset["timing"]["original_agent_deadline_monotonic"]
            == offer["timing"]["original_agent_deadline_monotonic"],
            "Checkpoint renewed deadline",
        )
    return {
        "status": "saved"
        if saved
        else "rejected"
        if accepted is None
        else "valid_response_not_saved",
        "summary_completion_tokens": checkpoint_response["usage"]["completion_tokens"],
        **accounting,
    }
