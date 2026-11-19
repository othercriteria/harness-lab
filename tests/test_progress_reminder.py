"""Test pacing decisions on the original attempt clock, through a checkpoint boundary."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from progress_reminder import ProgressReminder


class ReminderTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.receipt = self.root / "progress-reminder-001.json"
        limits = {
            "time_budget_feedback": True,
            "structured_finalization": True,
            "context_policy": {"mode": "none"},
            "progress_reminder": {
                "after_elapsed_agent_fraction": 0.25,
                "min_remaining_agent_seconds": 30,
            },
        }
        self.environment = SimpleNamespace(calls=1, agent_deadline=1100)
        self.model = SimpleNamespace(calls=2, completion_tokens=70)
        self.reminder = ProgressReminder(self.root, limits, self.environment)
        self.reminder.start(1100, 100)
        self.messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Task"},
        ]

    def query_at(self, when, **kwargs):
        with patch("progress_reminder.time.monotonic", return_value=when):
            return self.reminder.before_query(self.messages, self.model, **kwargs)

    def cycle(self):
        ident = str(self.reminder.cycles + 1)
        action = {"role": "assistant", "tool_calls": [{"id": ident}]}
        observation = {"role": "tool", "tool_call_id": ident, "content": "ok"}
        self.messages.extend([action, observation])
        self.reminder.completed_cycle(action, [observation])

    def test_retry_and_pending_checkpoint_do_not_consume_one_time_reminder(self):
        self.cycle()
        self.assertFalse(self.query_at(1024))
        self.assertFalse(self.query_at(1025))  # Same completed cycle.
        self.cycle()
        self.assertFalse(self.query_at(1026, checkpoint_pending=True))
        self.assertFalse(self.receipt.exists())
        self.assertTrue(self.query_at(1027))
        receipt = json.loads(self.receipt.read_bytes())
        self.assertEqual(receipt["notice"], self.messages[-1])
        self.assertEqual(receipt["timing"]["remaining_agent_seconds"], 73)
        self.assertEqual(receipt["timing"]["overshoot_seconds"], 2)
        self.assertEqual(
            (
                receipt["model_calls"],
                receipt["completion_tokens"],
                receipt["tool_calls"],
            ),
            (2, 70, 1),
        )
        self.assertEqual(self.environment.agent_deadline, 1100)
        self.cycle()
        self.assertFalse(self.query_at(1050))

    def test_completed_reset_takes_precedence_over_due_reminder(self):
        self.cycle()
        before = list(self.messages)
        self.assertFalse(self.query_at(1050, reset_applied=True))
        record = json.loads(self.receipt.read_bytes())
        self.assertEqual(record["status"], "bypassed")
        self.assertEqual(record["reason"], "fresh-context reset takes precedence")
        self.assertIsNone(record["notice"])
        self.assertEqual(self.messages, before)
        self.cycle()
        self.assertFalse(self.query_at(1060))

    def test_insufficient_remaining_time_keeps_original_view(self):
        self.cycle()
        self.assertFalse(self.query_at(1071))
        record = json.loads(self.receipt.read_bytes())
        self.assertEqual(record["reason"], "minimum remaining time")
        self.assertEqual(record["timing"]["remaining_agent_seconds"], 29)
        self.assertIsNone(record["notice"])
