"""Replay native read receipts against the snapshot, model call and visible context."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import read_file
from observations import ObservationHistory
from read_file_evidence import verify_reads


class ReadAuditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.workspace = self.root / "workspaces/0000"
        self.workspace.mkdir(parents=True)
        self.history = ObservationHistory(self.root, {"mode": "none"}, expose_ids=True)
        self.limits = {
            "read_file": True,
            "deduplicate_file_reads": True,
            "step_limit": 2,
        }

    def save(self, name, value):
        (self.root / name).write_text(json.dumps(value))

    def log_read(self, index, raw, visible, messages=(), call_type="function"):
        arguments = read_file.validate({"path": "notes"})
        identifier = f"call-{index}"
        prefix = f"tool-{index:03d}"
        self.save(
            prefix + ".request.json",
            {
                "name": "read_file",
                "mode": "adapter-read",
                "executed": False,
                "model_request": index,
                "workspace_generation": "0000",
                "tool_call_id": identifier,
                "arguments": arguments,
            },
        )
        self.save(
            prefix + ".result.json",
            {
                "executed": False,
                "read_only": True,
                "cleanup_required": False,
                "visible": visible,
                "ok": visible["returncode"] == 0,
                "wall_seconds": 0.01,
            },
        )
        self.save(f"request-{index:03d}.request.json", {"messages": messages})
        call = {
            "type": call_type,
            "id": identifier,
            "function": {"name": "read_file", "arguments": raw},
        }
        self.save(
            f"request-{index:03d}.response.bin",
            {
                "choices": [
                    {"finish_reason": "tool_calls", "message": {"tool_calls": [call]}}
                ]
            },
        )

    def repeated_read(self, text, *, plain=True):
        (self.workspace / "notes").write_bytes(text.encode())
        raw = '{"path":"/workspace/notes"}'
        result = read_file.read(self.workspace, {"path": "notes"})
        self.log_read(1, raw, result)
        message = {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": json.dumps(result),
        }
        self.history.record(message, "read_file notes", plain_text=plain)
        notice = (
            "Unchanged requested range is already in your current context at o0001."
            " Use reread=true to receive the text again."
        )
        result["output"] = notice
        result["file_read"].update(
            contents_returned=False, context_observation_id="o0001"
        )
        self.log_read(2, raw, result, self.history.wire([message]))
        return len(text) - len(notice)

    def test_mixed_newlines_remain_visible_for_duplicate(self):
        avoided = self.repeated_read("café\r\nend\r" * 40)
        rows = verify_reads(self.root, self.limits)["reads"]
        self.assertEqual(
            [(r["suppressed"], r["characters_avoided"]) for r in rows],
            [(False, 0), (True, avoided)],
        )

    def test_newline_only_archive_change_invalidates_duplicate(self):
        self.repeated_read("notes\n" * 40)
        archive = self.history.root / "o0001.message.txt"
        archive.write_bytes(archive.read_bytes().replace(b"\n", b"\r\n"))
        with self.assertRaisesRegex(ValueError, "integrity mismatch"):
            verify_reads(self.root, self.limits)

    def test_json_archive_and_actual_outgoing_context(self):
        self.repeated_read("é\r\n" * 100, plain=False)
        self.assertTrue(verify_reads(self.root, self.limits)["reads"][1]["suppressed"])
        self.save("request-002.request.json", {"messages": []})
        with self.assertRaisesRegex(ValueError, "absent from actual model context"):
            verify_reads(self.root, self.limits)

    def test_replays_unsuccessful_read_and_detects_snapshot_change(self):
        missing = read_file.read(self.workspace, {"path": "notes"})
        self.log_read(1, '{"path":"notes"}', missing)
        self.assertEqual(len(verify_reads(self.root, self.limits)["reads"]), 1)
        (self.workspace / "notes").write_text("new")
        with self.assertRaisesRegex(ValueError, "differs from immutable"):
            verify_reads(self.root, self.limits)

    def test_read_audit_skips_other_tools_and_rejects_undeclared_reads(self):
        self.save("tool-001.request.json", {"name": "bash"})
        self.assertEqual(verify_reads(self.root, {})["reads"], [])
        missing = read_file.read(self.workspace, {"path": "notes"})
        self.log_read(2, '{"path":"notes"}', missing)
        with self.assertRaisesRegex(ValueError, "Undeclared read_file"):
            verify_reads(self.root, {})

    def test_duplicate_requires_attempt_local_regular_archive(self):
        self.repeated_read("notes\n" * 40)
        archive = self.history.root / "o0001.message.txt"
        archive.rename(self.root / "copy")
        archive.symlink_to(self.root / "copy")
        with self.assertRaisesRegex(ValueError, "Invalid observation message file"):
            verify_reads(self.root, self.limits)
        manifest = {"observations": list(self.history.records.values())}
        manifest["observations"][0]["message_file"] = "../copy"
        self.save("observations/manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "Invalid observation message filename"):
            verify_reads(self.root, self.limits)

    def test_model_response_must_be_a_bounded_local_artifact(self):
        missing = read_file.read(self.workspace, {"path": "notes"})
        self.log_read(1, '{"path":"notes"}', missing)
        response = self.root / "request-001.response.bin"
        copy = self.root / "copy"
        response.rename(copy)
        response.symlink_to(copy)
        with self.assertRaisesRegex(ValueError, "Invalid read evidence artifact"):
            verify_reads(self.root, self.limits)
        response.unlink()
        with response.open("wb") as stream:
            stream.truncate(4 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(ValueError, "Invalid read evidence artifact"):
            verify_reads(self.root, self.limits)

    def test_recorded_calls_must_be_accepted_by_live_parser(self):
        missing = read_file.read(self.workspace, {"path": "notes"})
        for raw, kind, error in [
            ('{"path":"other","path":"notes"}', "function", "Duplicate JSON field"),
            (" " * 8192 + '{"path":"notes"}', "function", "8192 bytes"),
            ('{"path":"notes"}', "other", "association mismatch"),
        ]:
            with self.subTest(error=error):
                self.log_read(1, raw, missing, call_type=kind)
                with self.assertRaisesRegex(ValueError, error):
                    verify_reads(self.root, self.limits)
