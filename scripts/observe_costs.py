"""Bounded, cached projections of recorded trial costs; never execute artifacts."""

import json
import math
import threading
from collections import OrderedDict
from pathlib import Path


def number(value):
    return (
        value
        if type(value) in (int, float) and math.isfinite(value) and value >= 0
        else None
    )


def sequence(value):
    return value if isinstance(value, list) else []


class CostProjection:
    def __init__(self):
        self.cache = OrderedDict()
        self.lock = threading.Lock()

    def get(self, evidence, root):
        patterns = (
            "request-*.request.json",
            "request-*.response.bin",
            "request-*.timing.json",
            "context-checkpoint-request-*.json",
            "fresh-context-reset-*.json",
            "summary.json",
            "trajectory.json",
        )
        files = sorted(
            {
                p
                for pattern in patterns
                for p in root.glob(pattern)
                if not p.is_symlink() and p.is_file()
            }
        )
        try:
            fingerprint = tuple(
                (p.name, s.st_ino, s.st_size, s.st_mtime_ns)
                for p in files
                for s in [p.stat()]
            )
        except FileNotFoundError:
            return {
                "status": "updating",
                "note": "Evidence changed during refresh; retrying.",
            }
        key = str(root)
        with self.lock:
            cached = self.cache.get(key)
            if cached and cached[0] == fingerprint:
                self.cache.move_to_end(key)
                return cached[1]
        value = self.project(evidence, root, files)
        with self.lock:
            self.cache[key] = (fingerprint, value)
            self.cache.move_to_end(key)
            while len(self.cache) > 64:
                self.cache.popitem(last=False)
        return value

    def project(self, evidence, root, files):
        def read(path):
            value = evidence.read(path)
            return value if isinstance(value, dict) else {}

        names = {p.name for p in files}
        requests = sorted(
            n.removesuffix(".request.json")
            for n in names
            if n.startswith("request-")
            and n.endswith(".request.json")
            and n[8:-13].isdigit()
        )
        if not requests:
            return None
        summary = read(root / "summary.json")
        checkpoint_indices = set()
        for path in files:
            if path.name.startswith("context-checkpoint-request-"):
                index = read(path).get("model_calls")
                if type(index) is int and index >= 0:
                    checkpoint_indices.add(index + 1)
        wall = []
        checkpoint = []
        finalization = []
        prompt = []
        predicted = []
        responses = 0
        for prefix in requests:
            seconds = number(read(root / (prefix + ".timing.json")).get("wall_seconds"))
            response = read(root / (prefix + ".response.bin"))
            if seconds is not None:
                wall.append(seconds)
                if int(prefix.split("-")[1]) in checkpoint_indices:
                    checkpoint.append(seconds)
            if not response:
                continue
            responses += 1
            timing = response.get("timings") or {}
            if isinstance(timing, dict):
                for field, values in (
                    ("prompt_ms", prompt),
                    ("predicted_ms", predicted),
                ):
                    value = number(timing.get(field))
                    if value is not None:
                        values.append(value / 1000)
            choices = sequence(response.get("choices"))
            message = (
                choices[0].get("message", {})
                if choices and isinstance(choices[0], dict)
                else {}
            )
            if (
                isinstance(message, dict)
                and any(
                    isinstance(call, dict)
                    and isinstance(call.get("function"), dict)
                    and call["function"].get("name")
                    in ("finish_attempt", "submit_attempt", "report_blocker")
                    for call in sequence(message.get("tool_calls"))
                )
                and seconds is not None
            ):
                finalization.append(seconds)

        first_edit = last_edit = None
        read_calls = checkpoint_calls = 0
        calls = {}
        raw, truncated = evidence.text(root / "trajectory.json", 8 * 1024 * 1024)
        try:
            trajectory = json.loads(raw) if raw and not truncated else {}
        except ValueError:
            trajectory = {}
        trajectory = trajectory if isinstance(trajectory, dict) else {}
        limits = summary.get("limits") or {}
        allowance = (
            number(limits.get("agent_wall_seconds"))
            if isinstance(limits, dict)
            else None
        )
        messages = trajectory.get("messages")
        for message in messages if isinstance(messages, list) else []:
            if not isinstance(message, dict):
                continue
            for call in sequence(message.get("tool_calls")):
                function = call.get("function", {}) if isinstance(call, dict) else {}
                if not isinstance(function, dict):
                    continue
                name = function.get("name")
                read_calls += name == "read_file"
                checkpoint_calls += name == "checkpoint_context"
                try:
                    args = json.loads(function.get("arguments", "{}"))
                except (ValueError, TypeError):
                    continue
                if (
                    name in ("edit_file", "write_file")
                    and isinstance(args, dict)
                    and isinstance(args.get("path"), str)
                ):
                    path = args["path"].removeprefix("/workspace/")
                    if not path.startswith("tests/") and not Path(path).name.startswith(
                        "test_"
                    ):
                        identifier = call.get("id")
                        if isinstance(identifier, str):
                            calls[identifier] = name
            if (
                message.get("role") != "tool"
                or not isinstance(message.get("tool_call_id"), str)
                or message["tool_call_id"] not in calls
                or allowance is None
            ):
                continue
            content = message.get("content", "")
            if not isinstance(content, str) or not content.startswith(
                "Tool result metadata: "
            ):
                continue
            try:
                metadata = json.loads(
                    content.split("\n", 1)[0].removeprefix("Tool result metadata: ")
                )
                remaining = number(metadata.get("remaining_agent_seconds"))
            except (ValueError, AttributeError):
                continue
            if remaining is not None and 0 <= remaining <= allowance:
                elapsed = allowance - remaining
                first_edit = elapsed if first_edit is None else first_edit
                last_edit = elapsed

        task_seconds = number(summary.get("task_wall_seconds"))
        return {
            "status": "recorded trial" if summary else "live; recorded calls only",
            "task_seconds": task_seconds,
            "first_structured_edit_seconds_approx": first_edit,
            "after_last_structured_edit_seconds_approx": max(
                0, task_seconds - last_edit
            )
            if task_seconds is not None and last_edit is not None
            else None,
            "model_request_seconds": sum(wall) if wall else None,
            "checkpoint_request_seconds": sum(checkpoint) if wall else None,
            "finalization_request_seconds": sum(finalization) if wall else None,
            "backend_prompt_seconds": sum(prompt) if prompt else None,
            "backend_predicted_seconds": sum(predicted) if predicted else None,
            "verification_seconds": number(summary.get("verification_wall_seconds")),
            "context_resets": sum(n.startswith("fresh-context-reset-") for n in names),
            "read_calls": read_calls if trajectory else None,
            "checkpoint_calls": checkpoint_calls if trajectory else None,
            "coverage": {
                "requests": len(requests),
                "timed_requests": len(wall),
                "responses": responses,
                "backend_prompt_reports": len(prompt),
                "backend_decode_reports": len(predicted),
                "trajectory_available": bool(trajectory),
                "trajectory_truncated": truncated,
            },
            "note": "All recorded requests in this trial, independent of the timeline page. Recovery/finalization are subsets of model time; backend timers overlap client time. Missing or unfinished response work is unknown. Edit times approximate structured edit/write tool results (including failed attempts), excluding tests and bash edits. After-last-edit includes reasoning, inspection, tests, recovery, handoff and evaluation. Task time excludes load/warm-up, human review and separately scheduled outer probes.",
        }
