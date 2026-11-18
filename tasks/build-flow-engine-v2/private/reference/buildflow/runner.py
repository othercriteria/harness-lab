from .planner import fingerprint, output_hashes, prepare, reusable


def run(spec, root, execute, previous=None, targets=None, keep_going=False):
    steps, root, old, order = prepare(spec, root, previous, targets)
    completed = {
        n: r for n, r in old["completed"].items() if n in steps and n not in order
    }
    statuses, errors, fingerprints = {}, {}, {}
    stopped = False
    for name in order:
        step = steps[name]
        if any(statuses[d] in ("failed", "blocked", "not_run") for d in step["deps"]):
            statuses[name] = "blocked"
        elif stopped:
            statuses[name] = "not_run"
        else:
            try:
                digest = fingerprint(step, root, fingerprints)
                cached = reusable(step, root, digest, old)
                if not cached:
                    code = execute(name, list(step["command"]))
                    if type(code) is not int or code != 0:
                        raise RuntimeError(f"command failed: {code!r}")
                outputs = output_hashes(step, root)
            except Exception as error:
                statuses[name] = "failed"
                errors[name] = str(error) or type(error).__name__
                stopped = not keep_going
            else:
                statuses[name] = "cached" if cached else "succeeded"
                fingerprints[name] = digest
                completed[name] = {"fingerprint": digest, "outputs": outputs}
    return {
        "order": order,
        "statuses": statuses,
        "errors": errors,
        "state": {"version": 2, "completed": completed},
    }
