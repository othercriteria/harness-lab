"""Bounded execution facts independent of whether Delegate could collect an artifact."""

import json

from delegate_artifacts import digest, read_file

TRIAL_PATH = "experiment/trial-00-delegated-task"


def trial_evidence(run, closure):
    """Read only fixed outer trace paths. Missing records leave the fact unknown."""
    facts = {
        "trial": None,
        "model_request_recorded": None,
        "summary_sha256": None,
        "clean_agent_completion": None,
    }
    if not isinstance(closure, dict) or closure.get("verified") is not True:
        return facts
    if closure.get("not_launched") is True:
        facts["model_request_recorded"] = False
        return facts
    trial = run / TRIAL_PATH
    try:
        wire = read_file(
            run, f"{TRIAL_PATH}/request-001.request.json", limit=1024 * 1024
        )
        request = json.loads(wire)
        if isinstance(request, dict) and isinstance(request.get("messages"), list):
            facts.update(trial=str(trial), model_request_recorded=True)
    except (OSError, ValueError, RecursionError):
        pass
    summary_path = f"{TRIAL_PATH}/summary.json"
    receipts = closure.get("receipts")
    expected = (
        receipts.get(str(run / summary_path)) if isinstance(receipts, dict) else None
    )
    if expected:
        try:
            raw = read_file(run, summary_path, limit=16 * 1024 * 1024)
            if digest(raw) == expected:
                summary = json.loads(raw)
                if isinstance(summary, dict):
                    facts.update(trial=str(trial), summary_sha256=expected)
                    clean = summary.get("clean_agent_completion")
                    if isinstance(clean, bool):
                        facts["clean_agent_completion"] = clean
        except (OSError, ValueError, RecursionError):
            pass
    return facts
