import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from observe_harbor import HarborCatalog


class HarborObservatoryTests(unittest.TestCase):
    def test_live_trace_then_interrupted_attempt_with_zero_reward(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "smoke"
            trial = source / "trials/run-a"
            worker = trial / "agent/worker"
            worker.mkdir(parents=True)
            agent = {
                "import_path": "harbor_worker:Worker",
                "kwargs": {"control": False, "task_key": "task"},
                "model_name": "qwen",
            }
            (trial / "config.json").write_text(json.dumps({"agent": agent}))
            data = HarborCatalog([source])
            (worker / "tool-001.request.json").write_text(
                json.dumps(
                    {
                        "mode": "execute",
                        "interface": {"tool": "run_checks", "arguments": {"cwd": "."}},
                        "arguments": {"command": "true"},
                    }
                )
            )
            (worker / "request-001.request.json").write_text('{"messages":[]}')
            row = data.runs()["runs"][0]["trials"][0]
            self.assertIsNone(row["reward"])
            self.assertTrue(row["has_trace"])
            events = data.trace("smoke", "run-a")["events"]
            self.assertEqual(
                next(e for e in events if e["kind"] == "tool")["tool_name"],
                "run_checks",
            )
            self.assertEqual(
                next(e for e in events if e["kind"] == "model")["state"],
                "awaiting response",
            )
            (trial / "result.json").write_text(
                json.dumps(
                    {
                        "started_at": "2026-11-23T15:00:00Z",
                        "finished_at": "2026-11-23T15:01:00Z",
                        "reward_valid": True,
                        "verifier_result": {"rewards": {"reward": 0}},
                        "exception_info": {
                            "exception_type": "AgentTimeoutError",
                            "exception_message": "timed out",
                        },
                    }
                )
            )
            row = data.run("smoke")["trials"][0]
            self.assertEqual(
                (row["state"], row["reward"], row["outcome"]),
                ("stopped with error", 0, None),
            )
            trace = data.trace("smoke", "run-a")
            self.assertEqual(trace["cost_breakdown"]["task_seconds"], 60)
            self.assertEqual(trace["cost_breakdown"]["status"], "recorded Harbor trial")
            self.assertEqual(
                next(e for e in trace["events"] if e["kind"] == "model")["state"],
                "request timed out",
            )
            with self.assertRaises(ValueError):
                data.artifact("smoke", "run-a", "../../result.json")
            agent["kwargs"]["control"] = True
            (trial / "config.json").write_text(json.dumps({"agent": agent}))
            self.assertEqual(data.run("smoke")["trials"], [])
            with self.assertRaises(ValueError):
                data.trace("smoke", "run-a")
