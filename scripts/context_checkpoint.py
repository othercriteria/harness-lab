"""Bounded model-authored memory; never executable or verified evidence."""

import copy
import json

from spec_blocker import _constant, _object

NAME = "checkpoint_context"
MAX_BYTES = 8192
SUMMARY_BYTES = 4096
REPLY_TOKENS = 2048
THINK_TOKENS = 256
INSTRUCTION = (
    " The harness may request context checkpoints before fresh-session resets."
    " Only when requested, call checkpoint_context alone with a concise continuation"
    " note. This saves unverified memory; it does not submit work or execute commands."
    " Summary generation consumes your existing time, token and call allowances."
)
REQUEST = (
    "Context checkpoint requested. Your next response must call checkpoint_context"
    " alone; no implementation tools will execute in this checkpoint response."
    " Use only the space needed, up to 250 words and below 4096 UTF-8 bytes; shorter is fine."
    " Lead with unfinished deliverables, any established blocker and concrete next actions."
    " Then list changed"
    " file paths, observed checks/failures with observation IDs, and decisions needed"
    " to continue. Distinguish observations from assumptions. Do not recap function"
    " implementations, API schemas or the public task; the files remain available."
    " Do not claim new work. The original task, workspace and historical records will remain"
    " available. This request uses the same remaining budgets, with at most 2048 reply"
    " tokens and at most 256 thinking tokens when a native thinking cap is configured."
    " If validation fails, the harness may offer one repair using the same budgets;"
    " otherwise it may reset without a summary."
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
                    "description": "Unverified continuation note; at most 4096 UTF-8 bytes as well as the schema character limit. Use only the space needed.",
                }
            },
        },
    },
}


def tool(shared=False, *, progress=False):
    if progress and not shared:
        raise ValueError("Checkpoint progress requires shared evidence")
    if not shared:
        return TOOL
    from finish_attempt import TOOL as FINISH_TOOL

    result = copy.deepcopy(TOOL)
    properties = result["function"]["parameters"]["properties"]
    properties["evidence"] = copy.deepcopy(
        FINISH_TOOL["function"]["parameters"]["properties"]["evidence"]
    )
    properties["evidence"]["description"] = (
        "Optional historical evidence to carry into the next context, using the same"
        " observation/public-contract references as final handoff. At most four;"
        " cite failures as well as successes when useful."
    )
    if progress:
        from progress_report import schema

        properties["progress"] = schema(properties.pop("evidence"))
        result["function"]["parameters"]["required"].append("progress")
    return result


def request(shared=False, *, progress=False):
    if progress:
        return REQUEST + (
            " Include progress with concise implemented work, check outcomes, remaining"
            " public requirements, obstacle and next action. Report change since the"
            " previous report (or task start for the first). Aim for 100–150 words"
            " across summary and report; avoid repeating the same facts. Put shared"
            " citations in progress.evidence. These are unverified claims, not a"
            " completion forecast or a signal to stop. Empty lists and uncertain"
            " or unknown states are valid. Historical checks may be stale after edits."
            " Use implemented for saved changes to required artifacts; an empty list"
            " is correct before changes. Keep source-reading findings in summary."
            " Populate remaining from explicit public requirements; put optional"
            " verification plans in next_action when relevant."
        )
    return REQUEST + (
        " Optionally include evidence using the same references as final handoff;"
        " selected historical tool results will accompany your continuation note."
        if shared
        else ""
    )


def citations(value):
    """One shared citation interface, whether supplied with memory or progress."""
    return (
        value["progress"]["evidence"]
        if "progress" in value
        else value.get("evidence", [])
    )


def validate(value, *, shared=False, history=None, progress=False):
    if progress and not shared:
        raise ValueError("Checkpoint progress requires shared evidence")
    allowed = (
        {"summary", "progress"}
        if progress
        else {"summary", "evidence"}
        if shared
        else {"summary"}
    )
    if not isinstance(value, dict) or "summary" not in value or set(value) - allowed:
        raise ValueError(
            "Checkpoint fields differ from the enabled schema"
            if progress
            else "Checkpoint requires only a summary field"
        )
    summary = value["summary"]
    if (
        not isinstance(summary, str)
        or not summary.strip()
        or len(summary.encode()) > SUMMARY_BYTES
    ):
        raise ValueError("Checkpoint summary must be 1..4096 UTF-8 bytes")
    if progress:
        from progress_report import validate as validate_progress

        if "progress" not in value:
            raise ValueError("Checkpoint requires a progress report")
        validate_progress(value["progress"], history)
    elif shared:
        from evidence import validate_evidence

        validate_evidence(value.get("evidence", []), history)
    if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("Checkpoint arguments exceed 8192 bytes")
    return value


def failure(error, response):
    from tool_repair import failure as repair_failure

    return repair_failure(
        error,
        response,
        label="Context checkpoint rejected",
        instruction="Continue according to the next harness notice.",
    )


def repair_request(shared=False, *, progress=False):
    if progress:
        return (
            "Repair the rejected checkpoint with one checkpoint_context call alone."
            " Supply summary and progress using the tool schema; place shared citations"
            " in progress.evidence. Correct the reported validation error without"
            " inventing work or certainty. This is the only checkpoint repair opportunity;"
            " original budgets continue unchanged. If repair fails, continuation may"
            " reset without a summary or progress report."
        )
    return (
        "Repair the rejected checkpoint with one checkpoint_context tool call alone. "
        'Use arguments {"summary":"your concise continuation note"}. '
        + (
            "Optional evidence may be included once. "
            if shared
            else "Use only the summary field. "
        )
        + "Put the note in the summary argument, not in prose. "
        "Each JSON field must occur once. Correct the validation error reported above; "
        "this is the only checkpoint repair opportunity. Existing time, token and call "
        "budgets continue unchanged. If repair fails, continuation may reset without a summary."
    )


def action(
    message,
    response,
    finish_reason,
    *,
    requested,
    shared=False,
    history=None,
    progress=False,
):
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
            json.loads(raw, object_pairs_hook=_object, parse_constant=_constant),
            shared=shared,
            history=history,
            progress=progress,
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
