"""Bounded model-authored memory; never executable or verified evidence."""

import json

from mini_bootstrap import FormatError
from spec_blocker import _constant, _object

NAME = "checkpoint_context"
MAX_BYTES = 8192
SUMMARY_BYTES = 4096
REPLY_TOKENS = 2048
THINK_TOKENS = 256
INSTRUCTION = (
    " The harness may request one context checkpoint before a fresh-session reset."
    " Only when requested, call checkpoint_context alone with a concise continuation"
    " note. This saves unverified memory; it does not submit work or execute commands."
    " Summary generation consumes your existing time, token and call allowances."
)
REQUEST = (
    "Context checkpoint requested. Your next response must call checkpoint_context"
    " alone; no implementation tools will execute in this checkpoint response."
    " Aim for 150-250 words, comfortably below the hard limit of 4096 UTF-8 bytes."
    " Lead with unfinished deliverables and concrete next actions. Then list changed"
    " file paths, observed checks/failures with observation IDs, and decisions needed"
    " to continue. Distinguish observations from assumptions. Do not recap function"
    " implementations, API schemas or the public task; the files remain available."
    " Do not claim new work. The original task, workspace and historical records will remain"
    " available. This request uses the same remaining budgets, with at most 2048 reply"
    " tokens and at most 256 thinking tokens when a native thinking cap is configured."
    " A missing or malformed checkpoint will not be retried; the harness may reset"
    " without a summary if enough time remains."
)
TOOL = {
    "type": "function",
    "function": {
        "name": NAME,
        "description": "When requested, save a bounded unverified continuation note before context reset; no execution or submission.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["summary"],
            "properties": {
                "summary": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": SUMMARY_BYTES,
                }
            },
        },
    },
}


def validate(value):
    if not isinstance(value, dict) or set(value) != {"summary"}:
        raise ValueError("Checkpoint requires only a summary field")
    summary = value["summary"]
    if (
        not isinstance(summary, str)
        or not summary.strip()
        or len(summary.encode()) > SUMMARY_BYTES
    ):
        raise ValueError("Checkpoint summary must be 1..4096 UTF-8 bytes")
    return value


def failure(error, response):
    return FormatError(
        {
            "role": "user",
            "content": "No calls from that response were executed. Context checkpoint rejected: "
            + str(error)[:500]
            + ". Continue according to the next harness notice.",
            "extra": {"interrupt_type": "FormatError", "response": response},
        }
    )


def action(message, response, finish_reason, *, requested):
    try:
        if not requested:
            raise ValueError(
                "A checkpoint is only allowed when the harness requests it"
            )
        calls = message.get("tool_calls")
        if (
            finish_reason != "tool_calls"
            or not isinstance(calls, list)
            or len(calls) != 1
        ):
            raise ValueError("Checkpoint requires one complete tool call alone")
        call = calls[0]
        if not isinstance(call, dict) or call.get("type") != "function":
            raise ValueError("Expected a function call")
        identifier = call.get("id")
        fn = call.get("function")
        if (
            not isinstance(identifier, str)
            or not identifier
            or len(identifier.encode()) > 256
        ):
            raise ValueError("Invalid checkpoint tool-call ID")
        if not isinstance(fn, dict) or fn.get("name") != NAME:
            raise ValueError("Only checkpoint_context is accepted for this response")
        raw = fn.get("arguments")
        if not isinstance(raw, str) or len(raw.encode()) > MAX_BYTES:
            raise ValueError("Checkpoint arguments exceed 8192 bytes or are not text")
        value = validate(
            json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
        )
        return [
            {
                "tool": NAME,
                "payload": value,
                "raw_arguments": raw,
                "tool_call_id": identifier,
            }
        ]
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise failure(error, response) from error
