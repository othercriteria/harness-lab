from .planner import plan


def run(spec, root, execute, previous=None, targets=None, keep_going=False):
    planned = plan(spec, root, previous, targets)
    statuses, completed, errors = {}, {}, {}
    for step in planned:
        code = execute(step["id"], step["command"])
        statuses[step["id"]] = "succeeded" if code == 0 else "failed"
        if code == 0:
            completed[step["id"]] = step["fingerprint"]
    return {
        "order": [s["id"] for s in planned],
        "statuses": statuses,
        "errors": errors,
        "state": {"version": 2, "completed": completed},
    }
