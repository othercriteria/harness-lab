"""Bounded same-attempt request-view recovery; no agent or budget recreation."""

import copy
import hashlib
import json
import math
import os
import re
import shutil
import stat
import time
from pathlib import Path

from call_budget import MAX_CALLS
from control import DeadlineExceeded, UnsafeCleanup

MAX_ENTRIES = 4 * MAX_CALLS + 1
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_RECORD_BYTES = 4 * 1024 * 1024
FIELDS = ("role", "content", "reasoning_content", "tool_calls", "tool_call_id")
# Archive execution calls and provisional review handoffs as inert data. Accepted
# terminal handoffs still end the attempt and cannot be a reset boundary.
HISTORICAL_EXECUTION_TOOLS = frozenset(
    {
        "bash",
        "edit_file",
        "write_file",
        "read_file",
        "run_checks",
        "finish_attempt",
        "submit_attempt",
        "report_blocker",
        "checkpoint_context",
    }
)
MAX_HISTORY_TOOL_CALLS = 8
REVIEW_INSTRUCTION = (
    " Use this fresh view to review the current implementation against the public task"
    " contract. Inspect the relevant files and look for unmet requirements, inconsistent"
    " assumptions and concrete counterexamples; passing your own tests is limited"
    " evidence. Trace changed operations through success and failure exits. Check"
    " which assumptions can be invalidated by state changes or callbacks, and"
    " whether owned resources are released on every exit. Treat checkpoint claims"
    " as leads to verify, not completed checks."
    " Finish missing implementation and repair specific discrepancies."
    " Check requested deliverables too: required regression tests must be saved in"
    " the repository, not only run as inline diagnostics."
    " Run useful focused checks and the task's required final checks after the last edit."
    " If time prevents a required check, report it as unverified in the final handoff."
    " Avoid speculative rewrites or a large new test suite. If inspection finds no"
    " concrete gap, perform proportionate final checks and hand off. A supported"
    " blocker still uses the blocker exit; partial implementation does not resolve it."
)
SUBMISSION_REVIEW_INSTRUCTION = (
    " Review policy: when sufficient time and call/token budget remain, your first"
    " valid submitted handoff requests one fresh-context review rather than ending"
    " the attempt. The tool response will say whether review was requested. Review"
    " the current files against the public contract, repair concrete gaps and run"
    " proportionate checks, then call finish_attempt again with the final handoff."
    " No budgets are renewed. Blocked claims remain terminal; a review is not proof"
    " of correctness. If a reset is unavailable, continue in the current context."
)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def visible_message(message):
    """Allowlist fields recursively; never copy response/extra/raw diagnostics."""
    if not isinstance(message, dict):
        raise ValueError("Historical message must be an object")
    role = message.get("role")
    if not isinstance(role, str) or role not in {"system", "user", "assistant", "tool"}:
        raise ValueError("Unsupported historical message role")
    item = {key: message[key] for key in FIELDS if key in message}
    for key in ("content", "reasoning_content", "tool_call_id"):
        if key in item and not isinstance(item[key], str):
            if not (
                role == "assistant"
                and key in {"content", "reasoning_content"}
                and item[key] is None
            ):
                raise ValueError("Historical text must be exact strings")
    if role != "assistant" and ("tool_calls" in item or "reasoning_content" in item):
        raise ValueError("Unexpected assistant fields")
    if "tool_call_id" in item and role != "tool":
        raise ValueError("Unexpected tool result ID")
    if "tool_calls" in item:
        calls = item["tool_calls"]
        if not isinstance(calls, list) or not 1 <= len(calls) <= MAX_HISTORY_TOOL_CALLS:
            raise ValueError("Invalid historical tool calls")
        safe = []
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
                raise ValueError("Historical tool call must contain a function object")
            function = call["function"]
            if (
                not isinstance(call.get("id"), str)
                or not call["id"]
                or call.get("type") != "function"
                or not isinstance(function.get("name"), str)
                or function.get("name") not in HISTORICAL_EXECUTION_TOOLS
                or not isinstance(function.get("arguments"), str)
            ):
                raise ValueError("Unsupported historical tool schema")
            safe.append(
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": function["name"],
                        "arguments": function["arguments"],
                    },
                }
            )
        item["tool_calls"] = safe
    return copy.deepcopy(item)


