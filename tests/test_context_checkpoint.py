"""Metered continuation memory with no candidate code execution on the host."""

import copy
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from checkpoint_evidence import verify_checkpoint_evidence
from coding_agent import IsolatedEnvironment, LocalModel
from context_checkpoint import action, validate
from control import UnsafeCleanup
from fresh_context import FreshContext, validate_history_archive, validate_policy
from mini_bootstrap import DefaultAgent, FormatError
from observations import ObservationHistory

POLICY = {
    "after_elapsed_agent_fraction": 0.5,
    "min_remaining_agent_seconds": 180,
    "summary_checkpoint": True,
}
SUMMARY = "Observed o0001: tests fail. Next: fix engine.py and save regression tests."


def call(name, value, identifier="call-1"):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": identifier,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(value)},
            }
        ],
    }


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = IsolatedEnvironment(
            SimpleNamespace(manifest={"mock": True}),
            self.root,
            self.root,
            10,
            tool_call_limit=8,
            structured_finalization=True,
        )
        self.env.agent_deadline = time.monotonic() + 350
        self.limits = {
            "total_completion_token_limit": 8000,
            "max_completion_tokens_per_request": 4096,
            "reasoning_budget_tokens": 4096,
            "request_timeout_seconds": 1,
            "context_capacity_tokens": 32768,
            "step_limit": 8,
            "structured_finalization": True,
            "plain_tool_observations": True,
            "time_budget_feedback": True,
            "context_policy": {
                "mode": "none",
                "keep_recent": 8,
                "trigger_tokens": 22000,
                "safety_tokens": 256,
            },
            "fresh_context": dict(POLICY),
        }
        self.model = LocalModel(
            "http://127.0.0.1:18080", "fake", {}, self.limits, self.root
        )
        self.model.history = ObservationHistory(
            self.root,
            self.limits["context_policy"],
            expose_ids=True,
        )
        self.env.history = self.model.history
        self.controller = FreshContext(self.root, POLICY, self.env, model=self.model)
        self.model.fresh_context = self.env.fresh_context = self.controller
        self.controller.start(self.env.agent_deadline, 705)
        self.model.count_tokens = lambda *args: 100
        self.requests = []
        self.perform_options = []

    def read(self, name):
        return json.loads((self.root / name).read_text())

    def run_sequence(
        self, checkpoint=None, finish_reason="tool_calls", after_response=None
    ):
        def response(request, **kwargs):
            self.requests.append(json.loads(request.data))
            n = len(self.requests)
            if n == 2:
                message = checkpoint or call(
                    "checkpoint_context", {"summary": SUMMARY}, "call-2"
                )
            elif n == 4:
                message = call(
                    "finish_attempt",
                    {
                        "disposition": "submitted",
                        "summary": "Work ready.",
                        "evidence": [],
                        "unverified": ["Independent checks pending."],
                        "blocker": None,
                    },
                    "call-4",
                )
            else:
                message = call("bash", {"command": "echo diagnostic"}, f"call-{n}")
            if after_response:
                after_response(n)
            return io.BytesIO(
                json.dumps(
                    {
                        "usage": {"prompt_tokens": 100, "completion_tokens": 5},
                        "choices": [
                            {
                                "finish_reason": finish_reason
                                if n == 2
                                else "tool_calls",
                                "message": message,
                            }
                        ],
                    }
                ).encode()
            )

        self.model.opener = SimpleNamespace(open=response)

        def perform(runtime, workspace, name, arguments, timeout, prefix, **options):
            self.perform_options.append(options)
            prefix.with_suffix(".cleanup.json").write_text('{"verified":true}')
            return {"ok": True, "returncode": 0, "stdout": "diagnostic"}, workspace

        agent = DefaultAgent(
            self.model,
            self.env,
            system_template="SYSTEM",
            instance_template="TASK {{task}}",
            step_limit=8,
            wall_time_limit_seconds=10000,
            output_path=self.root / "trajectory.json",
        )
        with patch("coding_agent.perform_tool", side_effect=perform):
            agent.run(task="same task")
        return agent

    def test_summary_is_metered_nonexecuting_memory_with_stable_prefix(self):
        deadline, workspace = self.env.agent_deadline, self.env.workspace
        self.run_sequence()
        self.assertEqual(
            (self.model.calls, self.model.completion_tokens, self.env.calls), (4, 20, 4)
        )
        self.assertEqual(
            (self.env.agent_deadline, self.env.workspace), (deadline, workspace)
        )
        self.assertEqual(len(self.perform_options), 2)
        self.assertIsNone(self.perform_options[0].get("history_archive"))
        self.assertEqual(
            self.perform_options[1]["history_archive"], self.root / "history"
        )
        self.assertEqual(
            [r["max_tokens"] for r in self.requests], [4096, 2048, 4096, 4096]
        )
        self.assertEqual(
            [r["reasoning_budget_tokens"] for r in self.requests],
            [4096, 256, 4096, 4096],
        )
        self.assertTrue(
            all(r["tools"] == self.requests[0]["tools"] for r in self.requests)
        )
        view = self.requests[2]["messages"]
        self.assertEqual(view[:2], self.requests[0]["messages"][:2])
        self.assertEqual(len(view), 3)
        self.assertIn(SUMMARY, view[2]["content"])
        self.assertIn("unverified memory", view[2]["content"])
        self.assertFalse(self.read("tool-002.result.json")["executed"])
        self.assertFalse((self.root / "tool-002.cleanup.json").exists())
        self.assertEqual(
            self.read("context-checkpoint-response-001.json")["completion_tokens"], 10
        )
        self.assertEqual(
            self.read("fresh-context-reset-001.json")["summary_checkpoint"]["status"],
            "retained",
        )
        archive = validate_history_archive(
            self.root / "history", self.root / "tool-003"
        )
        manifest = self.read("history/manifest.json")
        saved = [
            json.loads((archive / r["file"]).read_text()) for r in manifest["messages"]
        ]
        self.assertEqual(
            saved[5]["tool_calls"][0]["function"]["name"], "checkpoint_context"
        )
        self.assertTrue((self.root / "final-handoff.json").exists())
        audit = verify_checkpoint_evidence(self.root, self.limits)
        self.assertEqual(audit["status"], "saved")
        self.assertEqual(audit["summary_completion_tokens"], 5)
        self.assertEqual(audit["known_completion_tokens"], 20)
        changed = self.read("context-checkpoint-001.json")
        changed["summary"] = "Fabricated success"
        (self.root / "context-checkpoint-001.json").write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, "Saved memory differs"):
            verify_checkpoint_evidence(self.root, self.limits)

    def test_wrong_tool_is_charged_but_not_executed_then_plain_reset(self):
        self.run_sequence(
            checkpoint=call("bash", {"command": "must not execute"}, "call-2")
        )
        self.assertEqual(
            (self.model.calls, self.model.completion_tokens, self.env.calls), (4, 20, 3)
        )
        self.assertEqual(len(self.perform_options), 2)
        self.assertEqual(
            self.read("context-checkpoint-response-001.json")["status"],
            "rejected_response",
        )
        self.assertEqual(
            self.read("fresh-context-reset-001.json")["summary_checkpoint"]["status"],
            "fallback_without_summary",
        )
        self.assertEqual(len(self.requests[2]["messages"]), 3)
        self.assertFalse((self.root / "context-checkpoint-001.json").exists())
        self.assertEqual(
            verify_checkpoint_evidence(self.root, self.limits)["status"], "rejected"
        )

    def test_unknown_final_usage_does_not_skip_prior_checkpoint_receipts(self):
        self.run_sequence()
        (self.root / "request-004.response.bin").unlink()
        audit = verify_checkpoint_evidence(self.root, self.limits)
        self.assertEqual(audit["status"], "saved")
        self.assertEqual(audit["known_completion_tokens"], 15)
        self.assertFalse(audit["all_usage_known"])
        self.assertEqual(audit["unknown_requests"], [4])
        self.assertEqual(audit["summary_completion_tokens"], 5)
        (self.root / "tool-002.result.json").unlink()
        with self.assertRaises(OSError):
            verify_checkpoint_evidence(self.root, self.limits)

    def test_unknown_usage_before_later_request_is_not_recoverable_accounting(self):
        self.run_sequence()
        (self.root / "request-003.response.bin").unlink()
        with self.assertRaisesRegex(
            ValueError, "Continued after unknown request usage"
        ):
            verify_checkpoint_evidence(self.root, self.limits)

    def test_truncated_checkpoint_is_rejected_without_retry(self):
        self.run_sequence(finish_reason="length")
        self.assertEqual(self.env.calls, 3)
        self.assertEqual(self.controller.decision, "applied")
        self.assertFalse((self.root / "context-checkpoint-001.json").exists())
        self.assertEqual(
            verify_checkpoint_evidence(self.root, self.limits)["status"], "rejected"
        )

    def test_nonlist_calls_are_rejected_without_adapter_execution(self):
        self.run_sequence(
            checkpoint={"role": "assistant", "content": "", "tool_calls": 7}
        )
        self.assertEqual(self.env.calls, 3)
        self.assertEqual(len(self.perform_options), 2)
        self.assertEqual(
            verify_checkpoint_evidence(self.root, self.limits)["status"], "rejected"
        )

    def test_premature_checkpoint_is_charged_but_does_not_start_reset(self):
        response = {
            "usage": {"prompt_tokens": 100, "completion_tokens": 5},
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": call("checkpoint_context", {"summary": SUMMARY}),
                }
            ],
        }
        self.model.opener = SimpleNamespace(
            open=lambda *a, **k: io.BytesIO(json.dumps(response).encode())
        )
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "T"},
        ]
        with self.assertRaises(FormatError):
            self.model.query(messages)
        self.assertEqual(
            (self.model.calls, self.model.completion_tokens, self.env.calls), (1, 5, 0)
        )
        self.assertFalse(self.controller.checkpoint_requested)
        self.assertFalse(self.controller.checkpoint_attempted)
        self.assertFalse(list(self.root.glob("context-checkpoint-*.json")))

    def test_late_summary_does_not_renew_deadline_or_force_reset(self):
        now = time.monotonic()

        def advance(n):
            if n == 2:
                clock.return_value = self.env.agent_deadline - 179

        with patch("time.monotonic", return_value=now) as clock:
            self.run_sequence(after_response=advance)
        self.assertEqual(self.controller.decision, "bypassed")
        self.assertFalse((self.root / "history").exists())
        self.assertGreater(len(self.requests[2]["messages"]), 3)
        self.assertIsNone(self.perform_options[1].get("history_archive"))
        self.assertEqual(
            verify_checkpoint_evidence(self.root, self.limits)["status"], "saved"
        )

    def test_forged_control_receipt_cannot_skip_cleanup(self):
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "T"},
        ]
        self.controller.checkpoint_requested = True
        self.controller.checkpoint_response(accepted=True)
        self.env.execute(
            {"tool": "checkpoint_context", "payload": {"summary": SUMMARY}}
        )
        (self.root / "tool-001.result.json").write_text('{"executed": true}')
        self.controller.completed_cycle({}, [{}])
        with self.assertRaises(UnsafeCleanup):
            self.controller.before_query(messages, self.model)
        self.assertIsNone(self.controller.boundary)

    def test_no_allowance_for_continuation_bypasses_checkpoint(self):
        self.model.calls = 7
        self.controller.completed_cycle({}, [{}])
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "T"},
        ]
        self.assertFalse(self.controller.before_query(messages, self.model))
        self.assertFalse(self.controller.checkpoint_pending)
        self.assertEqual(self.controller.decision, "bypassed")

    def test_policy_rejects_incompatible_modes(self):
        validate_policy(self.limits)
        for change in (
            {"structured_finalization": False},
            {"fresh_context": {**POLICY, "summary_checkpoint": 1}},
            {
                "fresh_context": {
                    "trigger": "first_submission",
                    "min_remaining_agent_seconds": 180,
                    "continuation_mode": "review",
                    "summary_checkpoint": True,
                }
            },
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_policy({**self.limits, **change})

    def test_strict_bounded_payload_and_single_requested_call(self):
        valid = call("checkpoint_context", {"summary": SUMMARY})
        self.assertEqual(
            action(valid, {}, "tool_calls", requested=True)[0]["payload"],
            {"summary": SUMMARY},
        )
        for value in (
            {"summary": ""},
            {"summary": "é" * 2049},
            {"summary": "ok", "command": "evil"},
        ):
            with self.subTest(value=str(value)[:30]), self.assertRaises(ValueError):
                validate(value)
        for raw in ('{"summary":"a","summary":"b"}', '{"summary":NaN}', "{"):
            malformed = copy.deepcopy(valid)
            malformed["tool_calls"][0]["function"]["arguments"] = raw
            with self.subTest(raw=raw), self.assertRaises(FormatError):
                action(malformed, {}, "tool_calls", requested=True)
        mixed = copy.deepcopy(valid)
        mixed["tool_calls"] += call("bash", {"command": "evil"})["tool_calls"]
        for message, requested in (
            (valid, False),
            (mixed, True),
            ({"tool_calls": None}, True),
        ):
            with self.assertRaises(FormatError):
                action(message, {}, "tool_calls", requested=requested)


if __name__ == "__main__":
    unittest.main()
