"""Data-only contract for model-authored progress reports.

A progress report is a bounded, unverified assertion plus historical
citations: it names implemented work, claims about checks, and public
requirements still unfinished or unverified. It is never a certification
of correctness or a probability of finishing. Semantic relevance, truth,
and next-action concreteness remain outer review, not mechanical
rejection rules here.

This module is data and validation only: no tool loop, no file I/O, no
scheduling, no termination decisions, no model calls. Standard library
plus the supplied read-only evidence modules only.
"""

import copy
import json

from evidence import validate_evidence
from evidence_contract import bounded_text, require_fields
from progress_values import (
    CHANGE_VALUES,
    CHECKS_MAX_ITEMS,
    CHECK_RESULT_VALUES,
    IMPLEMENTED_MAX_ITEMS,
    PAYLOAD_UTF8_BYTES,
    REMAINING_MAX_ITEMS,
    TEXT_BOUND,
)

REPORT_FIELDS = (
    "change",
    "implemented",
    "checks",
    "remaining",
    "obstacle",
    "next_action",
    "evidence",
)


def schema(evidence_schema):
    """Return a fresh JSON schema for a progress report object.

    The object has exactly the seven required fields and
    additionalProperties=false. The caller-supplied evidence schema is
    deep-copied verbatim under the "evidence" property, including any
    description it already has; it is not mutated and no mutable state is
    shared between returned schemas.
    """
    return {
        "type": "object",
        "description": (
            "Model-authored progress report: unverified assertions and "
            "historical citations, never certification of correctness or "
            "probability of finishing. Total payload must be at most "
            f"{PAYLOAD_UTF8_BYTES} UTF-8 bytes of "
            "json.dumps(value, ensure_ascii=False) with default "
            "separators; that aggregate cap applies even when every "
            "individual field is within its own cap."
        ),
        "required": list(REPORT_FIELDS),
        "additionalProperties": False,
        "properties": {
            "change": {
                "type": "string",
                "enum": list(CHANGE_VALUES),
                "description": (
                    "Task-relevant change since the previous report; on "
                    "the first report, since task start."
                ),
            },
            "implemented": {
                "type": "array",
                "minItems": 0,
                "maxItems": IMPLEMENTED_MAX_ITEMS,
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": TEXT_BOUND,
                },
                "description": (
                    "Actual implementation changes, not test outcomes; "
                    f"0-{IMPLEMENTED_MAX_ITEMS} items, each at most "
                    f"{TEXT_BOUND} characters "
                    f"and {TEXT_BOUND} UTF-8 bytes."
                ),
            },
            "checks": {
                "type": "array",
                "minItems": 0,
                "maxItems": CHECKS_MAX_ITEMS,
                "items": {
                    "type": "object",
                    "required": ["result", "summary"],
                    "additionalProperties": False,
                    "properties": {
                        "result": {
                            "type": "string",
                            "enum": list(CHECK_RESULT_VALUES),
                        },
                        "summary": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": TEXT_BOUND,
                        },
                    },
                },
                "description": (
                    "Model claims about checks, not independently "
                    f"observed facts; 0-{CHECKS_MAX_ITEMS} entries, each "
                    "exactly result "
                    "and summary, summary at most "
                    f"{TEXT_BOUND} characters and {TEXT_BOUND} UTF-8 "
                    "bytes."
                ),
            },
            "remaining": {
                "type": "array",
                "minItems": 0,
                "maxItems": REMAINING_MAX_ITEMS,
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": TEXT_BOUND,
                },
                "description": (
                    "Explicit public requirements still unfinished or "
                    f"unverified; 0-{REMAINING_MAX_ITEMS} items, each at most "
                    f"{TEXT_BOUND} characters and {TEXT_BOUND} UTF-8 "
                    "bytes. Empty is allowed and does not establish "
                    "completion."
                ),
            },
            "obstacle": {
                "type": "string",
                "maxLength": TEXT_BOUND,
                "description": (
                    f"Known obstacle, at most {TEXT_BOUND} characters "
                    f"and {TEXT_BOUND} UTF-8 bytes; exactly the empty "
                    "string means no obstacle known; other "
                    "whitespace-only values are invalid."
                ),
            },
            "next_action": {
                "type": "string",
                "minLength": 1,
                "maxLength": TEXT_BOUND,
                "description": (
                    "One concrete next action; nonempty, at most "
                    f"{TEXT_BOUND} characters and {TEXT_BOUND} UTF-8 "
                    "bytes."
                ),
            },
            "evidence": copy.deepcopy(evidence_schema),
        },
    }


def _require_text(value, bound, field):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    if len(value) > bound:
        raise ValueError(
            f"{field} is {len(value)} characters; maximum is {bound}"
        )
    bounded_text(value, bound, field)


def _validate_text_list(value, bound, max_items, field):
    if not isinstance(value, list) or len(value) > max_items:
        raise ValueError(f"{field} must be an array of at most {max_items}")
    for index, item in enumerate(value):
        _require_text(item, bound, f"{field}[{index}]")


def validate(value, history=None):
    """Validate a progress report; return the original value unchanged.

    Raises ValueError for invalid values. Enforces the exact required
    fields, field types, enum values, array counts, all text limits and
    control-character rules via evidence_contract.bounded_text, and the
    attempt-local evidence citations via evidence.validate_evidence.
    The whole-report byte cap applies to the serialized payload even
    when every individual field is within its own cap. No mutation,
    normalization, or inferred truth/freshness; reference validity does
    not establish entailment.
    """
    require_fields(value, REPORT_FIELDS, "progress report")

    change = value["change"]
    if not isinstance(change, str) or change not in CHANGE_VALUES:
        raise ValueError(
            "change must be one of: " + ", ".join(CHANGE_VALUES)
        )

    _validate_text_list(
        value["implemented"], TEXT_BOUND, IMPLEMENTED_MAX_ITEMS, "implemented"
    )

    checks = value["checks"]
    if not isinstance(checks, list) or len(checks) > CHECKS_MAX_ITEMS:
        raise ValueError(
            f"checks must be an array of at most {CHECKS_MAX_ITEMS}"
        )
    for index, entry in enumerate(checks):
        label = f"checks[{index}]"
        require_fields(entry, ("result", "summary"), label)
        result = entry["result"]
        if not isinstance(result, str) or result not in CHECK_RESULT_VALUES:
            raise ValueError(
                f"{label}.result must be one of: "
                + ", ".join(CHECK_RESULT_VALUES)
            )
        _require_text(entry["summary"], TEXT_BOUND, f"{label}.summary")

    _validate_text_list(
        value["remaining"], TEXT_BOUND, REMAINING_MAX_ITEMS, "remaining"
    )

    obstacle = value["obstacle"]
    if not isinstance(obstacle, str):
        raise ValueError("obstacle must be text")
    if obstacle != "":
        _require_text(obstacle, TEXT_BOUND, "obstacle")

    _require_text(value["next_action"], TEXT_BOUND, "next_action")

    validate_evidence(value["evidence"], history)

    payload_bytes = len(
        json.dumps(value, ensure_ascii=False).encode("utf-8")
    )
    if payload_bytes > PAYLOAD_UTF8_BYTES:
        raise ValueError(
            f"progress report is {payload_bytes} UTF-8 bytes; maximum "
            f"is {PAYLOAD_UTF8_BYTES}. Shorten it substantially (aim "
            f"below {PAYLOAD_UTF8_BYTES // 2} bytes)"
        )

    return value
