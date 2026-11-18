"""Optional wall-time heuristic for native thinking, independent of hard limits."""

import math

from control import DeadlineExceeded


def validate(policy):
    fields = {
        "decode_tokens_per_second",
        "reasoning_fraction",
        "response_reserve_seconds",
    }
    if not isinstance(policy, dict) or set(policy) != fields:
        raise ValueError("Invalid reasoning_deadline fields")
    for name, value in policy.items():
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"Invalid reasoning_deadline {name}")
    if not (
        0 < policy["decode_tokens_per_second"] <= 10000
        and 0 < policy["reasoning_fraction"] <= 1
        and policy["response_reserve_seconds"] >= 0
    ):
        raise ValueError("Invalid reasoning_deadline range")


def allocate(policy, configured_cap, deadline, now):
    validate(policy)
    if deadline is None or not math.isfinite(deadline) or not math.isfinite(now):
        raise ValueError("Reasoning deadline is not initialized")
    if type(configured_cap) is not int or configured_cap < 1:
        raise ValueError("Expected positive native reasoning cap")
    remaining = deadline - now
    if remaining <= 0:
        raise DeadlineExceeded("Agent deadline reached before model request")
    available = max(0, remaining - policy["response_reserve_seconds"])
    cap = min(
        configured_cap,
        max(
            1,
            math.floor(
                available
                * policy["decode_tokens_per_second"]
                * policy["reasoning_fraction"]
            ),
        ),
    )
    return {
        "policy": dict(policy),
        "agent_deadline_monotonic": deadline,
        "allocated_at_monotonic": now,
        "remaining_agent_seconds": remaining,
        "configured_reasoning_cap": configured_cap,
        "effective_reasoning_cap": cap,
        "note": "Heuristic before context preparation; prefill, reply and tools consume time too. Hard deadlines remain authoritative.",
    }
