"""Read reuse depends on both workspace identity and the actual outgoing context."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import evidence
import read_file
from observations import ObservationHistory


class ReadObservationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.file = self.root / "notes"
        self.file.write_text("first\n" + "é" * 1200 + "\n")
        self.history = ObservationHistory(
            self.root,
            {
                "mode": "recoverable",
                "keep_recent": 1,
                "trigger_tokens": 100,
                "safety_tokens": 16,
            },
            expose_ids=True,
        )

    def read(self, start):
        return read_file.read(
            self.root, {"path": "notes", "start_line": start, "max_lines": 1}
        )

    def record(self, result):
        message = {"role": "tool", "content": json.dumps(result)}
        self.history.record(message, "read_file notes", plain_text=True)
        return message

    def test_same_visible_range_requires_current_message_and_current_file_identity(
        self,
    ):
        result = self.read(1)
        message = self.record(result)
        meta = result["file_read"]
        self.assertIsNone(self.history.prior_file_read(meta))
        self.history.note_current_context([message])
        self.assertEqual(
            self.history.prior_file_read(meta), message["extra"]["observation_id"]
        )
        self.assertIsNone(self.history.prior_file_read(self.read(2)["file_read"]))
        self.file.write_text("first\nchanged off screen\n")
        updated = self.read(1)
        self.assertEqual(updated["output"], result["output"])
        self.assertIsNone(self.history.prior_file_read(updated["file_read"]))
        self.history.note_current_context(
            [{"role": "user", "content": message["content"]}]
        )
        self.assertIsNone(self.history.prior_file_read(meta))

    def test_clipped_read_cannot_stand_in_for_the_requested_range(self):
        self.file.write_text("a" * (read_file.MAX_OUTPUT_CHARS + 1))
        clipped = self.read(1)
        message = self.record(clipped)
        self.history.note_current_context([message])
        self.assertTrue(clipped["file_read"]["range_clipped"])
        self.assertIsNone(self.history.prior_file_read(clipped["file_read"]))

    def test_masked_read_remains_citable_but_cannot_supply_a_duplicate(self):
        large = self.read(2)
        old, recent = self.record(large), self.record(self.read(1))
        old_id = old["extra"]["observation_id"]
        recent_id = recent["extra"]["observation_id"]

        # Use character counts as a deterministic stand-in for backend token counts.
        def meter(payload, phase):
            return sum(len(m["content"]) for m in payload["messages"])

        request, stats = self.history.prepare(
            [old, recent], {"max_tokens": 200}, meter, 4096
        )
        self.assertEqual(stats["newly_masked"], [old_id])
        self.assertEqual(stats["protected_recent"], [recent_id])
        self.assertGreater(stats["tokens_reclaimed_this_request"], 0)
        placeholder, latest = request["messages"]
        notice = json.loads(placeholder["content"])
        self.assertEqual(notice["historical_observation"], old_id)
        self.assertEqual(latest["content"], recent["content"])
        self.history.note_current_context(request["messages"])
        self.assertIsNone(self.history.prior_file_read(large["file_read"]))

        self.assertEqual(notice["displayed_output_file"], f"/observations/{old_id}.txt")
        archived = self.history.root / f"{old_id}.txt"
        self.assertEqual(archived.read_text(), large["output"])
        citation = [{"kind": "observation", "observation_id": old_id}]
        self.assertEqual(
            evidence.resolve(citation, self.history)[0]["original_visible"],
            old["content"],
        )
        view = json.loads(evidence.render(citation, self.history))
        self.assertEqual(view["status"], "historical_only")
        self.assertEqual(view["observations"][0]["observation_id"], old_id)
        self.assertTrue(view["observations"][0]["excerpt_clipped"])
