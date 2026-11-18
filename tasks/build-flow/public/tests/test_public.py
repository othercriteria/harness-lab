import tempfile
import unittest
from pathlib import Path

from buildflow.planner import plan
from buildflow.runner import run
from buildflow.state import load_state


class PublicTests(unittest.TestCase):
    def test_empty(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(plan({"version": 1, "steps": []}, root), [])

    def test_single(self):
        calls = []
        with tempfile.TemporaryDirectory() as root:
            result = run(
                {"version": 1, "steps": [{"id": "a", "command": ["true"]}]},
                root,
                lambda name, command: calls.append((name, command)) or 0,
            )
        self.assertEqual(result["statuses"], {"a": "succeeded"})
        self.assertEqual(calls, [("a", ["true"])])

    def test_missing_state(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(
                load_state(Path(root) / "missing"), {"version": 1, "completed": {}}
            )
