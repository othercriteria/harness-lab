"""Explicit experiment budgets and task split admission, independent of model code."""

import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def profiles():
    return sorted(json.loads((PROJECT / "configs/servers.json").read_text()))


def tasks():
    return sorted(p.parent.name for p in (PROJECT / "tasks").glob("*/task.json"))


def protocols():
    return [
        "mvp",
        *sorted(p.stem for p in (PROJECT / "configs/protocols").glob("*.json")),
    ]


def load_protocol(name, root=PROJECT):
    path = root / (
        "configs/pilot.json" if name == "mvp" else f"configs/protocols/{name}.json"
    )
    if name != "mvp" and (
        not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in name)
    ):
        raise ValueError("Invalid protocol name")
    data = json.loads(path.read_text())
    data.setdefault("tool_call_limit", 24)
    data.setdefault("seed", 42)
    data.setdefault("max_command_bytes", 8192)
    if (
        type(data["max_command_bytes"]) is not int
        or not 8192 <= data["max_command_bytes"] <= 32768
    ):
        raise ValueError("Invalid max_command_bytes")
    if type(data.get("workspace_persistence_feedback", False)) is not bool:
        raise ValueError("Invalid workspace_persistence_feedback")
    for flag in (
        "work_policy_feedback",
        "contract_first_checks",
        "patch_edit_feedback",
        "context_budget_feedback",
        "evidence_audit_feedback",
        "self_test_feedback",
        "spec_blocker_exit",
        "structured_finalization",
        "split_finalization",
        "concise_finalization",
        "terminal_semantics_feedback",
        "exact_text_edit",
        "plain_tool_observations",
        "require_tool_call",
        "whole_file_write",
    ):
        if type(data.get(flag, False)) is not bool:
            raise ValueError(f"Invalid {flag}")
    if data.get("split_finalization", False) and not data.get(
        "structured_finalization", False
    ):
        raise ValueError("split_finalization requires structured_finalization")
    if data.get("exact_text_edit", False):
        if not data.get("structured_finalization", False):
            raise ValueError("exact_text_edit requires structured_finalization")
    if data.get("whole_file_write", False) and not data.get(
        "structured_finalization", False
    ):
        raise ValueError("whole_file_write requires structured_finalization")
    if data.get("concise_finalization", False) and not data.get(
        "structured_finalization", False
    ):
        raise ValueError("concise_finalization requires structured_finalization")
    if data.get("terminal_semantics_feedback", False) and not data.get(
        "structured_finalization", False
    ):
        raise ValueError("terminal_semantics_feedback requires structured_finalization")
    if "open_problem_policy" in data:
        if data["open_problem_policy"] not in (
            "report_blocker",
            "attempt_within_budget",
        ):
            raise ValueError("Unknown open_problem_policy")
        if not (
            data.get("spec_blocker_exit", False)
            or data.get("structured_finalization", False)
        ):
            raise ValueError(
                "open_problem_policy requires spec_blocker_exit or structured_finalization"
            )
    if data.get("self_test_feedback", False) and not data.get(
        "work_policy_feedback", False
    ):
        raise ValueError("self_test_feedback requires work_policy_feedback")
    if data.get("contract_first_checks", False) and not data.get(
        "work_policy_feedback", False
    ):
        raise ValueError("contract_first_checks requires work_policy_feedback")
    if data.get("evidence_audit_feedback", False) and not data.get(
        "work_policy_feedback", False
    ):
        raise ValueError("evidence_audit_feedback requires work_policy_feedback")
    if (
        data.get("context_budget_feedback", False)
        and data.get("context_policy") is None
    ):
        raise ValueError("context_budget_feedback requires measured context_policy")
    if "reasoning_budget_tokens" in data:
        value = data["reasoning_budget_tokens"]
        if type(value) is not int or not 1 <= value <= 32768:
            raise ValueError("Invalid reasoning_budget_tokens")
    if "reasoning_deadline" in data:
        from reasoning_deadline import validate

        validate(data["reasoning_deadline"])
        if (
            "reasoning_budget_tokens" not in data
            or data.get("time_budget_feedback") is not True
        ):
            raise ValueError(
                "reasoning_deadline requires native thinking and time feedback"
            )
    if "initial_repository" in data:
        from initial_repository import validate

        validate(data["initial_repository"])
    if "python_test_library" in data:
        from python_test_library import validate

        validate(data["python_test_library"])
    if "review_reasoning_only" in data:
        from inference_phase import validate

        validate(data)
    if "max_tool_calls_per_response" in data:
        value = data["max_tool_calls_per_response"]
        if type(value) is not int or not 1 <= value <= 8:
            raise ValueError(
                "max_tool_calls_per_response must be an integer from 1 to 8"
            )
    for key in (
        "task_wall_seconds",
        "agent_wall_seconds",
        "verification_reserve_seconds",
        "step_limit",
        "tool_call_limit",
        "max_completion_tokens_per_request",
        "total_completion_token_limit",
        "tool_timeout_seconds",
        "request_timeout_seconds",
        "context_capacity_tokens",
    ):
        if type(data[key]) is not int or data[key] <= 0:
            raise ValueError(f"Expected positive integer {key}")
    if (
        data["agent_wall_seconds"] + data["verification_reserve_seconds"]
        > data["task_wall_seconds"]
    ):
        raise ValueError("Agent ceiling must preserve verification reserve")
    if data["max_completion_tokens_per_request"] > data["total_completion_token_limit"]:
        raise ValueError("Per-request cap exceeds total token budget")
    if data.get("behavioral_gate") not in (None, "cli-state-v1"):
        raise ValueError("Unknown external behavioral gate")
    policy = data.get("context_policy")
    if policy is not None:
        if not isinstance(policy, dict) or set(policy) != {
            "mode",
            "keep_recent",
            "trigger_tokens",
            "safety_tokens",
        }:
            raise ValueError("Invalid context policy fields")
        if policy["mode"] not in ("none", "mask", "recoverable"):
            raise ValueError("Invalid context policy mode")
        for field, low, high in (
            ("keep_recent", 1, 64),
            ("trigger_tokens", 1, data["context_capacity_tokens"]),
            ("safety_tokens", 32, 4096),
        ):
            if type(policy[field]) is not int or not low <= policy[field] <= high:
                raise ValueError(f"Invalid context policy {field}")
        if data["tool_call_limit"] > 128:
            raise ValueError("Context archive supports at most 128 observations")
    if data.get("structured_finalization", False) and policy is None:
        raise ValueError(
            "structured_finalization requires measured context_policy and observation history"
        )
    from fresh_context import validate_policy

    validate_policy(data)
    from progress_reminder import validate_policy as validate_progress_policy

    validate_progress_policy(data)
    from handoff_phase import validate_policy as validate_handoff_policy

    validate_handoff_policy(data)
    return data


