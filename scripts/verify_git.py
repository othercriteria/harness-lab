"""Independent isolated graph, canonical tests and external behavior for Git tasks."""

import base64
import hashlib
import json
import shutil
import time
import zlib
from pathlib import Path

from behavioral_grade import require_cleanup
from control import deadline
from git_task import specification
from sandbox import write_json

GRADE = """
import io,json,sys,unittest
sys.path.insert(0, '/workspace')
suite=unittest.defaultTestLoader.discover('/evaluation', pattern='test_*.py')
log=io.StringIO()
r=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
print(json.dumps(dict(passed=r.wasSuccessful(),tests_run=r.testsRun,
                     skipped=len(r.skipped),failures=len(r.failures),
                     errors=len(r.errors),log=log.getvalue())))
"""


def verify(runtime, workspace, task, output, remaining):
    runtime = runtime.for_evaluation()
    spec = specification(task)
    metadata = json.loads((task / "task.json").read_text())
    directory = output / "git-verification"
    directory.mkdir()
    evaluation = directory / "reader"
    evaluation.mkdir()
    write_json(evaluation / "spec.json", spec)
    shutil.copyfile(Path(__file__).with_name("git_export.py"), evaluation / "export.py")
    end = time.monotonic() + remaining
    report = {
        "passed": False,
        "branches": {},
        "behavioral": {"passed": False},
        "delivery": {"passed": False, "errors": ["Git export unavailable"]},
        "limitations": [
            "Finite canonical/external coverage; source and handoff review still required.",
            "Canonical in-process test reports are not adversarial score-forgery protection.",
        ],
    }

    def run(source, argv, prefix, mount):
        seconds = min(10, end - time.monotonic())
        with deadline(seconds):
            try:
                result, _ = runtime.sandbox(
                    source,
                    {"mode": "grade", "argv": argv, "timeout": seconds},
                    prefix,
                    evaluation=(mount, "/evaluation"),
                )
            finally:
                require_cleanup(prefix, "Git evaluator")
        return result

    exported = run(
        workspace,
        ["/bin/python3", "-I", "-S", "/evaluation/export.py"],
        directory / "export",
        evaluation,
    )
    report["graph_transport"] = exported
    if not exported.get("ok"):
        report["reason"] = "Submitted Git graph/worktree rejected"
        return report
    decoder = zlib.decompressobj()
    raw = decoder.decompress(
        base64.b64decode(exported["stdout"], validate=False), 64 * 1024 * 1024
    )
    if decoder.unconsumed_tail or not decoder.eof:
        raise ValueError("Oversized or incomplete trusted Git export")
    data = json.loads(raw)
    if data.get("passed") is not True or set(data["branches"]) != set(spec["branches"]):
        raise ValueError("Invalid trusted Git export")
    report["checked_out"] = data["checked_out"]
    report["delivery"] = data["delivery"]
    # Full export stays in immutable raw transport receipt; keep summary bounded.
    report["graph_transport"] = {k: v for k, v in exported.items() if k != "stdout"}
    behavior = []
    for name, branch in data["branches"].items():
        label = name.split("/")[-1]
        root = directory / label
        source, tests = root / "tree", root / "tests"
        source.mkdir(parents=True)
        tests.mkdir()
        for relative, info in branch["files"].items():
            target = source / relative
            if target.is_absolute() and not target.resolve().is_relative_to(
                source.resolve()
            ):
                raise ValueError("Exported path escaped branch tree")
            target.parent.mkdir(parents=True, exist_ok=True)
            content = base64.b64decode(data["blobs"][info["sha256"]], validate=True)
            if hashlib.sha256(content).hexdigest() != info["sha256"]:
                raise ValueError("Exported blob digest mismatch")
            target.write_bytes(content)
            target.chmod(0o755 if info["mode"] == "100755" else 0o644)
        for path in (task / "private" / label).glob("test_*.py"):
            shutil.copyfile(path, tests / path.name)
        result = run(
            source, ["/bin/python3", "-I", "-S", "-c", GRADE], root / "canonical", tests
        )
        try:
            decoded = json.loads(result["stdout"])
        except (ValueError, KeyError):
            decoded = {}
        expected = metadata["test_counts"][label]
        passed = (
            result.get("ok") is True
            and decoded.get("passed") is True
            and type(decoded.get("tests_run")) is int
            and decoded["tests_run"] == expected
            and all(
                type(decoded.get(k)) is int and decoded[k] == 0
                for k in ("skipped", "failures", "errors")
            )
        )
        report["branches"][name] = {
            "commit": branch["commit"],
            "base": branch["base"],
            "changed_files": branch["changed_files"],
            "passed": passed,
            "tests": decoded,
            "transport": result,
        }
        # This probe contains inputs/observation code only; comparisons stay outside.
        probe = task / "private" / label / "probe.py"
        if not probe.is_file():
            probe = task / "private" / "probe.py"
        probe_mount = root / "probe"
        probe_mount.mkdir()
        shutil.copyfile(probe, probe_mount / "probe.py")
        observed = run(
            source,
            ["/bin/python3", "-I", "-S", "/evaluation/probe.py"],
            root / "behavior",
            probe_mount,
        )
        expected_behavior = json.loads(
            (task / "private" / label / "expected.json").read_text()
        )
        try:
            actual = json.loads(observed.get("stdout", ""))
        except ValueError:
            actual = None
        behavior.append(
            {
                "branch": name,
                "passed": observed.get("ok") is True and actual == expected_behavior,
                "expected": expected_behavior,
                "observed": actual,
                "transport": observed,
            }
        )
    report["passed"] = bool(report["branches"]) and all(
        row["passed"] for row in report["branches"].values()
    )
    report["behavioral"] = {
        "passed": all(row["passed"] for row in behavior),
        "checks": behavior,
    }
    write_json(directory / "summary.json", report)
    return report
