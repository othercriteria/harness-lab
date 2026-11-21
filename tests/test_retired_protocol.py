"""Regression coverage for the retired protocol diagnostic in a public clone."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import protocol

PROJECT = Path(__file__).resolve().parents[1]


def write_protocol(root, name, data):
    directory = root / "configs" / "protocols"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.json").write_text(json.dumps(data))


class RetiredProtocolTests(unittest.TestCase):
    def test_false_split_metadata_is_inert(self):
        data = json.loads((PROJECT / "configs/pilot.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_protocol(root, "historical", {**data, "split_finalization": False})
            self.assertIs(
                protocol.load_protocol("historical", root=root)["split_finalization"],
                False,
            )

    def test_load_protocol_rejects_activated_retired_options(self):
        for data in (
            {"handoff_phase": False},
            {"split_finalization": True},
            {"split_finalization": 0},
            {"handoff_phase": {}, "split_finalization": True},
        ):
            with self.subTest(data=data), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                write_protocol(root, "retired", data)
                with self.assertRaises(ValueError) as caught:
                    protocol.load_protocol("retired", root=root)
                message = str(caught.exception)
                for option in data:
                    self.assertIn(option, message)
                self.assertIn("SNAPSHOT.md", message)
                self.assertIn("archived", message)
                self.assertIn("frozen", message)
                self.assertNotIn("harness-option-survey", message)

    def test_diagnostic_points_to_mapped_public_source(self):
        rows = (PROJECT / "docs/development-commits.tsv").read_text().splitlines()[1:]
        public_commit = dict(row.split("\t") for row in rows)[
            "6847e2237b4e77a3ede64e79e889ebb4b7d85968"
        ]
        with self.assertRaises(ValueError) as caught:
            protocol.reject_retired_options({"split_finalization": True})
        self.assertIn(
            f"git show {public_commit}:scripts/protocol.py", str(caught.exception)
        )
