"""Opt-in typed terminal handoff. All model fields are bounded untrusted data."""

import json
import re
from types import SimpleNamespace

from mini_bootstrap import FormatError, parse_toolcall_actions
from spec_blocker import CATEGORIES, _constant, _object, _string

NAME = "finish_attempt"
MAX_BYTES = 8192
ECHO = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
DISPOSITION_INSTRUCTION = (
    " Use blocked for supported conflicting requirements, impossible computation or"
    " an unavailable permitted capability, even if partial code exists. Known open"
    " problems may also be reported as blocked; an explicit open-problem policy governs"
    " whether to attempt them within budget. Give the grounds and necessary requirement,"
    " assumption or capability change. Otherwise use submitted (blocker=null) for the actual"
    " result, listing unfinished work in unverified. Difficulty or failed tests"
    " alone are not blockers."
)
INSTRUCTION = (
    "\n\nCall finish_attempt alone to hand off the current workspace and end the attempt."
    + DISPOSITION_INSTRUCTION
    + " A known open problem is unresolved, not proved impossible; unfamiliarity is"
    " insufficient evidence. The outer harness reviews blocked handoffs afterward;"
    " you do not need to arrange review. A contract-only argument may cite public_contract"
    " clauses without executing tests. Copy observation_id from tool-result metadata"
    " when citing executed checks. For coding submissions, cite the final relevant check"
    " after edits, with its actual result and count;"
    " if no check completed after the final edit, disclose that in unverified rather"
    " than implying an earlier check validates the current files."
    " A passing suite is not proof of the entire contract. Mark unchecked claims"
    " unverified and explain empty evidence. In addition to schema character limits,"
    " each text field is limited to the same number of UTF-8 bytes; the serialized"
    " argument JSON, including escapes, is limited to 8192 UTF-8 bytes."
    " Code and claims are checked independently."
)
TERMINAL_SEMANTICS_INSTRUCTION = (
    " A submitted handoff describes"
    " the actual final workspace and work already done, not a plan, promise, or announcement"
    " of future work. State unfinished items as unverified; no edits are required when no"
    " change is needed. For blocked, contradictory_requirements means public requirements"
    " cannot jointly hold; identify the incompatible clauses. impossible_computation_model"
    " means an obligation is impossible under the stated model. open_problem means a"
    " mathematical result is not established, not proved impossible. environment_capability_limit"
    " means a required permitted capability is unavailable. Incomplete starter code, failing"
    " tests, ordinary difficulty, or an unsuccessful implementation are not by themselves"
    " blockers. Implement and repair editable code within the existing budgets. For a blocker,"
    " give category-specific grounds and what"
    " requirement, assumption, or capability must change. An implementation to-do list is"
    " not a contradiction. Retain supported blockers rather than pretending to complete them."
)
CONCISE_INSTRUCTION = (
    " Summary: one or two sentences about the actual outcome (aim below 400 UTF-8 bytes)."
    " Put citations in evidence and unfinished work or unchecked claims in unverified."
    " Avoid repeating the task or implementation."
)
TEXT = {"type": "string", "minLength": 1, "maxLength": 1000}
TOOL = {
    "type": "function",
    "function": {
        "name": NAME,
        "description": "Hand off the workspace without executing commands. An accepted call ends the attempt; invalid arguments return a correctable error within the remaining budget. submitted requires blocker=null; blocked requires a blocker object. Call as the sole tool call in a response.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["disposition", "summary", "evidence", "unverified", "blocker"],
            "properties": {
                "disposition": {"type": "string", "enum": ["submitted", "blocked"]},
                "summary": {
                    **TEXT,
                    "description": "Brief actual outcome, not a plan or a claim beyond observed evidence.",
                },
                "evidence": {
                    "type": "array",
                    "description": "Cite each observation_id at most once; combine claims supported by the same observation into one entry's supports text.",
                    "maxItems": 4,
                    "items": {
                        "anyOf": [
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["kind", "observation_id", "supports"],
                                "properties": {
                                    "kind": {"type": "string", "enum": ["observation"]},
                                    "observation_id": {
                                        "type": "string",
                                        "pattern": "^o[0-9]{4}$",
                                    },
                                    "supports": {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": 500,
                                    },
                                },
                            },
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["kind", "public_clause", "supports"],
                                "properties": {
                                    "kind": {
                                        "type": "string",
                                        "enum": ["public_contract"],
                                    },
                                    "public_clause": {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": 500,
                                    },
                                    "supports": {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": 500,
                                    },
                                },
                            },
                        ],
                    },
                },
                "unverified": {
                    "type": "array",
                    "description": "Unfinished work and unchecked claims. A supported blocker belongs in blocker with disposition blocked.",
                    "maxItems": 4,
                    "items": {"type": "string", "minLength": 1, "maxLength": 500},
                },
                "blocker": {
                    "anyOf": [
                        {"type": "null"},
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["category", "argument", "necessary_change"],
                            "properties": {
                                "category": {
                                    "type": "string",
                                    "enum": sorted(CATEGORIES),
                                },
                                "argument": {
                                    **TEXT,
                                    "description": "Grounds for this blocker category: incompatibility, impossibility, unavailable capability, or known unresolved status. Open status is not proof of impossibility.",
                                },
                                "necessary_change": {
                                    **TEXT,
                                    "description": "Smallest requirement, assumption or capability change needed; propose it, do not silently change the task.",
                                },
                            },
                        },
                    ]
                },
            },
        },
    },
}


