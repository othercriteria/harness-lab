"""Verification reuse must have a matching full-scan baseline and honest receipts."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from model_registry import record_campaign, verify_weight


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.weight = self.root / "model.gguf"
        self.weight.write_bytes(b"weight bytes")
        self.expected = {
            "size": self.weight.stat().st_size,
            "sha256": hashlib.sha256(self.weight.read_bytes()).hexdigest(),
        }
        self.registry = self.root / "registry"

    def verify(self, mode="metadata"):
        return verify_weight(
            self.weight, self.expected, mode=mode, registry=self.registry
        )

    def test_first_metadata_request_hashes_then_reuses_without_reading_weights(self):
        first = self.verify()
        self.assertEqual(first["method"], "full")
        original = Path.open

        def open_file(path, *args, **kwargs):
            if path == self.weight:
                raise AssertionError("Metadata hit read weight contents")
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", open_file):
            second = self.verify()
        self.assertEqual(second["method"], "metadata")
        self.assertEqual(first["full_verification_id"], second["full_verification_id"])
        self.assertEqual(self.verify("full")["method"], "full")

    def test_replacement_and_changed_expected_hash_do_not_reuse(self):
        self.verify()
        replacement = self.root / "replacement"
        replacement.write_bytes(b"weight bytes")
        replacement.replace(self.weight)
        self.assertEqual(self.verify()["method"], "full")
        self.expected["sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
            self.verify()

    def test_corrupt_cache_rehashes_size_mismatch_fails_and_unknown_mode_rejected(self):
        self.verify()
        next((self.registry / "weights").glob("*.json")).write_text("[]")
        self.assertEqual(self.verify()["method"], "full")
        self.weight.write_bytes(b"x")
        with self.assertRaisesRegex(RuntimeError, "size mismatch"):
            self.verify()
        with self.assertRaises(ValueError):
            self.verify("trust-everything")

    def test_timing_import_keeps_failures_unknown_usage_and_recipe_distinctions(self):
        campaign = self.root / "run"
        exp = campaign / "experiment"
        trial = exp / "trial-00-test"
        trial.mkdir(parents=True)

        def write(path, data):
            path.write_text(json.dumps(data))

        write(
            campaign / "inputs.json",
            {"files": {"scripts/run_trial.py": "abc", "uv.lock": "def"}},
        )
        write(
            exp / "summary.json", {"completed": True, "weight_verification_seconds": 10}
        )
        write(exp / "profile.json", {"sampling": {"temperature": 1}})
        write(exp / "protocol.json", {"seed": 1, "task_wall_seconds": 60})
        write(exp / "props.json", {"chat_template": "template"})
        write(exp / "verified-weights.json", [])
        write(trial / "agent-config.json", {"prompt": "do work"})
        write(
            trial / "summary.json",
            {
                "task": "test",
                "fixture": {"sha256": "abc"},
                "seed": 1,
                "split": "development",
                "success": False,
                "task_wall_seconds": 55,
            },
        )
        write(trial / "request-001.request.json", {})
        (trial / "request-001.response.bin").write_bytes(b"incomplete")
        first = record_campaign(campaign, self.registry)
        observation = json.loads(Path(first["observation"]).read_text())
        self.assertFalse(observation["trials"][0]["raw_success"])
        self.assertEqual(observation["trials"][0]["source_acceptance"], "not imported")
        self.assertIsNone(observation["trials"][0]["responses"][0]["usage"])
        self.assertEqual(record_campaign(campaign, self.registry), first)
        write(exp / "profile.json", {"sampling": {"temperature": 0.6}})
        second = record_campaign(campaign, self.registry)
        self.assertNotEqual(first["recipes"], second["recipes"])
        self.assertTrue(Path(first["observation"]).exists())
        write(
            exp / "profile.json",
            {"sampling": {"temperature": 0.6}, "draft_artifact": {"id": "draft"}},
        )
        with self.assertRaises(FileNotFoundError):
            record_campaign(campaign, self.registry)
        draft_receipt = [{"method": "metadata", "full_verification_id": "draft-hash"}]
        write(exp / "verified-draft-weights.json", draft_receipt)
        third = record_campaign(campaign, self.registry)
        self.assertNotEqual(second["recipes"], third["recipes"])
        evidence = json.loads(Path(third["observation"]).read_text())
        self.assertEqual(evidence["draft_weight_verification"], draft_receipt)

    def test_startup_failure_has_profile_but_no_invented_template_recipe_or_trials(
        self,
    ):
        campaign = self.root / "failed-start"
        exp = campaign / "experiment"
        exp.mkdir(parents=True)
        inputs = {
            campaign / "inputs.json": {"files": {"scripts/serve_trial.py": "abc"}},
            exp / "profile.json": {"model": "example"},
            exp / "protocol.json": {"task_wall_seconds": 120},
            exp / "summary.json": {"completed": False, "error": {"message": "guard"}},
        }
        for path, value in inputs.items():
            path.write_text(json.dumps(value))
        receipt = record_campaign(campaign, self.registry)
        observation = json.loads(Path(receipt["observation"]).read_text())
        self.assertEqual(observation["stage"], "startup")
        self.assertEqual(observation["profile"], {"model": "example"})
        self.assertEqual(observation["recipes"], {})
        self.assertEqual(observation["trials"], [])
        self.assertIsNone(observation["runtime_template_sha256"])
        self.assertIsNone(observation["weight_verification"])
        self.assertEqual(observation["experiment_summary"]["error"]["message"], "guard")
        # The same missing template is not acceptable once a trial is claimed.
        trial = exp / "trial-00-test"
        trial.mkdir()
        (trial / "summary.json").write_text("{}")
        with self.assertRaises(FileNotFoundError):
            record_campaign(campaign, self.registry)
