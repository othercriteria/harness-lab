"""Default-off exact edit schema and strict untrusted argument parsing."""

import json

from sandbox_worker import validate_edit_arguments
from spec_blocker import _constant, _object

NAME = "edit_file"
_CORE_INSTRUCTION = (
    "\n\nUse edit_file for focused replacements in existing UTF-8 workspace files."
    " old_text must match exactly once, including whitespace; otherwise nothing changes."
    " On a mismatch, reread the relevant current file region before retrying."
    " Combined old/new text"
    " <=32768 UTF-8 bytes; file <=262144 bytes."
)


def instruction(write_available=False):
    return _CORE_INSTRUCTION + (
        " Use write_file to create files or rewrite a module when appropriate."
        if write_available
        else " Use bash to create files or rewrite a module when appropriate."
    )


INSTRUCTION = instruction()
TOOL = {
    "type": "function",
    "function": {
        "name": NAME,
        "description": "Replace exactly one literal occurrence in an existing UTF-8 workspace file; no fuzzy matching or newline normalization.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Existing file inside /workspace.",
                },
                "old_text": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Exact text occurring once, including whitespace.",
                },
                "new_text": {
                    "type": "string",
                    "description": "Replacement text; empty deletes the match.",
                },
            },
            "required": ["path", "old_text", "new_text"],
            "additionalProperties": False,
        },
    },
}


def parse(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 262144:
        raise ValueError("Serialized edit arguments exceed262144 UTF-8 bytes")
    return validate_edit_arguments(
        json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
    )


def action(call):
    arguments = parse(call["function"]["arguments"])
    return {
        "tool": NAME,
        "arguments": arguments,
        "tool_call_id": call["id"],
        # Legacy observation archive field is descriptive metadata, never executed.
        "command": NAME + " " + json.dumps(arguments["path"], ensure_ascii=True),
    }