def failure(error, response=None):
    return FormatError(
        {
            "role": "user",
            "content": (
                "No calls from that response were executed. Invalid finish/tool response: "
                + str(error)[:500]
                + ". Continue work with the available tools, or call finish_attempt alone"
                " to submit your work or report a supported blocker."
            ),
            "extra": {
                "interrupt_type": "FormatError",
                **({"response": response} if response is not None else {}),
            },
        }
    )


def bounded_text(value, bound, field):
    """Report actionable sizes without reflecting arbitrary model text."""
    if isinstance(value, str):
        size = len(value.encode("utf-8"))
        if size > bound:
            raise ValueError(
                f"{field} is {size} UTF-8 bytes; maximum is {bound}. "
                f"Shorten it substantially (aim below {bound // 2} bytes)"
            )
    _string(value, bound, field)


def require_fields(value, fields, label):
    """Name missing contract fields without reflecting untrusted key text."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    expected = set(fields)
    missing = expected - set(value)
    extra = set(value) - expected
    if missing or extra:
        details = []
        if missing:
            details.append("missing: " + ", ".join(sorted(missing)))
        if extra:
            details.append(f"unexpected fields: {len(extra)}")
        raise ValueError(
            f"{label}: "
            + "; ".join(details)
            + ". Required fields: "
            + ", ".join(fields)
        )


def validate(value, history):
    require_fields(
        value,
        ("disposition", "summary", "evidence", "unverified", "blocker"),
        "handoff",
    )
    if value["disposition"] not in ("submitted", "blocked"):
        raise ValueError("Unknown disposition")
    bounded_text(value["summary"], 1000, "summary")
    if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("Handoff exceeds8192 bytes")
    evidence, gaps = value["evidence"], value["unverified"]
    if (
        not isinstance(evidence, list)
        or len(evidence) > 4
        or not isinstance(gaps, list)
        or len(gaps) > 4
    ):
        raise ValueError("At most four evidence and four unverified entries")
    if not evidence and not gaps:
        raise ValueError("Empty evidence requires an explicit unverified explanation")
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
    for gap in gaps:
        bounded_text(gap, 500, "unverified")
    blocker = value["blocker"]
    if value["disposition"] == "submitted":
        if blocker is not None:
            raise ValueError("Submitted requires null blocker")
    else:
        require_fields(blocker, ("category", "argument", "necessary_change"), "blocker")
        if (
            not isinstance(blocker["category"], str)
            or blocker["category"] not in CATEGORIES
        ):
            raise ValueError("Unknown blocker category")
        bounded_text(blocker["argument"], 1000, "argument")
        bounded_text(blocker["necessary_change"], 1000, "necessary_change")
    return value


def parse(raw, history):
    if not isinstance(raw, str) or len(raw.encode()) > MAX_BYTES:
        raise ValueError("Expected at most8192 argument bytes")
    return validate(
        json.loads(raw, object_pairs_hook=_object, parse_constant=_constant), history
    )


def actions(
    message,
    response,
    history,
    *,
    finish_reason,
    edit_file_enabled=False,
    write_file_enabled=False,
    max_calls=4,
):
    """Admission of complete action batch before DefaultAgent executes any action."""
    try:
        calls = message.get("tool_calls")
        if not isinstance(calls, list) or not calls:
            raise ValueError("Return at least one tool call in the tool_calls array")
        if len(calls) > max_calls:
            raise ValueError(
                f"Received {len(calls)} tool calls; maximum per response is {max_calls}. "
                f"Resend at most {max_calls} calls now and issue the rest in a later response"
            )
        seen = set()
        allowed_tools = {"bash", NAME}
        if edit_file_enabled:
            allowed_tools.add("edit_file")
        if write_file_enabled:
            allowed_tools.add("write_file")
        for call in calls:
            if not isinstance(call, dict) or call.get("type") != "function":
                raise ValueError("Expected function tool call")
            identifier = call.get("id")
            function = call.get("function")
            if (
                not isinstance(identifier, str)
                or not identifier
                or len(identifier.encode()) > 256
                or identifier in seen
            ):
                raise ValueError("Invalid/duplicate tool-call ID")
            seen.add(identifier)
            if (
                not isinstance(function, dict)
                or function.get("name") not in allowed_tools
                or not isinstance(function.get("arguments"), str)
            ):
                raise ValueError("Invalid tool name/arguments")
        if any(c["function"]["name"] == NAME for c in calls):
            if len(calls) != 1:
                raise ValueError("Finalization must be the sole action")
            if finish_reason != "tool_calls":
                raise ValueError(
                    "Finalization requires a complete tool_calls response; truncated or unknown stop reasons are not accepted"
                )
            call = calls[0]
            raw = call["function"]["arguments"]
            return [
                {
                    "tool": NAME,
                    "payload": parse(raw, history),
                    "raw_arguments": raw,
                    "tool_call_id": call["id"],
                }
            ]
        edits = any(c["function"]["name"] in ("edit_file", "write_file") for c in calls)
        if edits:
            if finish_reason != "tool_calls":
                raise ValueError("Edits require a complete tool_calls response")
            from edit_file import action as edit_action
            from write_file import action as write_action

            parsed = []
            for call in calls:
                if call["function"]["name"] == "edit_file":
                    parsed.append(edit_action(call))
                elif call["function"]["name"] == "write_file":
                    parsed.append(write_action(call))
                else:
                    parsed.extend(
                        parse_toolcall_actions(
                            [
                                SimpleNamespace(
                                    id=call["id"],
                                    function=SimpleNamespace(**call["function"]),
                                )
                            ],
                            format_error_template="{{ error }} Use the available tools.",
                            template_kwargs={},
                        )
                    )
        else:
            parsed = parse_toolcall_actions(
                [
                    SimpleNamespace(
                        id=c["id"], function=SimpleNamespace(**c["function"])
                    )
                    for c in calls
                ],
                format_error_template="{{ error }} Use bash or finish_attempt.",
                template_kwargs={},
            )
        from spec_blocker import reserved

        for action in parsed:
            if action.get("tool") in ("edit_file", "write_file"):
                continue
            if not isinstance(action["command"], str):
                raise ValueError("Bash command must be text")
            if action["command"].strip() == ECHO or reserved(action["command"]):
                raise ValueError(
                    "This bash command cannot finish the attempt. Call finish_attempt alone"
                )
        return parsed
    except (ValueError, UnicodeError, RecursionError, TypeError, KeyError) as error:
        raise failure(error, response) from error


def envelope(value, history):
    validate(value, history)
    citations = []
    for entry in value["evidence"]:
        if entry["kind"] == "observation":
            identifier = entry["observation_id"]
            record = history.records[identifier]
            # These are trusted attempt-local records; no model-selected filesystem path.
            citations.append(
                {
                    "record": dict(record),
                    "original_visible": history.visible_messages[identifier],
                }
            )
    return {
        "status": "unverified_model_handoff",
        "source": "model",
        "handoff": value,
        "observations": citations,
        "note": "References establish existence, not interpretation or correctness; historical state may be stale.",
    }


def compact_handoff(envelope):
    """Bounded common payload for summaries/UI; full observations stay in the artifact."""
    projection = {
        "status": envelope["status"],
        "source": envelope["source"],
        "handoff": envelope["handoff"],
        "observation_count": len(envelope["observations"]),
        "observations_artifact": "final-handoff.json",
        "note": "Model claims are unverified; full historical observations are attached in the fixed artifact.",
    }
    if "public_interface" in envelope:
        projection["public_interface"] = envelope["public_interface"]
    if len(json.dumps(projection).encode()) > 65536:
        raise ValueError("Compact handoff exceeds summary contribution bound")
    return projection
