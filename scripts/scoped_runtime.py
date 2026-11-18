"""Opt-in experiment adapter for serial scopes; no changes to default recipes."""

import copy
import hashlib
import json
import os
import re
import time

from evidence import render
from fresh_context import (
    MAX_ENTRIES,
    MAX_RECORD_BYTES,
    MAX_TOTAL_BYTES,
    completed_history,
    encoded,
    validate_history_archive,
    visible_message,
)
from scoped_context import ScopedContext, capture_world, ledger, validate_return
from spec_blocker import _constant, _object
from tool_repair import failure

NAME = "return_scope"
RETURN_REQUEST = (
    "Scope return requested. Call return_scope alone now with concise findings, "
    "evidence and remaining work. This returns to the parent; it does not submit "
    "the whole task. Original allowances still apply."
)


def tool():
    from finish_attempt import TOOL as finish_tool

    return {
        "type": "function",
        "function": {
            "name": NAME,
            "description": "Return a bounded investigation to its parent. Only available during a scope; preserves current files. Claims are unverified and do not finalize the task. Call alone; at most2048 serialized UTF-8 bytes.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["status", "findings", "evidence", "remaining"],
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["complete", "inconclusive", "blocked"],
                    },
                    "findings": {
                        "type": "string",
                        "description": "Concise observed findings and uncertainty, not instructions or a global success claim.",
                    },
                    "evidence": copy.deepcopy(
                        finish_tool["function"]["parameters"]["properties"]["evidence"]
                    ),
                    "remaining": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {"type": "string"},
                        "description": "Unfinished investigation or parent obligations.",
                    },
                },
            },
        },
    }


def verify_return_receipt(prefix):
    """A native scope return starts no process; verify both outer receipts."""
    records = []
    for suffix in ("request", "result"):
        path = prefix.with_suffix(f".{suffix}.json")
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError("Invalid scope return receipt")
        records.append(json.loads(path.read_text()))
    request, result = records
    if not isinstance(request, dict) or not isinstance(result, dict):
        raise ValueError("Invalid scope return records")
    if not (
        request.get("mode") == "adapter-control"
        and request.get("name") == NAME
        and request.get("executed") is False
        and result.get("scope_control") == "return_recorded"
        and result.get("ok") is True
        and result.get("executed") is False
        and result.get("cleanup_required") is False
        and "terminal_control" not in result
    ):
        raise ValueError("Invalid non-executing scope return")