def completed_history(messages):
    """Accept complete cycles only, including every result in multi-call turns."""
    pending = set()
    for message in messages:
        if message["role"] == "tool":
            identifier = message.get("tool_call_id")
            if identifier not in pending:
                raise ValueError("Unpaired historical tool result")
            pending.remove(identifier)
        else:
            if pending:
                raise ValueError("Unfinished historical tool cycle")
            calls = message.get("tool_calls", [])
            pending = {call["id"] for call in calls}
            if len(pending) != len(calls):
                raise ValueError("Duplicate tool IDs in one response")
    if pending:
        raise ValueError("Unfinished historical tool cycle")


def validate_policy(limits):
    policy = limits.get("fresh_context")
    if policy is None:
        return
    if not isinstance(policy, dict):
        raise ValueError("Unsupported fresh-context policy")
    trigger = policy.get("trigger", "elapsed")
    if trigger not in ("elapsed", "first_submission", "context_headroom"):
        raise ValueError("Unsupported fresh-context trigger")
    required = {"min_remaining_agent_seconds"}
    if trigger == "elapsed":
        required.add("after_elapsed_agent_fraction")
    if trigger == "context_headroom":
        required.update({"headroom_tokens", "max_resets"})
    if (
        not isinstance(policy, dict)
        or not required <= policy.keys()
        or policy.keys()
        - required
        - {"continuation_mode", "trigger", "summary_checkpoint", "announce_review"}
    ):
        raise ValueError("Unsupported fresh-context policy")
    if policy.get("continuation_mode", "continue") not in ("continue", "review"):
        raise ValueError("Unsupported fresh-context continuation mode")
    if "announce_review" in policy and (
        trigger != "first_submission" or type(policy["announce_review"]) is not bool
    ):
        raise ValueError("announce_review requires a boolean and first_submission")
    summarize = policy.get("summary_checkpoint", False)
    if type(summarize) is not bool or (
        summarize
        and (
            trigger not in ("elapsed", "context_headroom")
            or limits.get("structured_finalization") is not True
        )
    ):
        raise ValueError(
            "Summary checkpoint requires elapsed/headroom reset and structured tools"
        )
    if trigger == "first_submission" and (
        limits.get("structured_finalization") is not True
        or policy.get("continuation_mode") != "review"
    ):
        raise ValueError(
            "Submission review requires structured finalization and review mode"
        )
    if trigger == "context_headroom":
        if (
            not summarize
            or type(policy["max_resets"]) is not int
            or not 1 <= policy["max_resets"] <= 8
            or type(policy["headroom_tokens"]) is not int
            or policy["headroom_tokens"] < 4096
        ):
            raise ValueError(
                "Headroom recovery requires summaries, 1..8 resets and >=4096 headroom tokens"
            )
        capacity = limits.get("context_capacity_tokens")
        if capacity is not None and policy["headroom_tokens"] >= capacity:
            raise ValueError("Recovery headroom must be below context capacity")
    fraction = policy.get("after_elapsed_agent_fraction")
    minimum = policy["min_remaining_agent_seconds"]
    if trigger == "elapsed" and (
        type(fraction) not in (int, float)
        or not math.isfinite(fraction)
        or not 0 < fraction < 1
    ):
        raise ValueError(
            "Elapsed-agent fraction must be finite and strictly between 0 and 1"
        )
    if type(minimum) not in (int, float) or not math.isfinite(minimum) or minimum <= 0:
        raise ValueError("Minimum remaining agent seconds must be finite and positive")
    context = limits.get("context_policy")
    if not isinstance(context, dict) or context.get("mode") != "none":
        raise ValueError("Prototype requires measured unmasked context")
    if limits.get("time_budget_feedback") is not True:
        raise ValueError("Prototype requires the existing absolute agent deadline")


