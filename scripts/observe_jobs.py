"""Read-only delegated-job projection; no control or application endpoints."""

import hashlib
import json
import re

from delegate_artifacts import read_file
from delegate_job import RUNS, STORE, TERMINAL, job_path, read, result_envelope, status


def review_label(run_name, store=STORE):
    """Small list/detail projection, bound to the reviewed artifact, not test scores."""
    match = re.fullmatch(r"delegate-([a-f0-9]{32})", run_name)
    if not match:
        return None
    root = job_path(match[1], store)
    if not (root / "review.json").exists():
        return None
    try:
        state = json.loads(read_file(root, "state.json", limit=1024 * 1024))
        raw = read_file(root, "review.json", limit=1024 * 1024)
        review = json.loads(raw)
        kind = review.get("artifact", "artifact")
        if (
            review.get("job_id") != match[1]
            or not state.get("package_id")
            or review.get("package_id") != state["package_id"]
            or kind not in {"artifact", "reviewed-artifact"}
            or review.get("artifact_sha256") != hashlib.sha256(
                read_file(root, kind + "/artifact.json", limit=4 * 1024 * 1024)
            ).hexdigest()
        ):
            return "outer review needs reconciliation"
        decision = review.get("decision")
        label = {
            "accepted": "outer review accepted",
            "accepted_with_repairs": "outer review accepted with repairs",
            "rejected": "outer review rejected",
        }.get(decision)
        if label is None:
            return "outer review needs reconciliation"
        if (root / "application.json").exists():
            application = json.loads(read_file(root, "application.json", limit=1024 * 1024))
            if (
                decision in {"accepted", "accepted_with_repairs"}
                and application.get("job_id") == match[1]
                and application.get("review_sha256") == hashlib.sha256(raw).hexdigest()
                and application.get("artifact_sha256") == review["artifact_sha256"]
                and application.get("state") == "applied"
                and application.get("applied") is True
            ):
                label += " · applied"
        return label
    except (OSError, ValueError, TypeError, AttributeError):
        return "outer review needs reconciliation"


def projection(run_name, store=STORE, runs=RUNS):
    match = re.fullmatch(r"delegate-([a-f0-9]{32})", run_name)
    if not match:
        return None
    identifier = match[1]
    root = job_path(identifier, store)
    if not (root / "state.json").exists():
        return None

    def optional(name):
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Job evidence outside registry")
        return read(path) if path.exists() else None

    events = sorted((root / "events").glob("*.json"))
    result = result_envelope(root, runs)
    record = status(identifier, store)
    review = optional("review.json")
    applied = optional("application.json")
    return {
        "job_id": identifier,
        "label": record["label"],
        "state": record,
        "result": result,
        "result_provisional": result is not None and record["state"] not in TERMINAL,
        "outer_review": review,
        "classification": optional("classification.json"),
        "application": applied,
        "events": [read(p) for p in events[-256:]],
        "event_count": len(events),
        "qualification": "Execution, model claims, independent checks, outer acceptance and application are separate. A completed job is not an accepted patch.",
    }
