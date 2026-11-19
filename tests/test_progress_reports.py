"""Public checkpoint-report contracts at submission and retrospective inspection."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import progress_inspect
import progress_report


def report(**changes):
    return {
        "change": "advanced",
        "implemented": ["Added a migration"],
        "checks": [{"result": "unknown", "summary": "Verification pending"}],
        "remaining": ["Verify against an empty database"],
        "obstacle": "",
        "next_action": "Run the migration test",
        "evidence": [],
    } | changes


class ProgressReportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.trial = Path(temp.name)

    def checkpoint(self, number, record):
        path = self.trial / f"context-checkpoint-{number:03}.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        return path.name

    def inspect(self, directory):
        output = io.StringIO()
        with redirect_stdout(output):
            status = progress_inspect.main([str(directory)])
        return status, json.loads(output.getvalue())

    def test_partial_inspection_retains_claims_in_numeric_order(self):
        last = report(
            change="unchanged",
            checks=[{"result": "failing", "summary": "Missing table"}],
            obstacle="Migration did not apply",
            remaining=["Fix migration", "Rerun"],
        )
        late = self.checkpoint(1000, {"progress": last})
        early = self.checkpoint(998, {"progress": report()})
        self.checkpoint(999, {"summary": "legacy checkpoint"})
        self.checkpoint(1, {"progress": report(change="typo")})
        (self.trial / "context-checkpoint-002.json").write_bytes(b"\xff")
        (self.trial / "context-checkpoint-request-003.json").write_text("{}")

        status, result = self.inspect(self.trial)
        self.assertEqual(status, 1)
        self.assertEqual(result["report_files"], [early, late])
        self.assertEqual(
            result["counts"],
            {
                "checkpoint_file_count": 5,
                "report_count": 2,
                "missing_progress_count": 1,
                "malformed_record_count": 1,
                "malformed_report_count": 1,
                "unreadable_file_count": 0,
            },
        )
        summary = result["summary"]
        self.assertEqual(summary["latest"], last)
        self.assertEqual(summary["change_counts"]["unchanged"], 1)
        self.assertEqual(
            summary["check_counts"],
            {
                "passing": 0,
                "failing": 1,
                "stale": 0,
                "unknown": 1,
            },
        )
        self.assertEqual(summary["reports_with_obstacle"], 1)
        self.assertEqual(summary["remaining_counts"], [1, 2])
        self.assertEqual(summary["repeated_next_action_transitions"], 1)

    def test_empty_and_missing_directories_are_distinguishable(self):
        status, empty = self.inspect(self.trial)
        self.assertEqual(status, 0)
        self.assertIsNone(empty["summary"]["latest"])
        self.assertEqual(empty["diagnostics"][0]["kind"], "no_checkpoints")
        status, missing = self.inspect(self.trial / "absent")
        self.assertEqual(status, 2)
        self.assertIn("error", missing)

    def test_live_validation_requires_known_citation_offline_inspection_keeps_claim(self):
        evidence = [{"kind": "observation", "observation_id": "o0007"}]
        value = report(evidence=evidence)
        history = SimpleNamespace(expose_ids=True, records={"o0007": {}})
        self.assertEqual(progress_report.validate(value, history), value)
        with self.assertRaisesRegex(ValueError, "not from this attempt"):
            progress_report.validate(value)
        with self.assertRaisesRegex(ValueError, "Duplicate observation"):
            progress_report.validate(report(evidence=evidence * 2), history)
        self.checkpoint(1, {"progress": value})
        status, result = self.inspect(self.trial)
        self.assertEqual(status, 0)
        self.assertEqual(result["summary"]["latest"]["evidence"], evidence)

    def test_live_and_offline_accept_same_utf8_boundary_and_reject_bad_shapes(self):
        valid = report(next_action="é" * 150)
        invalid = [
            report(next_action="é" * 151),
            report(remaining=["check"] * 5),
            report(change="finished"),
            report(checks=[{"result": "passing"}]),
            report(checks=[{"result": "green", "summary": "done"}]),
            report(obstacle="  "),
            report(implemented=["line\x00break"]),
        ]
        self.assertEqual(progress_report.validate(valid), valid)
        accepted = self.checkpoint(0, {"progress": valid})
        for n, value in enumerate(invalid, start=1):
            with self.subTest(n=n), self.assertRaises(ValueError):
                progress_report.validate(value)
            self.checkpoint(n, {"progress": value})
        status, result = self.inspect(self.trial)
        self.assertEqual(status, 1)
        self.assertEqual(result["report_files"], [accepted])
        self.assertEqual(result["counts"]["malformed_report_count"], len(invalid))
