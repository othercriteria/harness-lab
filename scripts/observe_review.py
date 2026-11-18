"""Display the outcome of a rejected, already bound trial review."""


def rejected_trial_label(summary, receipt):
    if not receipt["source_accepted"]:
        return (
            "source rejected / handoff accepted"
            if receipt["handoff_accepted"]
            else "source and handoff rejected"
        )
    if receipt["handoff_accepted"]:
        return "trial failed / source and handoff accepted"

    error = summary.get("agent_error")
    outcome = summary.get("agent_outcome")
    exit_status = outcome.get("exit_status") if isinstance(outcome, dict) else None
    no_submission = outcome is None or (
        isinstance(exit_status, str) and exit_status not in ("Submitted", "Blocked")
    )
    if (
        "final_handoff" in summary
        and summary["final_handoff"] is None
        and summary.get("clean_agent_completion") is False
        and isinstance(error, dict)
        and error.get("type") == "DeadlineExceeded"
        and error.get("message") == "Whole-stage wall deadline expired"
        and no_submission
    ):
        return "source accepted / handoff missing at timeout"
    return "source accepted / handoff rejected"
