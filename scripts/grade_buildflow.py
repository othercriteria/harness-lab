"""Independent CLI/filesystem checks supplement build-flow's full canonical suite.

These checks judge output, saved receipts and real command side effects outside
the candidate process. They do not independently prove callback or hook internals.
"""

import hashlib
import json

from grade_migrations import _same


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


def fingerprints(steps, contents):
    result = {}
    pending = {s["id"]: s for s in steps}
    while pending:
        name = min(
            n for n, s in pending.items() if all(d in result for d in s.get("deps", []))
        )
        step = pending.pop(name)
        payload = {
            "id": name,
            "command": step["command"],
            "deps": [[d, result[d]] for d in sorted(step.get("deps", []))],
            "inputs": [
                [p, hashlib.sha256(contents[p]).hexdigest()]
                for p in sorted(step.get("inputs", []))
            ],
        }
        result[name] = hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode()
        ).hexdigest()
    return result


def command(name, token, failure=False):
    code = (
        "from pathlib import Path; import sys; "
        f"p=Path('executed'); p.open('a').write({(name + ':' + token + chr(10))!r}); "
        "print('command chatter'); print('stderr chatter',file=sys.stderr); "
        f"sys.exit({7 if failure else 0})"
    )
    return ["python", "-c", code]


def check(gate):
    token = gate.token()
    source = ("binary:" + gate.token()).encode() + b"\x00\xff"
    steps = [
        {"id": "c", "command": command("c", token), "deps": ["a"]},
        {"id": "b", "command": command("b", token)},
        {"id": "a", "command": command("a", token), "inputs": ["input.bin"]},
    ]
    setup = {
        "probe/spec.json": encoded({"version": 1, "steps": steps}),
        "probe/work/input.bin": source,
    }
    cli = "python -m buildflow probe/spec.json probe/work probe/state.json"

    def observe(name, probe, expected=None, code=0, error=False):
        result = probe.result
        stdout, stderr = result.get("stdout", ""), result.get("stderr", "")
        try:
            actual = gate.json(probe) if not error else None
        except (ValueError, TypeError):
            actual = None
        valid = (
            type(result.get("returncode")) is int
            and result["returncode"] == code
            and result.get("stopped_by") is None
        )
        valid = valid and (
            stdout == "" and bool(stderr.strip())
            if error
            else stderr == "" and _same(actual, expected)
        )
        gate.record(
            name,
            valid,
            {
                "returncode": result.get("returncode"),
                "stdout": stdout,
                "stderr": stderr,
                "actual": actual,
                "expected": expected,
            },
        )

    def artifact(name, probe, path, expected, json_value=False):
        try:
            raw = gate.read(probe, path)
            actual = json.loads(raw) if json_value else raw.decode()
            valid = _same(actual, expected)
        except (OSError, ValueError):
            actual, valid = None, False
        gate.record(name, valid, {"path": path, "actual": actual, "expected": expected})

    def state(receipts):
        return {"version": 1, "completed": receipts}

    def report(order, statuses, receipts):
        return {
            "order": order,
            "statuses": statuses,
            "errors": {},
            "state": state(receipts),
        }

    fp = fingerprints(steps, {"input.bin": source})
    rows = [
        {
            "id": name,
            "command": s["command"],
            "deps": sorted(s.get("deps", [])),
            "fingerprint": fp[name],
            "cached": False,
        }
        for name in fp
        for s in steps
        if s["id"] == name
    ]
    dry = gate.case("build_dry_run", setup, cli + " --dry-run")
    observe("dry_plan", dry, {"plan": rows})
    gate.record(
        "dry_no_side_effects",
        gate.absent(dry, "probe/state.json")
        and gate.absent(dry, "probe/work/executed"),
        {},
    )
    first = gate.step(dry, cli)
    observe("initial_run", first, report(list(fp), dict.fromkeys(fp, "succeeded"), fp))
    artifact("initial_receipts", first, "probe/state.json", state(fp), True)
    log = "".join(name + ":" + token + "\n" for name in fp)
    artifact("initial_commands", first, "probe/work/executed", log)
    cached = gate.step(first, cli)
    observe("cached_run", cached, report(list(fp), dict.fromkeys(fp, "cached"), fp))
    artifact("cached_commands_not_repeated", cached, "probe/work/executed", log)
    updated = source + b"changed"
    changed = gate.step(cached, cli, {"probe/work/input.bin": updated})
    next_fp = fingerprints(steps, {"input.bin": updated})
    observe(
        "transitive_invalidation",
        changed,
        report(list(fp), {"a": "succeeded", "b": "cached", "c": "succeeded"}, next_fp),
    )
    artifact("invalidated_receipts", changed, "probe/state.json", state(next_fp), True)
    artifact(
        "only_invalidated_commands",
        changed,
        "probe/work/executed",
        log + "a:" + token + "\nc:" + token + "\n",
    )

    failed_steps = [
        {"id": "a", "command": command("a", token)},
        {"id": "b", "command": command("b", token, True)},
        {"id": "c", "command": command("c", token), "deps": ["b"]},
        {"id": "d", "command": command("d", token)},
    ]
    failure_setup = {
        **setup,
        "probe/spec.json": encoded({"version": 1, "steps": failed_steps}),
    }
    failure_fp = fingerprints(failed_steps, {})
    for keep_going in (False, True):
        name = "keep_going" if keep_going else "fail_fast"
        probe = gate.case(
            name, failure_setup, cli + (" --keep-going" if keep_going else "")
        )
        try:
            actual = gate.json(probe)
        except (ValueError, TypeError):
            actual = None
        receipts = {"a": failure_fp["a"]}
        if keep_going:
            receipts["d"] = failure_fp["d"]
        expected = report(
            ["a", "b", "c", "d"],
            {
                "a": "succeeded",
                "b": "failed",
                "c": "blocked",
                "d": "succeeded" if keep_going else "not_run",
            },
            receipts,
        )
        errors = actual.get("errors") if isinstance(actual, dict) else None
        diagnostic = (
            isinstance(errors, dict)
            and set(errors) == {"b"}
            and isinstance(errors["b"], str)
            and bool(errors["b"].strip())
        )
        if diagnostic:
            expected["errors"] = errors
        observe(name + "_report", probe, expected, code=1)
        gate.record(name + "_diagnostic", diagnostic, {"errors": errors})
        artifact(
            name + "_partial_receipts", probe, "probe/state.json", state(receipts), True
        )
        artifact(
            name + "_commands",
            probe,
            "probe/work/executed",
            "a:"
            + token
            + "\nb:"
            + token
            + "\n"
            + ("d:" + token + "\n" if keep_going else ""),
        )

    for name, modifications in (
        (
            "invalid_spec",
            {"probe/spec.json": encoded({"version": True, "steps": steps})},
        ),
        (
            "invalid_state",
            {"probe/state.json": encoded({"version": True, "completed": {}})},
        ),
    ):
        probe = gate.case(name, {**setup, **modifications}, cli)
        observe(name, probe, code=2, error=True)
        gate.record(
            name + "_no_commands", gate.absent(probe, "probe/work/executed"), {}
        )
        for path, content in modifications.items():
            artifact(name + "_input_preserved", probe, path, content.decode())
    failed_save = gate.case(
        "save_failure",
        setup,
        "python -m buildflow probe/spec.json probe/work probe/missing/state.json",
    )
    observe("save_failure_no_success_output", failed_save, code=2, error=True)
    gate.record(
        "save_failure_no_parent_created", gate.absent(failed_save, "probe/missing"), {}
    )
