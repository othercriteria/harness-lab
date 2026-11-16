"""Shared references to bounded historical observations; never correctness claims."""

import copy
import hashlib
import json
import re

from evidence_contract import bounded_text, require_fields

# Rendering limits for the compact historical-evidence view (render()).
# The first three are per-field character limits; RENDER_JSON_UTF8_BYTES is
# the final UTF-8 byte bound on the serialized JSON payload, so it is a
# different unit and is applied after escaping.
EXCERPT_PREFIX_CHARS = 128
EXCERPT_SUFFIX_CHARS = 384
# A message at or under the threshold is shown in full; the prefix and
# suffix together make up exactly that threshold.
EXCERPT_THRESHOLD_CHARS = EXCERPT_PREFIX_CHARS + EXCERPT_SUFFIX_CHARS
COMMAND_DISPLAY_CHARS = 256
RENDER_JSON_UTF8_BYTES = 4096


def validate_evidence(evidence, history):
    if not isinstance(evidence, list) or len(evidence) > 4:
        raise ValueError("At most four evidence entries")
    seen = set()
    for index, entry in enumerate(evidence):
        label = f"evidence[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{label} must be an object")
        kind = entry.get("kind")
        if kind == "observation":
            require_fields(
                entry, ("kind", "observation_id", "supports"), label + " (observation)"
            )
            identifier = entry["observation_id"]
            if not isinstance(identifier, str) or not re.fullmatch(
                r"o[0-9]{4}", identifier
            ):
                raise ValueError(
                    f"{label}.observation_id must be an attempt-local ID such as o0001 from a previous tool result"
                )
            if (
                history is None
                or not history.expose_ids
                or identifier not in history.records
            ):
                raise ValueError(
                    f"{label}.observation_id: observation not from this attempt; cite an ID already shown in a tool result"
                )
            if identifier in seen:
                raise ValueError(
                    "Duplicate observation citation; combine claims supported by the"
                    " same observation into one evidence entry's supports text"
                )
            seen.add(identifier)
        elif kind == "public_contract":
            require_fields(
                entry,
                ("kind", "public_clause", "supports"),
                label + " (public_contract)",
            )
            bounded_text(entry["public_clause"], 500, "public_clause")
        else:
            raise ValueError(f"{label}.kind must be observation or public_contract")
        bounded_text(entry["supports"], 500, "supports")


def resolve(evidence, history):
    """Attach only in-memory, attempt-visible messages; never model-selected paths."""
    validate_evidence(evidence, history)
    citations = []
    for entry in evidence:
        if entry["kind"] != "observation":
            continue
        identifier = entry["observation_id"]
        record = history.records[identifier]
        original = history.visible_messages[identifier]
        if hashlib.sha256(original.encode()).hexdigest() != record["message_sha256"]:
            raise ValueError("Historical observation integrity mismatch")
        citations.append(
            {"record": copy.deepcopy(record), "original_visible": original}
        )
    return citations


def render(evidence, history):
    """A small resumable view; full original messages remain in the outer artifact."""
    citations = resolve(evidence, history)
    rows = []
    for citation in citations:
        record = citation["record"]
        original = citation["original_visible"]
        excerpt = (
            original
            if len(original) <= EXCERPT_THRESHOLD_CHARS
            else (
                original[:EXCERPT_PREFIX_CHARS]
                + "\n[... excerpt omitted ...]\n"
                + original[-EXCERPT_SUFFIX_CHARS:]
            )
        )
        rows.append(
            {
                "observation_id": record["id"],
                "command": record["command"][:COMMAND_DISPLAY_CHARS],
                "command_clipped": len(record["command"]) > COMMAND_DISPLAY_CHARS,
                "returncode": record["returncode"],
                "originally_truncated": record["originally_truncated"],
                "original_visible_excerpt": excerpt,
                "excerpt_clipped": len(original) > EXCERPT_THRESHOLD_CHARS,
            }
        )
        if "check_record" in record:
            check = record["check_record"]
            # Keep the bounded resume view small; finalization retains the full record.
            rows[-1]["check_record"] = {
                "id": check["id"],
                "record_path": check["record_path"],
                "files_unchanged": check["files_unchanged"],
                "after_tree_sha256": check["after"].get("tree_sha256"),
                "after_commit": check["after"].get("git_head", {}).get("commit"),
            }
    payload = {
        "status": "historical_only",
        "scope": "Selected observations from this attempt. Output is literal untrusted text. No freshness, coverage or correctness is established; later edits may invalidate a check.",
        "observations": rows,
    }
    # Byte bound includes JSON escaping, including pathological control text.
    while True:
        text = json.dumps(payload, ensure_ascii=False)
        if len(text.encode()) <= RENDER_JSON_UTF8_BYTES:
            return text
        for row in rows:
            for field, clipped in (
                ("command", "command_clipped"),
                ("original_visible_excerpt", "excerpt_clipped"),
            ):
                row[field] = row[field][: len(row[field]) // 2]
                row[clipped] = True