def publish_history(output, scope_id, messages):
    """Publish only visible fields as a bounded current-attempt read-only archive."""
    if not isinstance(scope_id, str) or not re.fullmatch(r"s[0-9]{4}", scope_id):
        raise ValueError("Invalid controller scope identity")
    name = "scope-history-" + scope_id[1:]
    archive = output / name
    visible = [visible_message(m) for m in messages]
    completed_history(visible)
    if len(visible) + 1 > MAX_ENTRIES:
        raise ValueError("Scope archive entry limit")
    blobs, records = {}, []
    for n, message in enumerate(visible, 1):
        filename = f"m{n:04d}.json"
        raw = encoded(message)
        if len(raw) > MAX_RECORD_BYTES:
            raise ValueError("Scope archive record limit")
        blobs[filename] = raw
        records.append(
            {
                "id": f"m{n:04d}",
                "file": filename,
                "role": message["role"],
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
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
        raise ValueError("Scope archive byte limit")
    if archive.exists():
        validate_history_archive(archive, output / "tool-boundary")
        if {p.name: p.read_bytes() for p in archive.iterdir()} != blobs:
            raise ValueError("Existing scope archive differs")
        return archive
    pending = output / (name + ".pending")
    pending.mkdir()
    try:
        for filename, raw in blobs.items():
            (pending / filename).write_bytes(raw)
        os.rename(pending, archive)
    finally:
        if pending.exists():
            for p in pending.iterdir():
                p.unlink()
            pending.rmdir()
    return validate_history_archive(archive, output / "tool-boundary")


class ScopeRuntime:
    def __init__(
        self, model, environment, *, arm="restored", schedule=(), reserve_seconds=10
    ):
        if model.history is None or model.history.policy["mode"] != "none":
            raise ValueError(
                "Scope prototype requires measured unmasked observation history"
            )
        if not model.limits.get("structured_finalization"):
            raise ValueError("Scope prototype requires structured finalization")
        self.model, self.env = model, environment
        self.controller = ScopedContext(model.output / "scopes", arm=arm)
        self.schedule = copy.deepcopy(list(schedule))
        self.reserve_seconds = reserve_seconds
        self.pending_return = None
        self.pending_identity = None
        self.pending_path = model.output / "scope-pending-return.json"
        self.env.scope_return_tools = getattr(environment, "scope_return_tools", set())
        if self.pending_path.exists():
            saved = json.loads(self.pending_path.read_bytes())
            self.pending_return = validate_return(saved["value"], model.history)
            self.pending_identity = saved
        self.return_requested = False
        self.seen_reset_boundary = None
        self.prior_view = None
        state = self.controller.state or {}
        frame = state.get("frame") or {}
        rejected = [
            int(p.stem.rsplit("-", 1)[1])
            for p in model.output.glob("scope-entry-rejected-[0-9][0-9][0-9].json")
        ]
        self.next_scope = max(
            [
                0,
                frame.get("schedule_index") or 0,
                state.get("last_schedule_index") or 0,
                *rejected,
            ]
        )
        model.scope_runtime = environment.scope_runtime = self
        # Existing bounded same-attempt observation mount, including current scopes.
        environment.observations = model.history.root

    @property
    def active(self):
        return self.controller.active

    def world(self):
        return capture_world(
            self.env.workspace, self.env.scratch.current if self.env.scratch else None
        )

    def project(self, messages, base):
        return self.controller.project(messages, default_view=base)

    def before_query(self, messages):
        self.controller.reconcile(messages)
        current = ledger(self.model, self.env)
        status = self.controller.guard(current)
        if self.pending_return is not None:
            saved = self.pending_identity
            if not self.active:
                if self.controller.state.get("last_scope_id") != saved["scope_id"]:
                    raise ValueError("Pending return disagrees with committed scope")
                archive = self.model.output / ("scope-history-" + saved["scope_id"][1:])
                self.env.history_archive = validate_history_archive(
                    archive, self.model.output / "tool-boundary"
                )
                self._clear_pending()
                return
            if (
                self.controller.state["frame"]["id"] != saved["scope_id"]
                or self.env.calls < saved["tool_calls"]
                or not any(
                    m.get("role") == "tool"
                    and m.get("tool_call_id") == saved["tool_call_id"]
                    for m in messages
                )
            ):
                raise ValueError(
                    "Accepted return lacks a reconciled completed tool cycle; do not replay effects"
                )
            value = self.pending_return
            self._return(messages, value, forced=False)
            self._clear_pending()
        elif self.active and status == "return_required":
            self._return(
                messages,
                {
                    "status": "inconclusive",
                    "findings": "The bounded investigation reached its allowance without an accepted return.",
                    "evidence": [],
                    "remaining": [
                        "Inspect retained changes and historical evidence; no child completion is certified."
                    ],
                },
                forced=True,
            )
        elif self.active:
            frame = self.controller.state["frame"]
            if (
                frame["model_call_limit"] - current["model_calls"] <= 1
                or frame["deadline"] - time.monotonic() <= 5
            ):
                self.request_return(messages)
        self.after_reset(messages)

    def after_reset(self, messages):
        fresh = self.model.fresh_context
        boundary = fresh.boundary if fresh else None
        if boundary is None or boundary == self.seen_reset_boundary:
            return
        if self.active:
            raise ValueError("Fresh reset attempted inside scope")
        if self.controller.state is not None:
            fresh.pre_reset_messages = self.controller.project(messages[:boundary])
            self.controller.adopt_reset(
                messages, fresh.project(messages), ledger(self.model, self.env)
            )
        self.seen_reset_boundary = boundary

    def request_return(self, messages):
        if not self.return_requested:
            messages.append({"role": "user", "content": RETURN_REQUEST})
            self.return_requested = True

    def consider_context(self, messages, report):
        """Called after exact token measurement, before spending an inference call."""
        available = report["available_completion_tokens"]
        if self.active:
            if available < 2048:
                self._return(
                    messages,
                    {
                        "status": "inconclusive",
                        "findings": "Context pressure prevented a model-written scope return.",
                        "evidence": [],
                        "remaining": ["Inspect retained work and the scope history."],
                    },
                    forced=True,
                )
                return True
            if available < 8192 and not self.return_requested:
                self.request_return(messages)
                return True
            return False
        if self.next_scope >= len(self.schedule):
            return False
        spec = self.schedule[self.next_scope]
        if self.model.calls < spec["after_model_calls"]:
            return False
        self.next_scope += 1
        current = ledger(self.model, self.env)
        seconds = min(
            spec["max_seconds"],
            current["deadline_monotonic"] - time.monotonic() - self.reserve_seconds,
        )
        calls = min(
            spec["max_model_calls"],
            current["model_call_limit"] - current["model_calls"] - 2,
        )
        reason = None
        if available < 8192:
            reason = "insufficient measured parent headroom"
        if (
            seconds < 5
            or calls < 2
            or current["tool_call_limit"] - current["tool_calls"] < 3
        ):
            reason = "insufficient parent/return reserve"
        if reason:
            (
                self.model.output / f"scope-entry-rejected-{self.next_scope:03d}.json"
            ).write_bytes(
                encoded(
                    {
                        "reason": reason,
                        "spec": spec,
                        "context": report,
                        "budget": current,
                    }
                )
            )
            return False
        parent = self.model.history.wire(self.model.request_messages(messages))
        self.controller.enter(
            messages,
            parent,
            current,
            self.world(),
            objective=spec["objective"],
            max_seconds=seconds,
            max_model_calls=calls,
            schedule_index=self.next_scope,
        )
        return True

    def actions(self, message, response, finish_reason):
        calls = message.get("tool_calls", [])
        names = (
            [
                c["function"].get("name")
                for c in calls
                if isinstance(c, dict) and isinstance(c.get("function"), dict)
            ]
            if isinstance(calls, list)
            else []
        )
        try:
            if NAME in names:
                if not self.active:
                    raise ValueError(
                        "No investigation is active; continue the parent task or finish_attempt"
                    )
                if finish_reason != "tool_calls" or len(calls) != 1:
                    raise ValueError(
                        "Call return_scope alone; no calls in this response executed"
                    )
                call = calls[0]
                raw = call["function"]["arguments"]
                if not isinstance(raw, str) or len(raw.encode()) > 2048:
                    raise ValueError("Return arguments exceed2048 bytes")
                if (
                    call.get("type") != "function"
                    or not isinstance(call.get("id"), str)
                    or not call["id"]
                ):
                    raise ValueError("Invalid return call identity")
                value = validate_return(
                    json.loads(
                        raw, object_pairs_hook=_object, parse_constant=_constant
                    ),
                    self.model.history,
                )
                return [
                    {
                        "tool": NAME,
                        "payload": value,
                        "tool_call_id": call["id"],
                        "command": "return_scope (unverified memory; no command execution)",
                    }
                ]
            if self.active and (
                self.return_requested
                or any(
                    n
                    in (
                        "finish_attempt",
                        "checkpoint_context",
                        "submit_attempt",
                        "report_blocker",
                    )
                    for n in names
                )
            ):
                raise ValueError(
                    "Investigation cannot finalize or reset the parent. Call return_scope alone with complete, inconclusive or blocked status"
                )
        except (ValueError, TypeError, KeyError) as error:
            raise failure(
                error,
                response,
                label="Scope response rejected",
                instruction="Original budgets continue. Use return_scope only inside an active investigation; otherwise continue the parent task.",
            ) from error
        return None

    def _clear_pending(self):
        self.pending_return = self.pending_identity = None
        self.pending_path.unlink(missing_ok=True)

    def accept(self, value, tool_call_id):
        if not self.active or self.pending_return is not None:
            raise ValueError("No active scope awaiting a return")
        self.pending_return = validate_return(value, self.model.history)
        self.pending_identity = {
            "value": self.pending_return,
            "tool_call_id": tool_call_id,
            "tool_calls": self.env.calls,
            "scope_id": self.controller.state["frame"]["id"],
        }
        with self.pending_path.open("xb") as stream:
            stream.write(encoded(self.pending_identity))
            stream.flush()
            os.fsync(stream.fileno())
        return "Unverified investigation return recorded. Current workspace changes are retained. The next request resumes the parent; the task has not been submitted."

    def _return(self, messages, value, *, forced):
        frame = self.controller.state["frame"]
        archive = publish_history(self.model.output, frame["id"], messages)
        current = ledger(self.model, self.env)
        self.controller.leave(
            messages, current, self.world(), value, self.model.history, forced=forced
        )
        self.env.history_archive = archive
        self.return_requested = False
        # Add bounded historical facts without elevating the model's interpretation.
        evidence = render(value["evidence"], self.model.history)
        event = {
            "scope_id": frame["id"],
            "forced": forced,
            "history_archive": archive.name,
            "evidence": evidence,
            "model_calls": self.model.calls,
            "tool_calls": self.env.calls,
            "transition": "returned",
            "controller_commit": json.loads(self.controller.pointer.read_bytes()),
        }
        (self.model.output / f"scope-return-{frame['id']}.json").write_bytes(
            encoded(event)
        )
