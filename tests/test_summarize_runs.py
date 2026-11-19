"""Unit tests for scripts/summarize_runs.summarize using synthetic campaigns."""

import hashlib
import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import summarize_runs


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


class SummarizeRunsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.runs = Path(tmp.name).resolve()
        patcher = unittest.mock.patch.object(summarize_runs, "ROOT", self.runs)
        patcher.start()
        self.addCleanup(patcher.stop)

    def campaign(self, name):
        path = self.runs / name
        path.mkdir()
        return path

    def test_missing_background_receipt_is_absent_evidence(self):
        campaign = self.campaign("campaign-missing")
        result = summarize_runs.summarize(campaign)

        self.assertEqual(result["campaign"], "campaign-missing")
        self.assertEqual(result["path"], str(campaign))
        self.assertIsNone(result["lifecycle"]["background_restored"])
        self.assertIsNone(result["lifecycle"]["background_error"])
        self.assertFalse(result["experiment_completed"])
        self.assertIsNone(result["inputs_sha256"])
        # No receipt file was written, so no evidence entry may appear.
        self.assertEqual(result["evidence"], {})
        self.assertEqual(result["trials"], [])

    def test_present_receipt_hashes_exact_stored_bytes(self):
        campaign = self.campaign("campaign-present")
        raw = b'{"restored": true, "note": "weights reloaded"}\n'
        receipt = campaign / "background" / "summary.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_bytes(raw)

        result = summarize_runs.summarize(campaign)

        self.assertIs(result["lifecycle"]["background_restored"], True)
        self.assertIsNone(result["lifecycle"]["background_error"])
        entry = result["evidence"]["background/summary.json"]
        self.assertEqual(entry["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(entry["path"], str(receipt))
        # Receipts that do not exist must not produce evidence entries.
        self.assertNotIn("voice/result.json", result["evidence"])
        self.assertNotIn("ollama/result.json", result["evidence"])
        self.assertNotIn("inputs.json", result["evidence"])
        # summarize must leave the input bytes intact.
        self.assertEqual(receipt.read_bytes(), raw)

    def test_trial_row_uses_trajectory_and_parent_timing(self):
        campaign = self.campaign("campaign-trial")
        trial_dir = campaign / "experiment" / "trial-001"
        write_json(
            campaign / "experiment" / "summary.json",
            {
                "profile": "tiny",
                "completed": True,
                "server_stopped": True,
                "client_stopped": True,
                "trials": [
                    {"path": str(trial_dir.with_name("trial-000")), "process_wall_seconds": 8},
                    {"path": str(trial_dir), "process_wall_seconds": 12.5},
                ],
            },
        )
        write_json(campaign / "inputs.json", {"sha256": "abc123"})
        write_json(
            trial_dir / "summary.json",
            {
                "task": "add-one",
                "seed": 7,
                "split": "dev",
                "model": "tiny",
                "success": True,
                "canonical_correctness": True,
                "delivery_correctness": False,
                "clean_agent_completion": False,
                "human_interventions": 0,
                "within_budget": True,
                "task_wall_seconds": 3.25,
                "agent_wall_seconds": 3.1,
                "verification_wall_seconds": 0.15,
                "agent_error": None,
                "verification_error": None,
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
                "tool_calls": 2,
                "fixture": {"sha256": "f00"},
                "limits": {"protocol": "v0"},
                "verification": {
                    "tests": {"canonical": 1, "delivery": 0, "log": "ignored"}
                },
            },
        )
        write_json(trial_dir / "trajectory.json", {"info": {"exit_status": 0}})

        result = summarize_runs.summarize(campaign)

        self.assertEqual(result["profile"], "tiny")
        self.assertEqual(result["inputs_sha256"], "abc123")
        self.assertIs(result["experiment_completed"], True)
        self.assertIs(result["server_stopped"], True)
        self.assertIs(result["client_stopped"], True)

        self.assertEqual(len(result["trials"]), 1)
        row = result["trials"][0]
        self.assertEqual(row["task"], "add-one")
        self.assertEqual(row["path"], str(trial_dir))
        self.assertEqual(row["protocol"], "v0")
        self.assertIs(row["success"], True)
        # Canonical correctness and clean completion are distinct signals.
        self.assertIs(row["canonical_correctness"], True)
        self.assertIs(row["clean_agent_completion"], False)
        self.assertEqual(row["task_wall_seconds"], 3.25)
        self.assertEqual(row["exit_status"], 0)
        self.assertEqual(row["parent_process_wall_seconds"], 12.5)
        self.assertEqual(row["fixture_sha256"], "f00")
        self.assertEqual(row["tests"], {"canonical": 1, "delivery": 0})
        self.assertIn("experiment/trial-001/summary.json", result["evidence"])
        self.assertIn("experiment/trial-001/trajectory.json", result["evidence"])


if __name__ == "__main__":
    unittest.main()
