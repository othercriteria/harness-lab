"""One optional pacing notice; no workspace inspection, execution or new budget."""

import json
import math
import time

from control import DeadlineExceeded
from fresh_context import completed_history

INSTRUCTION = (
    " The harness may issue one elapsed-time progress reminder. It reports timing,"
    " not implementation correctness, and does not renew any allowance."
)
GUIDANCE = (
    " If you are still investigating, choose a small coherent implementation step"
    " from the public contract and carry it through to a focused check now. Avoid"
    " repeating general environment or API probes unless a concrete discrepancy"
    " requires one. If implementation is underway, finish the remaining required"
    " behavior and saved tests before expanding optional coverage. Keep time for"
    " checking the result and an explicit final handoff. If you have established"
    " a specification blocker, report its concrete argument through the supported"
    " blocker exit rather than making cosmetic edits. This reminder does not"
    " certify progress, waive requirements or extend any budget."
)


def validate_policy(limits):
    policy = limits.get("progress_reminder")
    if policy is None:
        return
    if not isinstance(policy, dict) or set(policy) != {
        "after_elapsed_agent_fraction",
        "min_remaining_agent_seconds",
    }:
        raise ValueError("Unsupported progress-reminder policy")
    fraction, minimum = (
        policy["after_elapsed_agent_fraction"],
        policy["min_remaining_agent_seconds"],
    )
    if any(
        type(v) not in (int, float) or not math.isfinite(v) for v in (fraction, minimum)
    ):
        raise ValueError("Progress-reminder timing must be finite numbers")
    if not 0 < fraction < 1 or minimum <= 0:
        raise ValueError("Invalid progress-reminder timing")
    if limits.get("time_budget_feedback") is not True:
        raise ValueError("Progress reminder requires the original agent deadline")
    if limits.get("structured_finalization") is not True:
        raise ValueError(
            "Progress reminder requires structured completion/blocker exits"
        )
    context = limits.get("context_policy")
    if not isinstance(context, dict) or context.get("mode") != "none":
        raise ValueError("Progress reminder requires measured unmasked context")


class ProgressReminder:
    def __init__(self, output, limits, environment):
        validate_policy(limits)
        self.policy = dict(limits["progress_reminder"])
        self.output, self.environment = output, environment
        self.deadline = self.budget = self.started = None
        self.cycles = self.checked_cycles = 0
        self.decision = None

    def start(self, deadline, budget):
        if self.started is not None:
            raise ValueError("Progress-reminder clock already started")
        if (
            any(
                type(v) not in (int, float) or not math.isfinite(v)
                for v in (deadline, budget)
            )
            or budget <= 0
            or self.environment.agent_deadline != deadline
        ):
            raise ValueError("Invalid original progress-reminder clock")
        self.deadline, self.budget, self.started = deadline, budget, deadline - budget
        with (self.output / "progress-clock.json").open("x") as stream:
            json.dump(
                {
                    "original_agent_deadline_monotonic": self.deadline,
                    "original_agent_budget_seconds": self.budget,
                    "original_agent_started_monotonic": self.started,
                    "policy": self.policy,
                },
                stream,
                indent=2,
            )
            stream.write("\n")

    def completed_cycle(self, message, observations):
        if observations:
            self.cycles += 1

    def before_query(
        self, messages, model, *, reset_applied=False, checkpoint_pending=False
    ):
        env = self.environment
        if (
            (messages and messages[-1].get("role") == "exit")
            or getattr(env, "final_handoff", None) is not None
            or getattr(env, "spec_blocker_claim", None) is not None
        ):
            raise ValueError("Cannot remind/query a terminal attempt")
        if self.decision is not None or checkpoint_pending:
            return False
        if self.cycles == self.checked_cycles:
            return False
        if self.started is None or env.agent_deadline != self.deadline:
            raise ValueError("Missing or changed original progress-reminder clock")
        now = time.monotonic()
        elapsed, remaining = now - self.started, self.deadline - now
        self.checked_cycles = self.cycles
        if remaining <= 0:
            raise DeadlineExceeded("No time remains for progress reminder")
        nominal = self.budget * self.policy["after_elapsed_agent_fraction"]
        if elapsed < nominal:
            return False
        completed_history(messages)
        reason = (
            "fresh-context reset takes precedence"
            if reset_applied
            else "minimum remaining time"
            if remaining < self.policy["min_remaining_agent_seconds"]
            else None
        )
        timing = {
            "original_agent_budget_seconds": self.budget,
            "original_agent_started_monotonic": self.started,
            "original_agent_deadline_monotonic": self.deadline,
            **self.policy,
            "nominal_elapsed_seconds": nominal,
            "actual_elapsed_seconds": elapsed,
            "overshoot_seconds": max(0, elapsed - nominal),
            "remaining_agent_seconds": remaining,
        }
        notice = None
        if reason is None:
            notice = {
                "role": "user",
                "content": (
                    "Harness progress reminder (one-time): "
                    f"{elapsed:.1f}s of the original {self.budget:.1f}s agent allowance"
                    f" have elapsed; {remaining:.1f}s remain before this notice and"
                    " later work are processed." + GUIDANCE
                ),
                "extra": {"progress_reminder": timing, "timestamp": time.time()},
            }
        record = {
            "status": "bypassed" if reason else "sent",
            "reason": reason,
            "timing": timing,
            "completed_tool_cycles": self.cycles,
            "boundary_messages": len(messages),
            "model_calls": model.calls,
            "completion_tokens": model.completion_tokens,
            "tool_calls": env.calls,
            "notice": notice,
            "budget_renewed": False,
        }
        # Persist before appending; a failed evidence write must not produce an
        # unrecorded model-visible notice. No existing transcript item is changed.
        with (self.output / "progress-reminder-001.json").open("x") as stream:
            json.dump(record, stream, indent=2)
            stream.write("\n")
        self.decision = record["status"]
        if notice:
            messages.append(notice)
        return notice is not None
