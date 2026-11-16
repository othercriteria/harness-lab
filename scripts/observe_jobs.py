"""Read-only delegated-job projection; no control or application endpoints."""

import re

from delegate_job import STORE, TERMINAL, job_path, read, status


def projection(run_name, store=STORE):
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
    result = optional("result.json")
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
