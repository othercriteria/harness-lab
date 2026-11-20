"""Worker edit and write contracts, exercised on disposable workspace files."""

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import edit_file
import sandbox_worker as worker
import write_file


class FileMutationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.enterContext(patch.object(worker, "WORKSPACE", self.root))
        self.file = self.root / "notes"

    def write(self, content, path="notes"):
        args = {"path": path, "content": content}
        call = {"id": "w", "function": {"arguments": json.dumps(args)}}
        return worker.write_file(write_file.action(call)["arguments"])

    def edit(self, old, new, path="notes"):
        args = {"path": path, "old_text": old, "new_text": new}
        call = {"id": "e", "function": {"arguments": json.dumps(args)}}
        return worker.edit_file(edit_file.action(call)["arguments"])

    def test_create_empty_then_rewrite_and_edit_exact_bytes(self):
        self.assertEqual(
            self.write(""),
            {
                "ok": True,
                "changed": True,
                "created": True,
                "path": "notes",
                "before_bytes": 0,
                "after_bytes": 0,
            },
        )
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o644)
        self.file.chmod(0o751)
        source = "\ufeffcafé\r\nend"
        result = self.write(source, str(self.file))
        self.assertFalse(result["created"])
        self.assertEqual(result["after_bytes"], len(source.encode()))
        self.assertEqual(self.file.read_bytes(), source.encode())
        result = self.edit("fé", "", "./notes")
        self.assertEqual(
            result,
            {
                "ok": True,
                "changed": True,
                "path": "notes",
                "matches": 1,
                "before_bytes": len(source.encode()),
                "after_bytes": len("\ufeffca\r\nend".encode()),
            },
        )
        self.assertEqual(self.file.read_bytes(), "\ufeffca\r\nend".encode())
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o751)

    def test_no_op_preserves_file_identity(self):
        self.file.write_bytes(b"old")
        before = self.file.stat()
        for result in (self.edit("old", "old"), self.write("old")):
            self.assertFalse(result["changed"])
        after = self.file.stat()
        self.assertEqual(
            (after.st_ino, after.st_mtime_ns), (before.st_ino, before.st_mtime_ns)
        )

    def test_nonunique_and_missing_matches_leave_bytes_alone(self):
        self.file.write_bytes(b"aaa")
        for old, count in [("aa", 2), ("b", 0)]:
            with self.subTest(old=old), self.assertRaises(worker.EditError) as caught:
                self.edit(old, "x")
            self.assertEqual(caught.exception.details["code"], "MATCH_COUNT")
            self.assertEqual(caught.exception.details["actual"], count)
            self.assertEqual(self.file.read_bytes(), b"aaa")

    def test_directory_spelling_never_targets_a_regular_file(self):
        for path in (
            "notes/",
            "notes/.",
            "missing/../notes",
            "notes/../notes",
            # Even if the normalized destination is inside, the walk must stay inside.
            f"../{self.root.name}/notes",
        ):
            for tool, args in ((self.write, ("new",)), (self.edit, ("old", "new"))):
                with self.subTest(path=path, tool=tool.__name__):
                    self.file.write_bytes(b"old")
                    with self.assertRaises(worker.EditError):
                        tool(*args, path=path)
                    self.assertEqual(self.file.read_bytes(), b"old")
        with self.assertRaises(worker.EditError):
            self.write("new", "new-directory/")
        self.assertFalse((self.root / "new-directory").exists())

    def test_existing_parent_can_be_traversed_in_either_spelling(self):
        (self.root / "sub").mkdir()
        self.write("old", "sub/../notes")
        self.edit("old", "new", str(self.root / "sub" / ".." / "notes"))
        self.assertEqual(self.file.read_bytes(), b"new")

    def test_target_and_input_byte_limits(self):
        text = "é" * (worker.WRITE_TEXT_BYTES // 2)
        self.assertEqual(self.write(text)["after_bytes"], worker.WRITE_TEXT_BYTES)
        for operation, code in [
            (lambda: self.write(text + "a"), "WRITE_TOO_LARGE"),
            (lambda: self.edit("é", text), "EDIT_TOO_LARGE"),
            (lambda: self.edit("", "new"), "EMPTY_OLD_TEXT"),
        ]:
            with self.assertRaises(worker.EditError) as caught:
                operation()
            self.assertEqual(caught.exception.details["code"], code)
        self.assertEqual(self.file.read_bytes(), text.encode())
        full = b"x" + b"a" * (worker.EDIT_FILE_BYTES - 1)
        self.file.write_bytes(full)
        with self.assertRaises(worker.EditError) as caught:
            self.edit("x", "xx")
        self.assertEqual(caught.exception.details["code"], "FILE_TOO_LARGE")
        self.assertEqual(self.file.read_bytes(), full)
        self.assertTrue(self.edit("x", "y")["changed"])

    def test_uneditable_file_is_preserved(self):
        for data, code in [
            (b"\xff", "NOT_UTF8"),
            (b"x" * (worker.EDIT_FILE_BYTES + 1), "FILE_TOO_LARGE"),
        ]:
            self.file.write_bytes(data)
            for operation in (lambda: self.edit("x", "y"), lambda: self.write("new")):
                with self.assertRaises(worker.EditError) as caught:
                    operation()
                self.assertEqual(caught.exception.details["code"], code)
                self.assertEqual(self.file.read_bytes(), data)

    def test_missing_target_and_missing_parent(self):
        with self.assertRaises(worker.EditError) as caught:
            self.edit("old", "new")
        self.assertEqual(caught.exception.details["code"], "IO_ERROR")
        with self.assertRaises(worker.EditError) as caught:
            self.write("new", "missing/notes")
        self.assertEqual(caught.exception.details["code"], "PARENT_NOT_FOUND")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_file_links_and_directories_are_never_replaced(self):
        self.file.write_bytes(b"old")
        (self.root / "link").symlink_to(self.file)
        (self.root / "dir").mkdir()
        for name in ("link", "dir"):
            for tool, args in ((self.write, ("new",)), (self.edit, ("old", "new"))):
                with (
                    self.subTest(name=name, tool=tool.__name__),
                    self.assertRaises(worker.EditError),
                ):
                    tool(*args, path=name)
        self.assertTrue((self.root / "dir").is_dir())
        self.assertTrue((self.root / "link").is_symlink())
        self.assertEqual(self.file.read_bytes(), b"old")

    def test_invalid_arguments_fail_at_admission(self):
        for module, fields in (
            (write_file, {"content": "x"}),
            (edit_file, {"old_text": "x", "new_text": ""}),
        ):
            for args, code in [
                ({"path": "notes", **fields, "extra": ""}, "ARGUMENTS"),
                ({"path": 7, **fields}, "ARGUMENTS"),
                ({"path": "é" * 513, **fields}, "PATH_NOT_ALLOWED"),
                ({"path": "a\x00b", **fields}, "PATH_NOT_ALLOWED"),
                ({"path": "\udfff", **fields}, "NOT_UTF8"),
            ]:
                with (
                    self.subTest(tool=module.NAME, code=code),
                    self.assertRaises(worker.EditError) as caught,
                ):
                    module.parse(json.dumps(args))
                self.assertEqual(caught.exception.details["code"], code)
            for raw in ('{"path":"first","path":"second"}', " " * 262145):
                with self.subTest(tool=module.NAME), self.assertRaises(ValueError):
                    module.parse(raw)

    def test_failed_replace_preserves_destination_and_removes_temporary(self):
        self.file.write_bytes(b"old")
        for operation in (lambda: self.edit("old", "new"), lambda: self.write("new")):
            with patch.object(
                worker.os, "replace", side_effect=OSError("replace failed")
            ):
                with self.assertRaises(worker.EditError) as caught:
                    operation()
            self.assertEqual(caught.exception.details["code"], "IO_ERROR")
            self.assertEqual(self.file.read_bytes(), b"old")
            self.assertEqual(list(self.root.iterdir()), [self.file])
