"""Opt-in data-only blocked claim; no model-controlled paths or executable fields."""

from mini_bootstrap import FormatError, exceptions
from tool_arguments import load_arguments

COMMAND = "REPORT_SPEC_BLOCKER"
MAX_BYTES = 8192
CATEGORIES = {
    "contradictory_requirements",
    "impossible_computation_model",
    "open_problem",
    "environment_capability_limit",
}
INSTRUCTION = (
    " To stop and report a concrete blocker:"
    " Use one bash call alone with command REPORT_SPEC_BLOCKER followed by one JSON object:"
    ' {"version":1,"category":"contradictory_requirements","reason":"brief explanation",'
    '"evidence":[{"requirement":"exact relevant public clause","observation":"why it blocks the obligation"}],'
    '"necessary_change":"smallest requirement, assumption, or capability change needed"}.'
    " Categories: contradictory_requirements means clauses cannot jointly hold;"
    " impossible_computation_model means a stated obligation is impossible under the stated model;"
    " open_problem means the requested mathematical result is not established, not proof of impossibility;"
    " environment_capability_limit means missing permitted resources or capabilities, not intrinsic impossibility."
    " Include 1-4 evidence entries; reason and necessary_change each at most 1000 UTF-8 bytes,"
    " each requirement at most 500 and observation at most 1000, whole command at most 8192 bytes."
    " This report ends the attempt and consumes one tool call."
    " This adapter command is not executed by a shell. Use literal JSON, without shell quoting or a file path."
    " A blocker report is your unadjudicated claim, never completed coding work or verified correctness."
    " Ordinary difficulty, an unsuccessful implementation, or passing finite samples alone establishes"
    " neither impossibility nor a complete solution. Continue normal coding and submission when feasible."
)


OPEN_PROBLEM_INSTRUCTIONS = {
    "report_blocker": (
        " Open-problem policy: when supported evidence identifies an obligation as a known"
        " open problem, report that blocker rather than attempting to solve the open problem."
        " Difficulty or unfamiliarity alone is not evidence of open status. Quote the relevant"
        " obligation and explain the supported status; do not label it proved impossible."
    ),
    "attempt_within_budget": (
        " Open-problem policy: you may attempt an open-problem obligation within the available"
        " time, token and tool budgets. Distinguish bounded experiments from a general solution;"
        " do not claim a proof from finite test passes. An unresolved supported open obligation"
        " may still be reported as a blocker, never as proved impossible."
    ),
}


class Blocked(exceptions.InterruptAgentFlow):
    """A clean terminal disposition carrying an unadjudicated model claim."""


def reserved(command):
    if not isinstance(command, str):
        return False
    command = command.strip()
    return command == COMMAND or command.startswith(COMMAND + " ")


def _string(value, bound, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")
    if len(value.encode("utf-8")) > bound or any(
        ord(c) < 32 and c not in "\n\t" for c in value
    ):
        raise ValueError(f"{field} exceeds its text limit")


def parse(command):
    """Return a validated claim, or None for an ordinary bash command."""
    if not reserved(command):
        return None
    if len(command.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Blocker command exceeds 8192 bytes")
    claim = load_arguments(command.strip()[len(COMMAND) :].strip())
    if not isinstance(claim, dict) or set(claim) != {
        "version",
        "category",
        "reason",
        "evidence",
        "necessary_change",
    }:
        raise ValueError("Wrong blocker fields")
    if type(claim["version"]) is not int or claim["version"] != 1:
        raise ValueError("Unknown blocker schema version")
    if not isinstance(claim["category"], str) or claim["category"] not in CATEGORIES:
        raise ValueError("Unknown blocker category")
    _string(claim["reason"], 1000, "reason")
    _string(claim["necessary_change"], 1000, "necessary_change")
    evidence = claim["evidence"]
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 4:
        raise ValueError("Need 1-4 evidence entries")
    for entry in evidence:
        if not isinstance(entry, dict) or set(entry) != {"requirement", "observation"}:
            raise ValueError("Wrong evidence fields")
        _string(entry["requirement"], 500, "requirement")
        _string(entry["observation"], 1000, "observation")
    return claim


def format_error(error, response=None):
    extra = {"interrupt_type": "FormatError"}
    if response is not None:
        extra["response"] = response
    return FormatError(
        {
            "role": "user",
            "content": (
                "No calls from that response were executed. Invalid blocker control: "
                + str(error)
                + ". Use REPORT_SPEC_BLOCKER with one bounded JSON claim in a sole bash call;"
                " otherwise continue work with bash."
            ),
            "extra": extra,
        }
    )


def validate_actions(actions, response):
    """Reject a mixed/malformed terminal response before any of its actions execute."""
    candidates = [action for action in actions if reserved(action["command"])]
    if not candidates:
        return
    try:
        if len(actions) != 1:
            raise ValueError("Blocker control requires exactly one tool call")
        parse(candidates[0]["command"])
    except (ValueError, UnicodeError, RecursionError) as error:
        raise format_error(error, response) from error


def finalize_report(report):
    """Opt-in only: finite checks and terminal claims await an independent outer rubric."""
    report["coding_checks_passed"] = report["verified_correctness"]
    report["provisional_coding_success"] = report["success"]
    report["clean_agent_halt"] = (
        report.get("agent_outcome", {}).get("exit_status") in ("Submitted", "Blocked")
        and "agent_error" not in report
        and "cancelled" not in report
        and "unsafe_cleanup" not in report
    )
    report["task_adjudication"] = {
        "status": "pending_outer_rubric",
        "correct": None,
        "authority": "separate trusted evaluator/reviewer; model claim is not a verdict",
    }
    report["verified_correctness"] = False
    report["success"] = False