def requires_outer_adjudication(metadata):
    """Data-only admission guard; triage fixtures can never inherit ordinary scoring."""
    if not isinstance(metadata, dict):
        raise ValueError("Expected task metadata object")
    required = metadata.get("requires_outer_adjudication", False)
    if type(required) is not bool:
        raise ValueError("requires_outer_adjudication must be a boolean")
    if metadata.get("kind") == "contract-triage" and required is not True:
        raise ValueError("contract-triage requires explicit outer adjudication")
    return required


def require_task_protocol(metadata, limits):
    if (
        requires_outer_adjudication(metadata)
        and limits.get("spec_blocker_exit") is not True
    ):
        raise ValueError(
            "This task requires an opt-in spec_blocker_exit protocol and outer rubric"
        )


def admit_tasks(names, split, root=PROJECT):
    if split not in ("development", "reserved"):
        raise ValueError("Unknown task split")
    for name in names:
        if name not in tasks():
            raise ValueError(f"Unknown task: {name}")
        meta = json.loads((root / "tasks" / name / "task.json").read_text())
        if meta["split"] != split:
            raise ValueError(f"{name} is {meta['split']}, not requested {split}")


def server_resources(profile):
    """Trusted server allowances; never propagated into candidate sandboxes."""
    result = {
        "memory_max_gib": 48,
        "minimum_available_gib": 48,
        "startup_timeout_seconds": 300,
        "setup_allowance_seconds": 600,
    }
    configured = profile.get("server_resources", {})
    if set(configured) - result.keys():
        raise ValueError("Unknown server resource setting")
    result.update(configured)
    for name, ceiling in (
        ("memory_max_gib", 140),
        ("minimum_available_gib", 192),
        ("startup_timeout_seconds", 1200),
        ("setup_allowance_seconds", 1800),
    ):
        if type(result[name]) is not int or not 0 < result[name] <= ceiling:
            raise ValueError(f"Invalid server resource allowance: {name}")
    if result["minimum_available_gib"] < result["memory_max_gib"]:
        raise ValueError("Server admission must cover its memory cap")
    if result["setup_allowance_seconds"] < result["startup_timeout_seconds"] + 300:
        raise ValueError("Setup allowance must cover startup and weight verification")
    return result


def campaign_timeout(limits, count, setup_seconds=600):
    # Hashing/loading/readiness plus each trial's cleanup allowance.
    return setup_seconds + count * (limits["task_wall_seconds"] + 30)
