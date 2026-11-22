"""Verify which candidate the evaluator sees and what its results authorize."""

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import delegate_artifacts as artifacts
import delegate_verify


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def identity(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


class RecordingRuntime:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []

    def sandbox(self, candidate, spec, output, evaluation):
        self.calls.append((candidate, spec, output, evaluation))
        return next(self.outcomes), {}


def check(name):
    return {"name": name, "argv": ["/bin/python3", "-V"], "timeout": 5}


class DelegateVerifyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        base = {"tool": b"v1", "remove": b"obsolete", "keep": b"unchanged"}
        for name, data in base.items():
            (self.repo / name).write_bytes(data)
        (self.repo / "tool").chmod(0o755)

        self.task = root / "task"
        self.private = self.task / "private"
        self.private.mkdir(parents=True)
        (self.task / "public").mkdir()
        brief = b"Delegated brief\n"
        (self.task / "public/task.md").write_bytes(brief)
        snapshot = self.private / "snapshot"
        artifacts.create_snapshot(
            self.repo, list(base), ["tool", "remove", "docs/new"], snapshot
        )
        self.workspace = root / "workspace"
        shutil.copytree(snapshot / "public", self.workspace)
        (self.workspace / "task.md").write_bytes(brief)
        self.output = root / "output"

    def verify(self, checks, outcomes):
        (self.private / "checks.json").write_text(
            json.dumps({"version": 1, "checks": checks})
        )
        runtime = RecordingRuntime(outcomes)
        result = delegate_verify.verify(
            runtime, self.workspace, self.task, self.output, 120
        )
        return runtime.calls, result

    def test_evaluator_receives_the_sealed_submission(self):
        (self.workspace / "tool").write_bytes(b"v2")
        (self.workspace / "remove").unlink()
        (self.workspace / "docs").mkdir()
        (self.workspace / "docs/new").write_bytes(b"added")
        calls, report = self.verify([check("version")], [{"ok": True}])
        [(candidate, spec, _, evaluation)] = calls
        self.assertEqual(
            spec, {"mode": "grade", "argv": ["/bin/python3", "-V"], "timeout": 5}
        )
        self.assertEqual(evaluation, (self.private, "/evaluation"))
        self.assertNotEqual(candidate.resolve(), self.workspace.resolve())
        (self.workspace / "tool").write_bytes(b"changed after verification")
        observed = {
            path.relative_to(candidate).as_posix(): (
                path.read_bytes(),
                path.stat().st_mode & 0o111,
            )
            for path in candidate.rglob("*")
            if path.is_file()
        }
        expected = {
            "tool": (b"v2", 0o111),
            "keep": (b"unchanged", 0),
            "docs/new": (b"added", 0),
        }
        self.assertEqual(observed, expected)
        self.assertEqual(
            report["sealed_candidate_sha256"],
            identity(
                {
                    name: {"sha256": sha256(data), "executable_bits": bits}
                    for name, (data, bits) in expected.items()
                }
            ),
        )
        artifact = json.loads(
            (self.output / "delegated-artifact/artifact.json").read_bytes()
        )
        self.assertEqual(report["artifact_sha256"], identity(artifact))

    def test_empty_plan_leaves_verification_unknown(self):
        calls, report = self.verify([], [])
        self.assertEqual(calls, [])
        self.assertEqual(report["checks"], [])
        self.assertIsNone(report["passed"])

    def test_mixed_results_preserve_each_transport_and_fail_overall(self):
        names = ["passing", "failing", "missing-status"]
        outcomes = [{"ok": True}, {"ok": False, "error": "boom"}, {}]
        calls, report = self.verify([check(name) for name in names], outcomes)
        self.assertEqual(len({output for _, _, output, _ in calls}), len(names))
        self.assertEqual(
            report["checks"],
            [
                {"name": name, "passed": passed, "transport": result}
                for name, passed, result in zip(
                    names, (True, False, False), outcomes, strict=True
                )
            ],
        )
        self.assertIs(report["passed"], False)

    def test_successful_checks_still_require_outer_review(self):
        _, evidence = self.verify([check("version")], [{"ok": True}])
        report = {"verification": evidence}
        delegate_verify.pending_review(report)
        self.assertIs(report["independent_checks_passed"], True)
        self.assertIsNone(report["canonical_correctness"])
        self.assertIsNone(report["verified_correctness"])
        self.assertEqual(report["outer_acceptance"], "pending")
        self.assertEqual(report["task_adjudication"]["status"], "pending_outer_review")
        self.assertIs(report["success"], False)
        self.assertIs(report["applied"], False)

    def test_invalid_plans_are_rejected_before_sealing_or_running_checks(self):
        valid = check("example")
        cases = {
            "version": {"version": True, "checks": []},
            "too many checks": {
                "version": 1,
                "checks": [check(str(i)) for i in range(17)],
            },
            "duplicate name": {"version": 1, "checks": [valid, valid]},
            "missing argv": {
                "version": 1,
                "checks": [{"name": "missing", "timeout": 5}],
            },
            "unsupported command": {
                "version": 1,
                "checks": [dict(valid, argv=["/bin/sh"])],
            },
            "zero timeout": {"version": 1, "checks": [dict(valid, timeout=0)]},
        }
        for label, plan in cases.items():
            with self.subTest(label):
                (self.private / "checks.json").write_text(json.dumps(plan))
                runtime = RecordingRuntime([])
                with self.assertRaises(ValueError):
                    delegate_verify.verify(
                        runtime, self.workspace, self.task, self.output, 120
                    )
                self.assertEqual(runtime.calls, [])
                self.assertFalse(self.output.exists())
