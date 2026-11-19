"""Read-only audit boundary cases; no model or candidate code is executed."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from submission_review_evidence import reset_conformance


class InterruptedReviewAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.protocol = {"fresh_context": {"trigger": "first_submission"}}
        self.raw = {
            "usage": {
                "fresh_context": {
                    "trigger": "first_submission",
                    "reset_applied": False,
                    "decision": "bypassed",
                }
            },
            "agent_error": {"type": "DeadlineExceeded"},
            "clean_agent_completion": False,
            "success": False,
        }
        self.save("tool-001.request.json", {"mode": "tool", "name": "execute"})
        self.save(
            "tool-001.cleanup.json",
            {"verified": True, "owned_process_reaped": True},
        )
        self.save(
            "trajectory.json",
            {
                "messages": [
                    {"role": "exit", "extra": {"exit_status": "DeadlineExceeded"}}
                ]
            },
        )

    def save(self, name, value):
        (self.root / name).write_text(json.dumps(value))

    def audit(self):
        return reset_conformance(self.root, self.protocol, self.raw)

    def test_verified_terminal_interruption_preserves_unknown_result(self):
        for name in ("execute", "edit_file", "write_file"):
            with self.subTest(tool=name):
                self.save("tool-001.request.json", {"mode": "tool", "name": name})
                result = self.audit()
                self.assertTrue(result["conforming"], result)
                self.assertIsNone(result["interrupted_tools"][0]["result"])
                self.assertFalse((self.root / "tool-001.result.json").exists())
                self.assertFalse(self.raw["success"])

    def test_missing_intermediate_result_is_not_accepted(self):
        self.save("tool-002.request.json", {"mode": "tool", "name": "execute"})
        self.assertFalse(self.audit()["conforming"])

    def test_missing_adapter_control_is_not_an_interrupted_sandbox(self):
        self.save(
            "tool-001.request.json",
            {"mode": "adapter-control", "name": "finish_attempt"},
        )
        self.assertFalse(self.audit()["conforming"])

    def test_requires_failed_deadline_and_verified_cleanup_and_trace(self):
        for field, value in (
            ("agent_error", {"type": "OtherError"}),
            ("clean_agent_completion", True),
            ("success", True),
        ):
            with self.subTest(field=field):
                prior = self.raw[field]
                self.raw[field] = value
                self.assertFalse(self.audit()["conforming"])
                self.raw[field] = prior
        self.save(
            "tool-001.cleanup.json", {"verified": True, "owned_process_reaped": False}
        )
        self.assertFalse(self.audit()["conforming"])
        self.save(
            "tool-001.cleanup.json", {"verified": True, "owned_process_reaped": True}
        )
        self.save("trajectory.json", {"messages": [{"role": "assistant"}]})
        self.assertFalse(self.audit()["conforming"])

    def test_existing_complete_results_stay_complete(self):
        self.save("tool-001.result.json", {"returncode": 0})
        result = self.audit()
        self.assertTrue(result["conforming"], result)
        self.assertEqual(result["interrupted_tools"], [])

    def test_corrupt_result_is_not_treated_as_absent(self):
        (self.root / "tool-001.result.json").write_text("{")
        self.assertFalse(self.audit()["conforming"])


if __name__ == "__main__":
    unittest.main()
