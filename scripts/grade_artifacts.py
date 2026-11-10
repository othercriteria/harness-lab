"""External build artifact checks: actual files, execution logs and receipt bytes.

Expected values stay in this outer controller. Candidate Python is only run via
Gate in disposable sandboxes. API aliasing/path/hook assertions remain canonical.
"""

import hashlib
import json

from grade_buildflow import encoded
from grade_migrations import _same


def digest(data):
    return hashlib.sha256(data).hexdigest()


def receipts(steps, contents):
    pending = {s["id"]: s for s in steps}
    result = {}
    while pending:
        name = min(
            n for n, s in pending.items() if all(d in result for d in s.get("deps", []))
        )
        step = pending.pop(name)
        payload = {
            "id": name,
            "command": step["command"],
            "deps": [
                [d, result[d]["fingerprint"]] for d in sorted(step.get("deps", []))
            ],
            "inputs": [
                [p, digest(contents[p])] for p in sorted(step.get("inputs", []))
            ],
            "outputs": sorted(step.get("outputs", [])),
        }
        result[name] = {
            "fingerprint": digest(
                json.dumps(
                    payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
                ).encode()
            ),
            "outputs": {p: digest(contents[p]) for p in step.get("outputs", [])},
        }
    return result


def check(gate):
    token = gate.token()
    source = ("source:" + gate.token()).encode() + b"\x00\xff"
    other = ("other:" + gate.token()).encode()

    def command(name, source_path, output, suffix):
        data = f"Path({source_path!r}).read_bytes()" if source_path else repr(other)
        code = (
            "from pathlib import Path; import sys; Path('out').mkdir(exist_ok=True); "
            f"Path({output!r}).write_bytes({data}+{suffix!r}); "
            f"Path('log').open('a').write({(name + ':' + token + chr(10))!r}); "
            "print('chatter'); print('stderr chatter',file=sys.stderr)"
        )
        return ["python", "-c", code]

    steps = [
        {
            "id": "a",
            "command": command("a", "source", "out/a", b"A"),
            "inputs": ["source"],
            "outputs": ["out/a"],
        },
        {
            "id": "b",
            "command": command("b", "out/a", "out/b", b"B"),
            "deps": ["a"],
            "inputs": ["out/a"],
            "outputs": ["out/b"],
        },
        {"id": "c", "command": command("c", None, "out/c", b""), "outputs": ["out/c"]},
    ]
    setup = {
        "probe/spec.json": encoded({"version": 1, "steps": steps}),
        "probe/work/source": source,
    }
    cli = "python -m buildflow probe/spec.json probe/work probe/state.json"

    def state(completed):
        return {"version": 2, "completed": completed}

    def report(statuses, completed):
        return {
            "order": list(statuses),
            "statuses": statuses,
            "errors": {},
            "state": state(completed),
        }

    def observe(name, probe, expected, code=0, failed=None):
        try:
            actual = gate.json(probe)
        except (ValueError, TypeError):
            actual = None
        if failed is not None:
            errors = actual.get("errors") if isinstance(actual, dict) else None
            valid = (
                isinstance(errors, dict)
                and set(errors) == set(failed)
                and all(isinstance(v, str) and v.strip() for v in errors.values())
            )
            gate.record(name + "_diagnostics", valid, {"actual": errors})
            if valid:
                expected = {**expected, "errors": errors}
        valid = (
            type(probe.result.get("returncode")) is int
            and probe.result["returncode"] == code
            and not probe.result.get("stderr")
            and probe.result.get("stopped_by") is None
            and _same(actual, expected)
        )
        gate.record(
            name,
            valid,
            {
                "actual": actual,
                "expected": expected,
                "returncode": probe.result.get("returncode"),
                "stderr": probe.result.get("stderr"),
            },
        )

    def artifact(name, probe, path, expected, json_value=False):
        try:
            raw = gate.read(probe, path)
            actual = json.loads(raw) if json_value else raw.hex()
            value = expected if json_value else expected.hex()
            valid = _same(actual, value)
        except (ValueError, OSError):
            actual = None
            value = expected if json_value else expected.hex()
            valid = False
        gate.record(name, valid, {"path": path, "actual": actual, "expected": value})

    contents = {
        "source": source,
        "out/a": source + b"A",
        "out/b": source + b"AB",
        "out/c": other,
    }
    expected = receipts(steps, contents)
    rows = [
        {
            "id": s["id"],
            "deps": s.get("deps", []),
            "command": s["command"],
            "outputs": s["outputs"],
            "fingerprint": None if s["id"] == "b" else expected[s["id"]]["fingerprint"],
            "disposition": "deferred" if s["id"] == "b" else "run",
        }
        for s in steps
    ]
    dry = gate.case("dry_missing_generated", setup, cli + " --dry-run")
    observe("dry_plan", dry, {"plan": rows})
    gate.record(
        "dry_no_effects",
        gate.absent(dry, "probe/state.json")
        and gate.absent(dry, "probe/work/out")
        and gate.absent(dry, "probe/work/log"),
        {},
    )
    first = gate.step(dry, cli)
    observe("first", first, report(dict.fromkeys(expected, "succeeded"), expected))
    artifact("first_receipts", first, "probe/state.json", state(expected), True)
    for p in ["out/a", "out/b", "out/c"]:
        artifact("first_" + p, first, "probe/work/" + p, contents[p])
    log = "".join(n + ":" + token + "\n" for n in expected).encode()
    artifact("first_log", first, "probe/work/log", log)
    cached = gate.step(first, cli)
    observe("cached", cached, report(dict.fromkeys(expected, "cached"), expected))
    artifact("cached_log", cached, "probe/work/log", log)
    repaired = gate.step(cached, "rm probe/work/out/a && " + cli)
    observe(
        "repair_identical",
        repaired,
        report({"a": "succeeded", "b": "cached", "c": "cached"}, expected),
    )
    log += ("a:" + token + "\n").encode()
    artifact("repair_log", repaired, "probe/work/log", log)
    artifact("repair_bytes", repaired, "probe/work/out/a", contents["out/a"])
    # Same-length tampering with preserved mtime must still invalidate content.
    tamper = "python -c \"import os; from pathlib import Path; p=Path('probe/work/out/a'); s=p.stat(); p.write_bytes(b'x'*s.st_size); os.utime(p,ns=(s.st_atime_ns,s.st_mtime_ns))\" && "
    tampered = gate.step(repaired, tamper + cli)
    observe(
        "mtime_is_not_proof",
        tampered,
        report({"a": "succeeded", "b": "cached", "c": "cached"}, expected),
    )
    log += ("a:" + token + "\n").encode()
    artifact("tamper_log", tampered, "probe/work/log", log)
    new_source = source + b"new"
    updated_contents = {
        **contents,
        "source": new_source,
        "out/a": new_source + b"A",
        "out/b": new_source + b"AB",
    }
    updated = receipts(steps, updated_contents)
    changed = gate.step(tampered, cli, {"probe/work/source": new_source})
    observe(
        "source_change",
        changed,
        report({"a": "succeeded", "b": "succeeded", "c": "cached"}, updated),
    )
    log += ("a:" + token + "\nb:" + token + "\n").encode()
    artifact("change_log", changed, "probe/work/log", log)
    artifact("change_output", changed, "probe/work/out/b", updated_contents["out/b"])
    artifact("change_receipts", changed, "probe/state.json", state(updated), True)
    leaf = gate.step(changed, cli, {"probe/work/out/b": b"tampered"})
    observe(
        "leaf_only",
        leaf,
        report({"a": "cached", "b": "succeeded", "c": "cached"}, updated),
    )
    log += ("b:" + token + "\n").encode()
    artifact("leaf_log", leaf, "probe/work/log", log)
    artifact("leaf_bytes", leaf, "probe/work/out/b", updated_contents["out/b"])
    target = gate.case("targeted", setup, cli + " --target b")
    observe(
        "targeted",
        target,
        report(
            {"a": "succeeded", "b": "succeeded"}, {n: expected[n] for n in ("a", "b")}
        ),
    )
    gate.record(
        "target_no_independent_artifact", gate.absent(target, "probe/work/out/c"), {}
    )
    # Legacy recipe hashes plus existing output files still confer no reuse.
    legacy_setup = {
        **setup,
        "probe/state.json": encoded(
            {
                "version": 1,
                "completed": {n: r["fingerprint"] for n, r in expected.items()},
            }
        ),
        **{"probe/work/" + p: v for p, v in contents.items() if p.startswith("out/")},
    }
    legacy = gate.case("legacy_cold", legacy_setup, cli)
    observe("legacy", legacy, report(dict.fromkeys(expected, "succeeded"), expected))
    artifact(
        "legacy_log",
        legacy,
        "probe/work/log",
        "".join(n + ":" + token + "\n" for n in expected).encode(),
    )
    failure_steps = [
        {**steps[0], "command": ["python", "-c", "pass"]},
        steps[1],
        steps[2],
    ]
    failure_setup = {
        **setup,
        "probe/spec.json": encoded({"version": 1, "steps": failure_steps}),
        "probe/state.json": encoded(state(expected)),
    }
    for keep in (False, True):
        name = "missing_output_keep" if keep else "missing_output_stop"
        probe = gate.case(name, failure_setup, cli + (" --keep-going" if keep else ""))
        statuses = {
            "a": "failed",
            "b": "blocked",
            "c": "succeeded" if keep else "not_run",
        }
        completed = {"c": expected["c"]} if keep else {}
        observe(name, probe, report(statuses, completed), code=1, failed=["a"])
        artifact(name + "_receipts", probe, "probe/state.json", state(completed), True)
        gate.record(name + "_no_consumer", gate.absent(probe, "probe/work/out/b"), {})
