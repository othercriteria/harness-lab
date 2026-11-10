from .planner import plan
from .spec import parse_spec
from .state import validate_state


def run(spec, root, execute, previous=None, targets=None, keep_going=False):
    planned = plan(spec, root, previous, targets)
    steps = parse_spec(spec)
    old = validate_state(
        {"version": 1, "completed": {}} if previous is None else previous
    )
    chosen = {p["id"] for p in planned}
    completed = {
        k: v for k, v in old["completed"].items() if k in steps and k not in chosen
    }
    statuses, errors = {}, {}
    stopped = False
    for step in planned:
        name = step["id"]
        if any(statuses[d] in ("failed", "blocked", "not_run") for d in step["deps"]):
            statuses[name] = "blocked"
        elif stopped:
            statuses[name] = "not_run"
        elif step["cached"]:
            statuses[name] = "cached"
            completed[name] = step["fingerprint"]
        else:
            try:
                code = execute(name, list(step["command"]))
                if type(code) is not int or code != 0:
                    raise RuntimeError(f"command failed: {code!r}")
            except Exception as error:
                statuses[name] = "failed"
                errors[name] = str(error) or type(error).__name__
                stopped = not keep_going
            else:
                statuses[name] = "succeeded"
                completed[name] = step["fingerprint"]
    return {
        "order": [p["id"] for p in planned],
        "statuses": statuses,
        "errors": errors,
        "state": {"version": 1, "completed": completed},
    }