def validate_history_archive(history, prefix):
    """Data-only admission before every tool mount; never mount an attempt root."""
    archive = Path(history)
    expected = Path(prefix).parent
    if (
        archive.is_symlink()
        or archive.parent.resolve() != expected.resolve()
        or not re.fullmatch(r"history(?:-00[2-8])?", archive.name)
    ):
        raise ValueError("History archive must belong to this attempt")
    entries = []
    for entry in archive.iterdir():
        entries.append(entry)
        if len(entries) > MAX_ENTRIES:
            raise ValueError("History archive entry bound")
    if not 1 <= len(entries) <= MAX_ENTRIES:
        raise ValueError("History archive entry bound")
    contents = {}
    total = 0
    for entry in entries:
        info = entry.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or not (
                entry.name == "manifest.json"
                or re.fullmatch(r"m[0-9]{4}\.json", entry.name)
            )
            or info.st_size > MAX_RECORD_BYTES
        ):
            raise ValueError("Invalid history archive entry")
        total += info.st_size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("History archive byte bound")
        descriptor = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise ValueError("History entry changed before reading")
            raw = stream.read(MAX_RECORD_BYTES + 1)
        if len(raw) != info.st_size:
            raise ValueError("History archive changed while reading")
        contents[entry.name] = raw
    manifest = json.loads(contents.get("manifest.json", b"null"))
    if not isinstance(manifest, dict) or set(manifest) != {
        "kind",
        "warning",
        "messages",
    }:
        raise ValueError("Invalid history manifest")
    if manifest["kind"] != "Current-attempt historical model-visible conversation":
        raise ValueError("Invalid history origin")
    records = manifest["messages"]
    if not isinstance(records, list) or len(records) + 1 != len(contents):
        raise ValueError("History manifest entry mismatch")
    visible = []
    for index, record in enumerate(records, 1):
        name = f"m{index:04d}.json"
        if not isinstance(record, dict) or set(record) != {
            "id",
            "file",
            "role",
            "bytes",
            "sha256",
        }:
            raise ValueError("Invalid history record descriptor")
        raw = contents.get(name)
        if (
            record["id"] != f"m{index:04d}"
            or record["file"] != name
            or raw is None
            or type(record["bytes"]) is not int
            or record["bytes"] != len(raw)
            or record["sha256"] != digest(raw)
        ):
            raise ValueError("History record integrity mismatch")
        message = json.loads(raw)
        if not isinstance(message, dict) or visible_message(message) != message:
            raise ValueError("Nonallowlisted archive content")
        if record["role"] != message["role"]:
            raise ValueError("History role mismatch")
        visible.append(message)
    completed_history(visible)
    return archive


