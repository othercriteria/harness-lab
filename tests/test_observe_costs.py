import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from observe import Evidence


class CostTests(unittest.TestCase):
    def test_checkpoint_repair_time_counts_as_checkpoint_work(self):
        self.request(1, 2, "bash")
        self.request(2, 3, "checkpoint_context")
        self.request(3, 5, "checkpoint_context")
        self.save("context-checkpoint-request-001.json", {"model_calls": 1})
        self.save(
            "context-checkpoint-repair-request-001.json",
            {"model_calls": 2, "status": "requested"},
        )
        trace = self.data.trace("campaign", self.trial.name)
        self.assertEqual(trace["cost_breakdown"]["checkpoint_request_seconds"], 8)
        event = next(
            e
            for e in trace["events"]
            if e["id"] == "context-checkpoint-repair-request-001"
        )
        self.assertEqual(event["state"], "checkpoint repair requested")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.trial = self.root / "campaign/experiment/trial-00-task"
        self.trial.mkdir(parents=True)
        self.data = Evidence(self.root)

    def save(self, name, value):
        (self.trial / name).write_text(json.dumps(value))

    def request(self, index, seconds=None, function=None, backend=True):
        prefix = f"request-{index:03d}"
        self.save(prefix + ".request.json", {"messages": []})
        if seconds is not None:
            self.save(prefix + ".timing.json", {"wall_seconds": seconds})
        if function:
            response = {
                "choices": [
                    {"message": {"tool_calls": [{"function": {"name": function}}]}}
                ]
            }
            if backend:
                response["timings"] = {"prompt_ms": 1000, "predicted_ms": 2000}
            self.save(prefix + ".response.bin", response)

    def test_whole_trial_costs_do_not_depend_on_event_page(self):
        for index in range(1, 83):
            self.request(index, 3, "bash")
        latest = self.data.trace("campaign", self.trial.name)
        earlier = self.data.trace("campaign", self.trial.name, start=0)
        self.assertEqual(len(latest["events"]), 80)
        self.assertEqual(latest["cost_breakdown"], earlier["cost_breakdown"])
        cost = latest["cost_breakdown"]
        self.assertEqual(cost["model_request_seconds"], 246)
        self.assertEqual(cost["coverage"]["requests"], 82)
        self.assertEqual(cost["backend_prompt_seconds"], 82)
        self.assertIsNone(cost["first_structured_edit_seconds_approx"])
        self.assertIsNone(cost["read_calls"])

    def test_subsets_edit_estimates_and_missing_response_are_explicit(self):
        self.request(1, 8, "bash")
        self.request(2, 2, "checkpoint_context")
        self.request(3, 3, "finish_attempt", backend=False)
        self.request(4, 4)  # Timed request without a response: usage is unknown.
        self.save("context-checkpoint-request-001.json", {"model_calls": 1})
        self.save("fresh-context-reset-001.json", {"status": "applied"})
        self.save("fresh-context-bypassed-002.json", {"status": "bypassed"})
        self.save(
            "summary.json",
            {
                "task_wall_seconds": 30,
                "verification_wall_seconds": 1,
                "limits": {"agent_wall_seconds": 28},
            },
        )
        messages = []
        for index, name, path, remaining in (
            (1, "write_file", "tests/test_extra.py", 27),
            (2, "edit_file", "/workspace/code.py", 20),
            (3, "write_file", "code.py", 14),
        ):
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": str(index),
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps({"path": path}),
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": str(index),
                        "content": "Tool result metadata: "
                        + json.dumps({"remaining_agent_seconds": remaining})
                        + "\nTool output (literal text):\n{}",
                    },
                ]
            )
        messages.append(
            {
                "role": "assistant",
                "tool_calls": [
                    {"function": {"name": "read_file", "arguments": "{}"}},
                    {"function": {"name": "checkpoint_context", "arguments": "{}"}},
                ],
            }
        )
        self.save("trajectory.json", {"messages": messages})
        cost = self.data.costs.get(self.data, self.trial)
        self.assertEqual(cost["model_request_seconds"], 17)
        self.assertEqual(cost["checkpoint_request_seconds"], 2)
        self.assertEqual(cost["finalization_request_seconds"], 3)
        self.assertEqual(cost["first_structured_edit_seconds_approx"], 8)
        self.assertEqual(cost["after_last_structured_edit_seconds_approx"], 16)
        self.assertEqual(cost["coverage"]["responses"], 3)
        self.assertEqual(cost["coverage"]["backend_prompt_reports"], 2)
        self.assertEqual(cost["context_resets"], 1)
        self.assertEqual(cost["read_calls"], 1)
        self.assertEqual(cost["checkpoint_calls"], 1)
        self.assertIn("subsets", cost["note"])
        self.assertIn("unknown", cost["note"])

    def test_cache_reuses_projection_and_invalidates_on_rewrite(self):
        self.request(1, 3, "bash")
        before = self.data.costs.get(self.data, self.trial)
        with patch.object(
            self.data, "read", side_effect=AssertionError("Unchanged trial reparsed")
        ):
            self.assertIs(self.data.costs.get(self.data, self.trial), before)
        self.save("request-001.timing.json", {"wall_seconds": 12})
        after = self.data.costs.get(self.data, self.trial)
        self.assertEqual(after["model_request_seconds"], 12)
        self.assertIsNot(after, before)

    def test_nonfinite_and_unrecorded_values_do_not_become_zero_cost(self):
        self.request(1)
        self.save("request-001.timing.json", {"wall_seconds": float("nan")})
        self.save(
            "request-001.response.bin",
            {"timings": {"prompt_ms": -1, "predicted_ms": True}},
        )
        self.save("request-nope.request.json", {})
        cost = self.data.costs.get(self.data, self.trial)
        self.assertEqual(cost["coverage"]["requests"], 1)
        self.assertIsNone(cost["model_request_seconds"])
        self.assertIsNone(cost["backend_prompt_seconds"])
        self.assertIsNone(cost["backend_predicted_seconds"])

    def test_malformed_historical_calls_do_not_break_projection(self):
        self.request(1, 2)
        self.save("request-001.response.bin", {"choices": {"unexpected": True}})
        self.save(
            "trajectory.json",
            {
                "messages": [
                    {"tool_calls": None},
                    {"tool_calls": True},
                    {"tool_calls": [{"function": None}]},
                    {"role": "tool", "tool_call_id": []},
                    {
                        "tool_calls": [
                            {
                                "id": [],
                                "function": {
                                    "name": "write_file",
                                    "arguments": '{"path":"code.py"}',
                                },
                            }
                        ]
                    },
                ]
            },
        )
        cost = self.data.costs.get(self.data, self.trial)
        self.assertEqual(cost["model_request_seconds"], 2)
        self.assertIsNone(cost["first_structured_edit_seconds_approx"])


if __name__ == "__main__":
    unittest.main()
