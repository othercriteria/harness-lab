"""The host checker accounts for fixtures it cannot execute."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_fixtures


class FixtureScopeTests(unittest.TestCase):
    def test_unknown_policy_is_an_error(self):
        for metadata in (
            {"origin": "unknown"},
            {"fixture_validation": "unknown"},
            {"kind": "contract-triage"},
        ):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                check_fixtures.separate_evaluation(metadata)

    def test_deferred_only_inventory_has_no_pass_and_never_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, metadata in {
                "imported": {"origin": "imported"},
                "isolated": {"fixture_validation": "isolated-only"},
                "triage": {
                    "kind": "contract-triage",
                    "requires_outer_adjudication": True,
                },
            }.items():
                task = root / "tasks" / name
                task.mkdir(parents=True)
                (task / "task.json").write_text(json.dumps(metadata))
            report = root / "report.json"
            with (
                patch.object(check_fixtures, "ROOT", root),
                patch.object(check_fixtures, "run_suite", side_effect=AssertionError),
                patch.object(
                    sys, "argv", ["check", "--host-eligible", "--report", str(report)]
                ),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(check_fixtures.main(), 1)
                with self.assertRaisesRegex(ValueError, "host execution refused"):
                    check_fixtures.check_task(root / "tasks" / "imported")
            result = json.loads(report.read_bytes())
            self.assertFalse(result["passed"])
            self.assertEqual(result["tasks"], [])
            self.assertEqual(
                result["requires_separate_evaluation"],
                {
                    "imported": "separate isolated evaluator",
                    "isolated": "isolated-only validation",
                    "triage": "outer adjudication",
                },
            )
