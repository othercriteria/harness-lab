"""Opt-in whole-file write schema; execution stays inside the sandbox worker."""

import json

from sandbox_worker import validate_write_arguments
from tool_arguments import load_arguments

NAME = "write_file"
INSTRUCTION = (
    "\n\nUse write_file to create or fully rewrite a UTF-8 workspace file without shell"
    " quoting. Supply literal content, not a patch; existing content is replaced."
    " Parent directories must exist;"
    " symlink paths are rejected. Content <=32768 UTF-8 bytes; existing file <=262144 bytes."
)
TOOL = {
    "type": "function",
    "function": {
        "name": NAME,
        "description": "Create or atomically replace one UTF-8 workspace file with literal content; no command execution.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["path", "content"],
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File inside /workspace; parent directories must exist.",
                },
                "content": {
                    "type": "string",
                    "description": "Complete literal file contents, including intended newlines; empty is allowed.",
                },
            },
        },
    },
}


def parse(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 262144:
        raise ValueError("Serialized write arguments exceed 262144 UTF-8 bytes")
    return validate_write_arguments(load_arguments(raw))


def action(call):
    arguments = parse(call["function"]["arguments"])
    return {
        "tool": NAME,
        "arguments": arguments,
        "tool_call_id": call["id"],
        "command": NAME + " " + json.dumps(arguments["path"], ensure_ascii=True),
    }