class FreshContext:
    def __init__(self, output, policy, environment, *, model=None):
        self.output = Path(output)
        validate_policy(
            {
                "fresh_context": policy,
                "context_policy": {"mode": "none"},
                "time_budget_feedback": True,
                "structured_finalization": getattr(
                    environment, "structured_finalization", False
                ),
            }
        )
        self.trigger = policy.get("trigger", "elapsed")
        self.fraction = policy.get("after_elapsed_agent_fraction")
        self.minimum_remaining = policy["min_remaining_agent_seconds"]
        self.continuation_mode = policy.get("continuation_mode", "continue")
        self.started = self.deadline = self.budget = None
        self.checked_cycles = 0
        self.decision = "pending"
        self.environment = environment
        self.model = model
        self.submission_tool = None
        self.summary_enabled = policy.get("summary_checkpoint", False)
        self.checkpoint_requested = False
        self.checkpoint_attempted = False
        self.checkpoint_attempts = 0
        self.checkpoint_repair_considered = False
        self.checkpoint_valid_response = False
        self.checkpoint_tool = None
        self.checkpoint = None
        self.cycles = 0
        self.attempted = False
        self.boundary = None
        self.prefix = None
        self.measurement_pending = False
        self.headroom_tokens = policy.get("headroom_tokens")
        self.max_resets = policy.get("max_resets", 1)
        self.sequence = 1
        self.reset_count = 0
        self.last_reset_cycle = None
        self.checkpoint_tools = set()
        self.pressure = None
        self.pre_reset_messages = None

    def artifact(self, stem):
        return self.output / f"{stem}-{self.sequence:03d}.json"

    def consider_pressure(self, messages, model, report):
        """Called on the actual rendered view, before sending a model request."""
        if self.trigger != "context_headroom" or self.checkpoint_requested:
            return False
        return self.before_query(messages, model, context_report=report)

    @property
    def checkpoint_pending(self):
        return self.checkpoint_requested and not self.checkpoint_attempted

    def checkpoint_response(self, *, accepted, error=None):
        """Called after ordinary request/usage accounting, before any tool dispatch."""
        if not self.checkpoint_pending:
            raise ValueError("No pending checkpoint response")
        self.checkpoint_attempted = True
        self.checkpoint_attempts += 1
        self.checkpoint_valid_response = accepted
        record = {
            "status": "valid_response" if accepted else "rejected_response",
            "model_calls": self.model.calls,
            "completion_tokens": self.model.completion_tokens,
            "timing": self.timing(time.monotonic()),
            "error": error,
            "executed": False,
        }
        stem = (
            "context-checkpoint-response"
            if self.checkpoint_attempts == 1
            else "context-checkpoint-repair-response"
        )
        with self.artifact(stem).open("x") as stream:
            json.dump(record, stream, indent=2)

    def offer_checkpoint_repair(self, messages, model):
        """Reuse ordinary validation repair, once, without renewing any allowance."""
        from context_checkpoint import REPLY_TOKENS, repair_request

        self.checkpoint_repair_considered = True
        timing = self.timing(time.monotonic())
        env = self.environment
        reason = None
        if timing["remaining_agent_seconds"] < self.minimum_remaining:
            reason = "minimum remaining time"
        elif (
            model.calls + 1 >= model.limits["step_limit"]
            or env.calls + 1 >= env.tool_call_limit
        ):
            reason = "insufficient remaining calls for repair and continuation"
        elif (
            model.limits["total_completion_token_limit"] - model.completion_tokens
            <= REPLY_TOKENS
        ):
            reason = "insufficient remaining completion tokens"
        notice = {
            "role": "user",
            "content": repair_request(
                model.limits.get("shared_evidence", False),
                progress=model.limits.get("checkpoint_progress", False),
            ),
        }
        measured = None
        if reason is None:
            payload = json.loads(
                (self.output / f"request-{model.calls:03d}.request.json").read_text()
            )
            payload["messages"] = model.history.wire(self.project([*messages, notice]))
            tokens = model.count_tokens(payload, "checkpoint-repair")
            available = (
                model.limits["context_capacity_tokens"]
                - tokens
                - model.limits["context_policy"]["safety_tokens"]
            )
            measured = {
                "input_tokens": tokens,
                "available_completion_tokens": available,
                "required_completion_headroom": 2560,
            }
            if available < 2560:
                reason = "insufficient measured context headroom"
            timing = self.timing(time.monotonic())
            if timing["remaining_agent_seconds"] < self.minimum_remaining:
                reason = "minimum remaining time after measurement"
        decision = {
            "status": "offered" if reason is None else "skipped",
            "reason": reason,
            "model_calls": model.calls,
            "completion_tokens": model.completion_tokens,
            "tool_calls": env.calls,
            "timing": timing,
            "context": measured,
        }
        with self.artifact("context-checkpoint-repair-decision").open("x") as stream:
            json.dump(decision, stream, indent=2)
        if reason is not None:
            return False
        original = json.loads(self.artifact("context-checkpoint-request").read_text())
        offer = {
            **decision,
            "status": "requested",
            "notice": notice,
            "boundary_messages": len(messages),
        }
        if "observation_manifest" in original:
            offer["observation_manifest"] = original["observation_manifest"]
        with self.artifact("context-checkpoint-repair-request").open("x") as stream:
            json.dump(offer, stream, indent=2)
        messages.append(notice)
        self.checkpoint_attempted = False
        return True

    def accept_checkpoint(self, value):
        from context_checkpoint import citations, validate

        if not (
            self.summary_enabled
            and self.checkpoint_attempted
            and self.checkpoint_valid_response
            and self.checkpoint_requested
            and self.checkpoint is None
            and not self.attempted
        ):
            raise ValueError("Checkpoint is not awaiting acceptance")
        shared = self.model.limits.get("shared_evidence", False)
        self.checkpoint = copy.deepcopy(
            validate(
                value,
                shared=shared,
                history=self.model.history,
                progress=self.model.limits.get("checkpoint_progress", False),
            )
        )
        self.checkpoint_tool = self.environment.calls
        self.checkpoint_tools.add(self.checkpoint_tool)
        record = {
            "status": "unverified_model_memory",
            "summary": self.checkpoint["summary"],
            "tool_call": self.checkpoint_tool,
            "model_call": self.model.calls,
            "timing": self.timing(time.monotonic()),
            "executed": False,
        }
        if shared:
            from evidence import resolve

            record["evidence"] = citations(self.checkpoint)
            record["observations"] = resolve(record["evidence"], self.model.history)
        if "progress" in self.checkpoint:
            record["progress"] = self.checkpoint["progress"]
            record["progress_measurement"] = {
                "status": "unverified_model_report",
                "elicitation": "context_checkpoint",
                "report_utf8_bytes": len(
                    json.dumps(record["progress"], ensure_ascii=False).encode()
                ),
                "overhead_note": "Included in the checkpoint request's recorded time/tokens; marginal report cost is not separately observed.",
            }
        with self.artifact("context-checkpoint").open("x") as stream:
            json.dump(record, stream, indent=2)

    def start(self, deadline, budget):
        """Capture once from the actual original allocation, never renew it."""
        if self.started is not None:
            raise ValueError("Fresh-context clock already started")
        if (
            any(
                type(v) not in (int, float) or not math.isfinite(v)
                for v in (deadline, budget)
            )
            or budget <= 0
        ):
            raise ValueError("Invalid original agent clock")
        if self.environment.agent_deadline != deadline:
            raise ValueError("Agent deadline does not match original clock")
        self.deadline, self.budget = deadline, budget
        self.started = deadline - budget

    def timing(self, now):
        if self.started is None or self.environment.agent_deadline != self.deadline:
            raise ValueError("Missing or changed original agent clock")
        nominal = self.budget * self.fraction if self.fraction is not None else None
        elapsed = now - self.started
        return {
            "original_agent_budget_seconds": self.budget,
            "original_agent_started_monotonic": self.started,
            "original_agent_deadline_monotonic": self.deadline,
            "after_elapsed_agent_fraction": self.fraction,
            "minimum_remaining_agent_seconds": self.minimum_remaining,
            "nominal_elapsed_seconds": nominal,
            "actual_elapsed_seconds": elapsed,
            "overshoot_seconds": max(0, elapsed - nominal)
            if nominal is not None
            else None,
            "remaining_agent_seconds": self.deadline - now,
        }

    def bypass(self, timing, phase, reason="minimum remaining time"):
        self.decision = "bypassed"
        with self.artifact("fresh-context-bypassed").open("x") as stream:
            json.dump(
                {
                    "status": "bypassed",
                    "reason": reason,
                    "phase": phase,
                    "timing": timing,
                    "cycles": self.cycles,
                    "projection_applied": False,
                    "projection_tokens_reclaimed": 0,
                },
                stream,
                indent=2,
            )
        return False

    def offer_submission(self):
        """Reserve one nonterminal review; no execution, counters or clock renewal."""
        if self.trigger != "first_submission" or self.attempted:
            return False
        if self.submission_tool is not None:
            raise ValueError("Submission review query boundary is still pending")
        if self.model is None:
            raise ValueError("Submission review has no owning model")
        timing = self.timing(time.monotonic())
        model, env = self.model, self.environment
        reason = None
        if timing["remaining_agent_seconds"] < self.minimum_remaining:
            reason = "minimum remaining time"
        elif (
            model.calls >= model.limits["step_limit"]
            or model.completion_tokens >= model.limits["total_completion_token_limit"]
            or env.calls >= env.tool_call_limit
        ):
            reason = "no remaining model/tool/token allowance"
        if reason:
            self.attempted = True
            return self.bypass(timing, "submission_offer", reason)
        self.submission_tool = env.calls
        write = self.output / "fresh-context-submission-offer-001.json"
        with write.open("x") as stream:
            json.dump(
                {
                    "status": "requested",
                    "timing": timing,
                    "tool_calls": env.calls,
                    "model_calls": model.calls,
                    "completion_tokens": model.completion_tokens,
                },
                stream,
                indent=2,
            )
        return True

    def completed_cycle(self, message, observations):
        # Called after tools finished and their bounded observations were formatted.
        # Archive eligibility must never prevent DefaultAgent appending those
        # observations to its full transcript. Validate only at the reset boundary,
        # where optional archive rejection can leave ordinary continuation intact.
        if observations:
            self.cycles += 1

    def project(self, messages):
        if self.prefix is None:
            if len(messages) < 2 or [m.get("role") for m in messages[:2]] != [
                "system",
                "user",
            ]:
                raise ValueError("Expected original system/task prefix")
            self.prefix = copy.deepcopy(messages[:2])
        if messages[:2] != self.prefix:
            raise ValueError("Original system/task prefix changed")
        if self.boundary is None:
            return messages
        return [*self.prefix, *messages[self.boundary :]]

    def before_query(self, messages, model, *, context_report=None):
        # A terminal adapter spawns no process and has no cleanup receipt. It must
        # never become a reset cycle or permit another reset/query after acceptance.
        if (
            (messages and messages[-1].get("role") == "exit")
            or getattr(self.environment, "final_handoff", None) is not None
            or getattr(self.environment, "spec_blocker_claim", None) is not None
        ):
            raise ValueError("Cannot reset/query a terminal attempt")
        self.project(messages)
        if (
            self.trigger == "context_headroom"
            and self.attempted
            and self.decision == "applied"
            and self.sequence < self.max_resets
            and self.cycles > self.last_reset_cycle
        ):
            self.sequence += 1
            self.attempted = False
            self.decision = "pending"
            self.checkpoint_requested = self.checkpoint_attempted = False
            self.checkpoint_attempts = 0
            self.checkpoint_repair_considered = False
            self.checkpoint_valid_response = False
            self.checkpoint_tool = self.checkpoint = None
            self.pressure = None
        if (
            self.trigger == "context_headroom"
            and not self.checkpoint_requested
            and (
                context_report is None
                or context_report["available_completion_tokens"] > self.headroom_tokens
            )
        ):
            return False
        if self.attempted or (
            self.cycles == self.checked_cycles and not self.checkpoint_attempted
        ):
            return False
        started = time.monotonic()
        timing = self.timing(started)
        # Only the next query following a newly completed whole action cycle can
        # cross the trigger. A malformed-response retry is not another boundary.
        self.checked_cycles = self.cycles
        if timing["remaining_agent_seconds"] <= 0:
            raise DeadlineExceeded("No time remains for context reset")
        if self.trigger == "first_submission" and self.submission_tool is None:
            return False
        if (
            self.trigger == "elapsed"
            and timing["actual_elapsed_seconds"] < timing["nominal_elapsed_seconds"]
        ):
            return False
        if self.trigger == "context_headroom" and self.pressure is None:
            self.pressure = {
                "input_tokens": context_report["input_tokens_after"],
                "available_completion_tokens": context_report[
                    "available_completion_tokens"
                ],
                "threshold_tokens": self.headroom_tokens,
                "model_calls": model.calls,
            }
        env = self.environment
        # Snapshot return alone is insufficient: cleanup must be authoritative.
        for number in range(1, env.calls + 1):
            if number in getattr(env, "read_tools", set()):
                from read_file import verify_receipt

                try:
                    verify_receipt(self.output / f"tool-{number:03d}")
                except (OSError, ValueError, KeyError) as error:
                    raise UnsafeCleanup("Invalid read-only tool boundary") from error
                continue
            if number == self.submission_tool or number in self.checkpoint_tools:
                # The outer adapter's provisional handoff starts no process.
                checkpoint = number in self.checkpoint_tools
                try:
                    records = []
                    for suffix in ("result", "request"):
                        path = self.output / f"tool-{number:03d}.{suffix}.json"
                        if path.is_symlink() or path.stat().st_size > 65536:
                            raise ValueError("Invalid review control artifact")
                        records.append(json.loads(path.read_text()))
                    result, request = records
                    if not (
                        isinstance(result, dict)
                        and isinstance(request, dict)
                        and result.get(
                            "checkpoint_control" if checkpoint else "review_control"
                        )
                        == (
                            "summary_saved" if checkpoint else "fresh_context_requested"
                        )
                        and result.get("ok") is True
                        and result.get("executed") is False
                        and result.get("cleanup_required") is False
                        and "terminal_control" not in result
                        and request.get("mode") == "adapter-control"
                        and request.get("name")
                        == ("checkpoint_context" if checkpoint else "finish_attempt")
                        and request.get("executed") is False
                    ):
                        raise ValueError("Invalid review control receipt")
                except (OSError, ValueError) as error:
                    raise UnsafeCleanup(
                        "Invalid non-executing context control receipt"
                    ) from error
                continue
            path = self.output / f"tool-{number:03d}.cleanup.json"
            try:
                if path.is_symlink() or path.stat().st_size > 65536:
                    raise ValueError("Invalid cleanup receipt")
                receipt = json.loads(path.read_text())
                if not isinstance(receipt, dict) or receipt.get("verified") is not True:
                    raise ValueError("Unverified cleanup")
            except (OSError, ValueError) as error:
                raise UnsafeCleanup(
                    f"Fresh-context boundary cleanup unverified: {path}"
                ) from error
        if (
            self.checkpoint_attempts == 1
            and not self.checkpoint_valid_response
            and not self.checkpoint_repair_considered
            and self.offer_checkpoint_repair(messages, model)
        ):
            return False
        timing = self.timing(time.monotonic())
        if timing["remaining_agent_seconds"] < self.minimum_remaining:
            self.attempted = True
            return self.bypass(timing, "query_boundary")
        # A large observation can jump across the summary reserve. Recover via
        # the archive without sending an impossible/truncated checkpoint request.
        summary_fits = (
            self.pressure is None
            or self.pressure["available_completion_tokens"] >= 2560
        )
        if self.summary_enabled and not self.checkpoint_requested and summary_fits:
            from context_checkpoint import request

            if (
                model.calls + 1 >= model.limits["step_limit"]
                or env.calls + 1 >= env.tool_call_limit
                or model.completion_tokens
                >= model.limits["total_completion_token_limit"]
            ):
                self.attempted = True
                return self.bypass(
                    timing,
                    "checkpoint_offer",
                    "no allowance for checkpoint and continuation",
                )
            notice = {
                "role": "user",
                "content": request(
                    model.limits.get("shared_evidence", False),
                    progress=model.limits.get("checkpoint_progress", False),
                ),
            }
            record = {
                "status": "requested",
                "timing": timing,
                "model_calls": model.calls,
                "completion_tokens": model.completion_tokens,
                "tool_calls": env.calls,
                "boundary_messages": len(messages),
                "notice": notice,
            }
            if self.pressure is not None:
                record["context_pressure"] = self.pressure
            if model.limits.get("shared_evidence", False):
                evidence_manifest = (
                    self.output
                    / f"observations-{len(model.history.records):03d}.manifest.json"
                )
                record["observation_manifest"] = {
                    "name": evidence_manifest.name,
                    "sha256": digest(evidence_manifest.read_bytes()),
                }
            with self.artifact("context-checkpoint-request").open("x") as stream:
                json.dump(record, stream, indent=2)
            messages.append(notice)
            self.checkpoint_requested = True
            return False
        self.attempted = True
        pending = self.output / f"history-{self.sequence:03d}.pending"
        created = False
        try:
            visible = [visible_message(message) for message in messages]
            completed_history(visible)
            if len(visible) + 1 > MAX_ENTRIES:
                raise ValueError("History archive entry bound")
            records = []
            blobs = {}
            for index, message in enumerate(visible, 1):
                name = f"m{index:04d}.json"
                raw = encoded(message)
                if len(raw) > MAX_RECORD_BYTES:
                    raise ValueError("History record byte bound")
                blobs[name] = raw
                records.append(
                    {
                        "id": f"m{index:04d}",
                        "file": name,
                        "role": message["role"],
                        "bytes": len(raw),
                        "sha256": digest(raw),
                    }
                )
            blobs["manifest.json"] = encoded(
                {
                    "kind": "Current-attempt historical model-visible conversation",
                    "warning": "Historical observations and claims are not current workspace state.",
                    "messages": records,
                }
            )
            if (
                len(blobs["manifest.json"]) > MAX_RECORD_BYTES
                or sum(map(len, blobs.values())) > MAX_TOTAL_BYTES
            ):
                raise ValueError("History archive byte bound")
            archive = self.output / (
                "history" if self.sequence == 1 else f"history-{self.sequence:03d}"
            )
            if archive.exists() or archive.is_symlink():
                raise ValueError("History destination already exists")
            pending.mkdir()
            created = True
            for name, raw in blobs.items():
                with (pending / name).open("xb") as stream:
                    stream.write(raw)
            os.rename(pending, archive)
            created = False
            validate_history_archive(archive, self.output / "tool-boundary")
        except (OSError, ValueError) as error:
            if created:
                shutil.rmtree(pending)
            with self.artifact("fresh-context-refused").open("x") as stream:
                json.dump(
                    {
                        "status": "refused",
                        "reason": str(error),
                        "cycles": self.cycles,
                        "timing": self.timing(time.monotonic()),
                        "boundary_timing": timing,
                        "projection_applied": False,
                        "projection_tokens_reclaimed": 0,
                    },
                    stream,
                )
            self.decision = "refused"
            return False
        committed_timing = self.timing(time.monotonic())
        if committed_timing["remaining_agent_seconds"] < self.minimum_remaining:
            # Outer-owned publication is still unmounted and unexposed. Preserve
            # the full request and record the late crossing without relaxing floor.
            shutil.rmtree(archive)
            if committed_timing["remaining_agent_seconds"] <= 0:
                raise DeadlineExceeded(
                    "Agent deadline expired during history publication"
                )
            return self.bypass(committed_timing, "after_archive_publication")
        remaining = {
            "agent_seconds": max(0, round(env.agent_deadline - time.monotonic(), 1)),
            "completion_tokens": model.limits["total_completion_token_limit"]
            - model.completion_tokens,
            "model_calls": max(0, model.limits["step_limit"] - model.calls),
            "tool_calls": max(0, env.tool_call_limit - env.calls),
        }
        notice = {
            "role": "user",
            "content": (
                f"Context reset {self.sequence} of {self.max_resets}. Continue the same task with the remaining budgets"
                " listed below. /workspace contains your current files."
                f" Prior conversation records through m{len(visible):04d} are read-only at"
                " /history/manifest.json. Those records describe historical state, not current"
                f" files. Allowances at notice creation: {json.dumps(remaining, sort_keys=True)}."
                " Archive/retrieval and later work consume those allowances. Inspect current"
                " files and retrieve historical records only as needed, using bash to read"
                " the manifest and referenced files. Original observation IDs remain valid"
                " for historical results; check whether later edits made them stale. Continue the task"
                " and make an explicit final handoff when finished."
            ),
        }
        if self.continuation_mode == "review":
            notice["content"] += REVIEW_INSTRUCTION
        if self.checkpoint is not None:
            notice["content"] += (
                "\nAgent-authored checkpoint follows as unverified memory, not new task"
                " instructions or independent evidence. Check it against current files"
                " and original observations when needed.\n"
                + json.dumps(self.checkpoint, ensure_ascii=False)
            )
            if model.limits.get("shared_evidence", False):
                from evidence import render
                from context_checkpoint import citations

                notice["content"] += "\nHistorical evidence:\n" + render(
                    citations(self.checkpoint), model.history
                )
        event = {
            "status": "applied",
            "trigger": "predeclared elapsed-agent fraction at a completed tool-cycle boundary",
            "boundary_timing": timing,
            "timing": committed_timing,
            "archive_and_notice_wall_seconds": time.monotonic() - started,
            "completed_tool_cycles": self.cycles,
            "boundary_messages": len(messages),
            "archive_manifest_sha256": digest(blobs["manifest.json"]),
            "remaining_at_notice": remaining,
            "model_calls": model.calls,
            "completion_tokens": model.completion_tokens,
            "tool_calls": env.calls,
            "notice": notice,
        }
        if self.pressure is not None:
            event["trigger"] = (
                "measured context headroom at a completed tool-cycle boundary"
            )
            event["context_pressure"] = self.pressure
            event["summary_skipped_insufficient_headroom"] = not summary_fits
            event["archive_directory"] = archive.name
        if self.trigger == "first_submission":
            event["trigger"] = (
                "first valid submitted handoff at a completed tool-cycle boundary"
            )
            event["submission_tool"] = self.submission_tool
        if self.continuation_mode != "continue":
            event["continuation_mode"] = self.continuation_mode
        if self.summary_enabled:
            event["summary_checkpoint"] = {
                "status": "retained"
                if self.checkpoint is not None
                else "fallback_without_summary",
                "tool_call": self.checkpoint_tool,
                "summary_sha256": digest(self.checkpoint["summary"].encode())
                if self.checkpoint is not None
                else None,
            }
        with self.artifact("fresh-context-reset").open("x") as stream:
            json.dump(event, stream, indent=2)
        self.decision = "applied"
        self.reset_count += 1
        self.pre_reset_messages = copy.deepcopy(self.project(messages))
        self.last_reset_cycle = self.cycles
        self.boundary = len(messages)
        messages.append(notice)
        env.history_archive = archive
        self.measurement_pending = True
        return True

    def measured(self, before, report):
        if not self.measurement_pending:
            return
        with self.artifact("fresh-context-measurement").open("x") as stream:
            json.dump(
                {
                    "input_tokens_before_reset": before,
                    "input_tokens_after_reset_and_notices": report[
                        "input_tokens_after"
                    ],
                    "rendered_tokens_reclaimed": before - report["input_tokens_after"],
                    "wire_sha256": report["wire_sha256"],
                },
                stream,
                indent=2,
            )
        self.measurement_pending = False
