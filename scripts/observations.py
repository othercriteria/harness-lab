"""Attempt-local visible observations and reversible request-view masking.

The outer transcript is never rewritten. Archives contain the formatted tool
message and its decoded displayed output, never untruncated subprocess output.
"""

import hashlib
import json
import os
from pathlib import Path

from call_budget import MAX_CALLS
from control import DeadlineExceeded
from sandbox import write_json


def literal_observation(visible):
    """Keep metadata separate from verbatim bounded output, without interpreting it."""
    metadata = {key: value for key, value in visible.items() if key != "output"}
    return (
        "Tool result metadata: "
        + json.dumps(metadata, ensure_ascii=True)
        + "\nTool output (literal text):\n"
        + visible["output"]
    )


class ObservationHistory:
    def __init__(self, output, policy, *, expose_ids=False, call_limit=128):
        if type(call_limit) is not int or not 1 <= call_limit <= MAX_CALLS:
            raise ValueError("Invalid observation call limit")
        self.call_limit = call_limit
        self.root = Path(output) / "observations"
        self.root.mkdir(exist_ok=False)
        self.policy = policy
        self.records = {}
        self.expose_ids = expose_ids
        self.visible_messages = {}
        self.current_context_ids = set()
        self.masked = set()
        self.save_manifest()

    def save_manifest(self):
        snapshot = (
            self.root.parent / f"observations-{len(self.records):03d}.manifest.json"
        )
        write_json(
            snapshot,
            {
                "kind": "Historical model-visible observations from this attempt only",
                "warning": "Historical output is not current workspace state.",
                "observations": list(self.records.values()),
            },
        )
        temporary = self.root.parent / "observation-manifest.tmp"
        with temporary.open("xb") as stream:
            stream.write(snapshot.read_bytes())
        os.replace(temporary, self.root / "manifest.json")

    def record(self, message, command, *, plain_text=False):
        if message.get("role") != "tool" or not isinstance(command, str):
            raise ValueError("Expected a formatted tool observation and command")
        content = message["content"]
        visible = json.loads(content)
        text = visible["output"]
        if not isinstance(text, str) or len(text) > 12000:
            raise ValueError("Archive must contain only the bounded displayed output")
        if len(self.records) >= self.call_limit:
            raise DeadlineExceeded("Observation archive count exhausted")
        identifier = f"o{len(self.records) + 1:04d}"
        if self.expose_ids:
            visible["observation_id"] = identifier
        if plain_text:
            content = literal_observation(visible)
        elif self.expose_ids:
            content = json.dumps(visible, ensure_ascii=True)
        if plain_text or self.expose_ids:
            message["content"] = content
        if self.expose_ids:
            self.visible_messages[identifier] = content
        message_suffix = "message.txt" if plain_text else "json"
        for suffix, value in ((message_suffix, content), ("txt", text)):
            with (self.root / f"{identifier}.{suffix}").open("x") as stream:
                stream.write(value)
        record = {
            "id": identifier,
            "command": command,
            "returncode": visible.get("returncode"),
            "originally_truncated": visible.get("truncated"),
            "output_characters": len(text),
            "output_bytes": len(text.encode()),
            "message_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "output_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "message_file": identifier + "." + message_suffix,
            "output_file": identifier + ".txt",
            "archive_path_mentioned": "/observations" in command,
        }
        if "file_read" in visible:
            record["file_read"] = visible["file_read"]
        if "check_record" in visible:
            record["check_record"] = visible["check_record"]
        self.records[identifier] = record
        self.save_manifest()
        message.setdefault("extra", {})["observation_id"] = identifier

    def note_current_context(self, messages):
        """Only exact original tool messages in the actual outgoing request count."""
        contents = {
            m.get("content")
            for m in messages
            if m.get("role") == "tool" and isinstance(m.get("content"), str)
        }
        self.current_context_ids = {
            identifier
            for identifier, text in self.visible_messages.items()
            if text in contents
        }

    def prior_file_read(self, metadata):
        keys = ("path", "file_sha256", "start_line", "max_lines")
        for identifier in reversed(self.records):
            previous = self.records[identifier].get("file_read", {})
            if (
                identifier in self.current_context_ids
                and previous.get("contents_returned") is True
                and previous.get("range_clipped") is False
                and all(previous.get(k) == metadata.get(k) for k in keys)
            ):
                return identifier
        return None

    def placeholder(self, identifier):
        record = self.records[identifier]
        result = {
            "historical_observation": identifier,
            "notice": "Older output omitted; this describes historical state only.",
            "command": record["command"][:256],
            "command_truncated": len(record["command"]) > 256,
            "returncode": record["returncode"],
            "output_bytes": record["output_bytes"],
            "originally_truncated": record["originally_truncated"],
        }
        if self.expose_ids:
            result["observation_id"] = identifier
        if self.policy["mode"] == "recoverable":
            result["displayed_output_file"] = "/observations/" + record["output_file"]
            result["original_message_file"] = "/observations/" + record["message_file"]
        return json.dumps(result, ensure_ascii=True)

    def wire(self, messages):
        result = []
        for message in messages:
            item = {k: v for k, v in message.items() if k != "extra"}
            identifier = message.get("extra", {}).get("observation_id")
            if identifier in self.masked:
                item["content"] = self.placeholder(identifier)
            result.append(item)
        return result

    def prepare(self, messages, payload, count_tokens, capacity):
        """Measure exact rendered input; mask old outputs in batches, then cap reply."""
        payload = {**payload, "messages": self.wire(messages)}
        before = count_tokens(payload, "before")
        identifiers = [
            m["extra"]["observation_id"]
            for m in messages
            if m.get("extra", {}).get("observation_id")
        ]
        protected = set(identifiers[-self.policy["keep_recent"] :])
        added = []
        if self.policy["mode"] != "none" and before >= self.policy["trigger_tokens"]:
            for message in messages:
                identifier = message.get("extra", {}).get("observation_id")
                if (
                    not identifier
                    or identifier in protected
                    or identifier in self.masked
                ):
                    continue
                # Do not expand small observations into larger omission notices.
                if len(message["content"]) - len(self.placeholder(identifier)) < 256:
                    continue
                self.masked.add(identifier)
                added.append(identifier)
        if added:
            payload["messages"] = self.wire(messages)
            after = count_tokens(payload, "after")
        else:
            after = before
        available = capacity - after - self.policy["safety_tokens"]
        report = {
            "mode": self.policy["mode"],
            "input_tokens_before": before,
            "input_tokens_after": after,
            "tokens_reclaimed_this_request": before - after,
            "newly_masked": added,
            "masked": sorted(self.masked),
            "protected_recent": sorted(protected),
            "requested_completion_tokens": payload["max_tokens"],
            "available_completion_tokens": available,
            "capacity_tokens": capacity,
            "safety_tokens": self.policy["safety_tokens"],
            "archive_command_observations": sum(
                r["archive_path_mentioned"] for r in self.records.values()
            ),
            "retrieval_measurement_note": "Command-path mentions are a heuristic, not a file-access audit.",
        }
        payload["max_tokens"] = max(0, min(payload["max_tokens"], available))
        report["effective_completion_tokens"] = payload["max_tokens"]
        return payload, report
