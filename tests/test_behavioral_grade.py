"""External verification from disposable fixtures and recorded transport outcomes."""

import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import behavioral_grade as grade
import grade_issue_selection
from control import UnsafeCleanup


class BehavioralGradeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "submitted"
        self.source.mkdir()
        self.output = self.root / "evidence"
        self.runtime = Mock(spec=["sandbox"])

    def gate(self):
        return grade.Gate(self.runtime, self.source, self.output)

    def verify_issues(self, transport):
        with patch.object(grade, "perform_tool", side_effect=transport):
            return grade.verify_behavior(
                self.runtime, self.source, "issue-selection", self.output
            )

    def test_fresh_cases_replace_fixture_roots_and_steps_use_returned_workspace(self):
        (self.source / "probe").mkdir()
        (self.source / "probe/stale").write_text("left by submission")

        def transition(runtime, workspace, name, arguments, timeout, prefix):
            self.assertIs(runtime, self.runtime)
            self.assertFalse((workspace / "probe/stale").exists())
            if arguments["command"] == "continue":
                self.assertEqual((workspace / "probe/product").read_bytes(), b"old")
            updated = workspace.with_name("0001")
            shutil.copytree(workspace, updated)
            (updated / "probe/product").write_bytes(
                (workspace / "probe/input").read_bytes()
            )
            prefix.with_suffix(".cleanup.json").write_text('{"verified":true}')
            return {"ok": True}, updated

        gate = self.gate()
        with patch.object(grade, "perform_tool", transition):
            first = gate.case("first", {"probe/input": b"old"}, "produce")
            second = gate.step(first, "continue", {"probe/input": b"new"})
        self.assertEqual(gate.read(first, "probe/product"), b"old")
        self.assertEqual(gate.read(second, "probe/product"), b"new")
        self.assertTrue((self.source / "probe/stale").is_file())
        self.assertFalse((self.source / "probe/input").exists())
        self.assertEqual(gate.finish()["sandbox_calls"], 2)
        self.assertTrue(gate.absent(first, "probe/absent"))

    def test_sqlite_observer_receives_only_data_and_available_sidecars(self):
        for name in ("result.db", "result.db-wal", "unrelated.py"):
            (self.source / name).write_bytes(name.encode())
        gate = self.gate()

        def observe(workspace, spec, prefix):
            self.assertEqual(
                {p.name: p.read_bytes() for p in workspace.iterdir()},
                {"database": b"result.db", "database-wal": b"result.db-wal"},
            )
            self.assertEqual(spec["mode"], "grade")
            self.assertEqual(spec["argv"][:4], ["/bin/python3", "-I", "-S", "-c"])
            prefix.with_suffix(".cleanup.json").write_text('{"verified":true}')
            return {"ok": True, "stdout": "[[[7]]]", "stderr": ""}, None

        self.runtime.sandbox.side_effect = observe
        rows = gate.observe_sqlite(
            grade.Probe({}, self.source), "result.db", ["SELECT 7"]
        )
        self.assertEqual(rows, [[[7]]])
        self.assertEqual(gate.finish()["sandbox_calls"], 1)

    def test_empty_and_mixed_check_summaries(self):
        gate = self.gate()
        self.assertFalse(gate.finish()["passed"])
        gate = grade.Gate(self.runtime, self.source, self.root / "mixed")
        gate.record("first", True, {"exit": 0})
        gate.record("second", False, {"exit": 1})
        summary = gate.finish()
        self.assertFalse(summary["passed"])
        self.assertEqual(
            summary, json.loads((gate.output / "summary.json").read_bytes())
        )
        for index, check in enumerate(summary["checks"]):
            self.assertEqual(
                check,
                json.loads((gate.output / f"check-{index:03d}.json").read_bytes()),
            )

    def test_rejected_setup_does_not_count_as_a_sandbox_dispatch(self):
        gate = self.gate()
        with patch.object(grade, "perform_tool") as dispatch:
            with self.assertRaisesRegex(ValueError, "namespace"):
                gate.case("invalid", {"unexpected/file": b"input"}, "unused")
            dispatch.assert_not_called()
        self.assertEqual(gate.finish()["sandbox_calls"], 0)

    def test_candidate_and_observer_share_one_call_budget(self):
        gate = self.gate()
        (self.source / "test.db").write_bytes(b"fixture")

        def command(runtime, workspace, name, arguments, timeout, prefix):
            prefix.with_suffix(".cleanup.json").write_text('{"verified":true}')
            return {"ok": True}, workspace

        def observe(workspace, spec, prefix):
            prefix.with_suffix(".cleanup.json").write_text('{"verified":true}')
            return {"ok": True, "stdout": "[]", "stderr": ""}, None

        self.runtime.sandbox.side_effect = observe
        with patch.object(grade, "perform_tool", side_effect=command) as dispatch:
            for _ in range(31):
                probe = gate.case("ordinary", {}, "command")
            self.assertEqual(gate.observe_sqlite(probe, "test.db", ["SELECT 1"]), [])
            with self.assertRaisesRegex(RuntimeError, "limit"):
                gate.step(probe, "over budget")
            with self.assertRaisesRegex(RuntimeError, "limit"):
                gate.observe_sqlite(probe, "test.db", [])
            self.assertEqual(dispatch.call_count, 31)
        self.runtime.sandbox.assert_called_once()
        self.assertEqual(gate.finish()["sandbox_calls"], 32)

    def test_nonfatal_transport_error_requires_verified_cleanup(self):
        def failure(runtime, workspace, name, arguments, timeout, prefix):
            prefix.with_suffix(".cleanup.json").write_text('{"verified":true}')
            raise RuntimeError("transport unavailable")

        result = self.verify_issues(failure)
        self.assertFalse(result["passed"])
        self.assertEqual(
            result["checks"],
            [
                {
                    "name": "gate-error",
                    "passed": False,
                    "details": {
                        "type": "RuntimeError",
                        "message": "transport unavailable",
                    },
                }
            ],
        )

    def test_missing_or_malformed_cleanup_aborts_even_after_a_normal_return(self):
        for index, content in enumerate((None, "{", '{"verified":1}')):
            with self.subTest(content=content):
                self.output = self.root / str(index)

                def command(runtime, workspace, name, arguments, timeout, prefix):
                    if content is not None:
                        prefix.with_suffix(".cleanup.json").write_text(content)
                    return {"ok": True}, workspace

                with self.assertRaises(UnsafeCleanup):
                    self.verify_issues(command)
                result = json.loads((self.output / "summary.json").read_bytes())
                self.assertFalse(result["passed"])
                self.assertEqual(result["checks"][-1]["name"], "unsafe-cleanup")

    def test_cleanup_failure_survives_failure_to_write_audit(self):
        write = grade.write_json
        for filename in ("check-000.json", "summary.json"):
            with self.subTest(filename=filename):
                self.output = self.root / filename
                original = UnsafeCleanup("unverified sandbox cleanup")

                def fail_one_write(path, value):
                    if path.name == filename:
                        raise OSError("storage full")
                    write(path, value)

                with (
                    patch.object(grade, "write_json", fail_one_write),
                    self.assertRaises(UnsafeCleanup) as raised,
                ):
                    self.verify_issues(original)
                self.assertIs(raised.exception, original)
                self.assertIn("storage full", " ".join(original.__notes__))

    def test_issue_rejection_requires_a_completed_program_exit(self):
        # Model the observable CLI effects for each case. No candidate runs in this test.
        def exporter(runtime, workspace, name, arguments, timeout, prefix):
            calls = workspace / "probe/calls"
            argv = shlex.split(arguments["command"])
            issues = [arg for flag, arg in zip(argv, argv[1:]) if flag == "--issue"]
            status, stop = 2, None
            if issues == ["09", "12", "9"]:
                status = 0
                numbers = [9, 12]
                calls.write_text(
                    "".join(
                        json.dumps(["issue", "view", str(n)]) + "\n" for n in numbers
                    )
                )
                rows = [
                    {"number": n, "labels": ["a", "z"], "state": "CLOSED"}
                    for n in numbers
                ]
                (workspace / "probe/out").write_text(json.dumps({"issues": rows}))
            elif issues == ["5", "113"]:
                calls.write_text('["issue","view","5"]\n["issue","view","113"]\n')
            elif issues == ["3", "00"]:
                stop = "tool_wall_limit"
            elif issues == ["７"]:
                status = -15
            prefix.with_suffix(".cleanup.json").write_text('{"verified":true}')
            return {
                "ok": status == 0,
                "returncode": status,
                "stopped_by": stop,
            }, workspace

        report = self.verify_issues(exporter)
        checks = {row["name"]: row["passed"] for row in report["checks"]}
        self.assertEqual(
            checks,
            {
                "selected": True,
                "missing": True,
                "zero": False,
                "unicode": False,
                "too-many": True,
            },
        )
        self.assertFalse(report["passed"])

    def test_issue_lookup_fixture_identifies_the_requested_issue(self):
        # This runs the outer grader's trusted gh stand-in.
        probe = self.root / "probe"
        probe.mkdir()
        fake = probe / "gh"
        fake.write_bytes(grade_issue_selection.FAKE)
        fields = "number,state,title,body,url,updatedAt,labels"
        for number in (9, 12):
            raw = subprocess.check_output(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    str(fake),
                    "issue",
                    "view",
                    str(number),
                    "--repo",
                    "example/repo",
                    "--json",
                    fields,
                ],
                cwd=self.root,
            )
            issue = json.loads(raw)
            self.assertEqual(issue["number"], number)
            self.assertEqual(
                issue["url"], f"https://github.com/example/repo/issues/{number}"
            )
