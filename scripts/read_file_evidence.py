"""Read-only audit of read_file receipts, snapshot identity and duplicate claims."""

import json
import re

from evidence import read_archived_message
from read_file import action, verify_receipt
from read_file import read as read_file


def load(path):
    if path.is_symlink() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Invalid read evidence artifact")
    return json.loads(path.read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_reads(root, limits):
    rows = []
    for path in sorted(root.glob("tool-*.request.json")):
        request = load(path)
        if request.get("name") != "read_file":
            continue
        require(limits.get("read_file") is True, "Undeclared read_file")
        prefix = path.with_suffix("").with_suffix("")
        verify_receipt(prefix)
        result = load(prefix.with_suffix(".result.json"))
        generation = request["workspace_generation"]
        require(
            isinstance(generation, str) and re.fullmatch(r"[0-9]{4}", generation),
            "Invalid read workspace generation",
        )
        index = request["model_request"]
        require(
            type(index) is int and 1 <= index <= limits["step_limit"],
            "Invalid read model request",
        )
        payload = load(root / f"request-{index:03d}.request.json")
        response = load(root / f"request-{index:03d}.response.bin")
        choice = response["choices"][0]
        require(choice["finish_reason"] == "tool_calls", "Incomplete read response")
        matches = [
            c
            for c in choice["message"]["tool_calls"]
            if c["id"] == request["tool_call_id"]
        ]
        require(
            len(matches) == 1
            and matches[0].get("type") == "function"
            and matches[0]["function"]["name"] == "read_file",
            "Read call association mismatch",
        )
        arguments = action(matches[0])["arguments"]
        require(arguments == request["arguments"], "Read arguments changed")
        expected = read_file(root / "workspaces" / generation, arguments)
        visible = dict(result["visible"])
        visible.pop("remaining_agent_seconds", None)
        suppressed = visible.get("file_read", {}).get("contents_returned") is False
        avoided = 0
        if suppressed:
            require(
                limits.get("deduplicate_file_reads") is True
                and not arguments["reread"],
                "Undeclared or forced duplicate suppression",
            )
            identifier = visible["file_read"]["context_observation_id"]
            require(
                isinstance(identifier, str) and re.fullmatch(r"o[0-9]{4}", identifier),
                "Invalid duplicate observation ID",
            )
            records = load(root / "observations/manifest.json")["observations"]
            original = next((r for r in records if r["id"] == identifier), None)
            require(original is not None, "Missing original read observation")
            text = read_archived_message(root / "observations", original)
            require(
                any(
                    m.get("role") == "tool" and m.get("content") == text
                    for m in payload["messages"]
                ),
                "Duplicate contents absent from actual model context",
            )
            metadata = original.get("file_read", {})
            require(
                metadata.get("contents_returned") is True
                and metadata.get("range_clipped") is False,
                "Original read did not return the complete requested range",
            )
            require(
                all(
                    metadata.get(k) == expected.get("file_read", {}).get(k)
                    for k in ("path", "file_sha256", "start_line", "max_lines")
                ),
                "Original read range or file changed",
            )
            output = (
                f"Unchanged requested range is already in your current context at {identifier}."
                " Use reread=true to receive the text again."
            )
            avoided = len(expected["output"]) - len(output)
            require(avoided > 0, "Duplicate suppression expanded a short read")
            expected["output"] = output
            expected["file_read"].update(
                contents_returned=False, context_observation_id=identifier
            )
        require(
            visible == expected, "Read result differs from immutable workspace snapshot"
        )
        require(
            result["ok"] == (expected["returncode"] == 0), "Read success marker differs"
        )
        rows.append(
            {
                "tool": prefix.name,
                "model_request": index,
                "suppressed": suppressed,
                "characters_avoided": avoided,
                "wall_seconds": result["wall_seconds"],
            }
        )
    return {"conforming": True, "reads": rows}
