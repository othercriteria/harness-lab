"""Read-only checkpoint audit supplement; not a coding or lifecycle verdict.

Campaign audits must also check ordinary requests, reset/archive conformance,
isolation, cleanup and evaluator outcomes. No candidate code is imported here.
"""

import hashlib
import json
from pathlib import Path

from context_checkpoint import REPLY_TOKENS, REQUEST, THINK_TOKENS, TOOL, action
from mini_bootstrap import FormatError


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    with path.open("rb") as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    require(len(raw) <= 4 * 1024 * 1024, "Checkpoint evidence size bound")
    return json.loads(raw)


def verify_checkpoint_evidence(directory, limits):
    """Raise on mismatches; retain explicit unknown usage on interrupted requests."""
    root = Path(directory)
    artifacts = list(root.glob("context-checkpoint-*.json"))
    allowed = {
        "context-checkpoint-request-001.json",
        "context-checkpoint-response-001.json",
        "context-checkpoint-001.json",
    }
    require(all(p.name in allowed for p in artifacts), "Unexpected checkpoint attempt")
    enabled = (limits.get("fresh_context") or {}).get("summary_checkpoint", False)
    require(enabled or not artifacts, "Checkpoint artifacts without enabled policy")
    requests = sorted(root.glob("request-*.request.json"))
    require(len(requests) <= limits["step_limit"], "Model-call allowance exceeded")
    offer_path = root / "context-checkpoint-request-001.json"
    offer = read(offer_path) if offer_path.exists() else None
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
            sum(t == TOOL for t in tools) == int(enabled),
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
        if index == checkpoint_index:
            before_tokens = total
            cap = min(cap, REPLY_TOKENS)
            require(
                offer["completion_tokens"] == total, "Checkpoint offer renewed tokens"
            )
            notice = {"role": "user", "content": REQUEST}
            require(offer["notice"] == notice, "Checkpoint instructions changed")
            require(
                notice in payload["messages"], "Checkpoint request lacks invitation"
            )
        require(
            payload["max_tokens"] == cap > 0, "Cumulative/context/reply cap differs"
        )
        if "reasoning_budget_tokens" in limits:
            expected = limits["reasoning_budget_tokens"]
            if index == checkpoint_index:
                expected = min(expected, THINK_TOKENS)
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
            not (root / "context-checkpoint-response-001.json").exists(),
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
        )[0]
    except FormatError:
        accepted = None
    receipt = read(root / "context-checkpoint-response-001.json")
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
    tool_index = offer["tool_calls"] + 1
    control_path = root / f"tool-{tool_index:03d}.request.json"
    saved_path = root / "context-checkpoint-001.json"
    saved = read(saved_path) if saved_path.exists() else None
    if saved:
        require(accepted is not None, "Rejected response produced saved memory")
        require(
            saved["summary"] == accepted["payload"]["summary"],
            "Saved memory differs from response",
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
    reset_path = root / "fresh-context-reset-001.json"
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
            require(
                reset["notice"]["content"].endswith(
                    json.dumps(accepted["payload"], ensure_ascii=False)
                ),
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
