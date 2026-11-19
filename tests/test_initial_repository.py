"""Tests for build_task in scripts/initial_repository.py.

Covers the in-budget preload (contents and hashes), the file-count overflow,
and the JSON-rendered byte overflow (raw data fits, rendered payload does not).
"""

import hashlib
import importlib.util
import json
import pathlib
import tempfile
import unittest

# Load the module under test by path so the suite runs with `python -B -S`
# (no site, no package import machinery beyond the standard library).
_MODULE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "initial_repository.py"
)
_spec = importlib.util.spec_from_file_location("initial_repository", _MODULE_PATH)
initial_repository = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(initial_repository)

BRIEF = "Do the thing.\n"


def _make_tree(root, files):
    """Create root/public/task.md (BRIEF) plus files {relpath: bytes}."""
    public = root / "public"
    public.mkdir(parents=True)
    (public / "task.md").write_bytes(BRIEF.encode("utf-8"))
    for rel, data in files.items():
        path = public / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return public


class BuildTaskTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.task = pathlib.Path(self._tmp.name)

    def test_in_budget_preload_shows_contents_and_hashes_original_bytes(self):
        files = {
            "notes.md": b"alpha\nbeta\n",
            "src/app.py": b"print('gamma')\n",
            "data.json": b'{"ok": true}\n',
        }
        _make_tree(self.task, files)
        policy = {"max_files": 8, "max_bytes": 4096}
        message, receipt = initial_repository.build_task(self.task, policy)

        # The brief leads the message; the file contents are visible as the
        # JSON payload (escaped, so compare via a round-trip, not substrings).
        self.assertTrue(message.startswith(BRIEF))

        # The JSON payload is the complete set of files, verbatim.
        payload = message.rsplit("\n", 1)[1]
        self.assertEqual(
            json.loads(payload),
            {name: data.decode("utf-8") for name, data in files.items()},
        )

        # The receipt hashes the original bytes and reports the real sizes.
        self.assertTrue(receipt["included"])
        self.assertEqual(
            receipt["files"],
            {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        )
        self.assertEqual(receipt["raw_bytes"], sum(len(d) for d in files.values()))
        self.assertEqual(receipt["rendered_bytes"], len(payload.encode("utf-8")))
        self.assertEqual(
            receipt["task_text_sha256"],
            hashlib.sha256(message.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(receipt["policy"], policy)

    def test_exceeding_file_count_returns_brief_only(self):
        files = {f"file{i}.txt": b"x\n" for i in range(3)}
        _make_tree(self.task, files)
        policy = {"max_files": 2, "max_bytes": 4096}
        message, receipt = initial_repository.build_task(self.task, policy)

        # Exactly the original brief, no partial selection, and the reason is stated.
        self.assertEqual(message, BRIEF)
        self.assertFalse(receipt["included"])
        self.assertEqual(receipt["reason"], "max_files")
        self.assertEqual(receipt["files"], {})
        self.assertEqual(receipt["raw_bytes"], 0)
        self.assertEqual(receipt["policy"], policy)

    def test_exceeding_byte_limit_after_json_rendering_returns_brief_only(self):
        # 506 raw double-quotes fit under max_bytes (506 <= 1024), but JSON
        # escapes each quote to \", so the rendered payload (1027 bytes)
        # exceeds the limit even though the raw data fits.
        files = {"pad.txt": b'"' * 506}
        public = _make_tree(self.task, files)
        policy = {"max_files": 8, "max_bytes": 1024}

        # Guard the discriminating premise: raw fits, rendered does not.
        raw_total = sum(
            p.stat().st_size
            for p in public.rglob("*")
            if p.is_file() and p != public / "task.md"
        )
        self.assertLessEqual(raw_total, policy["max_bytes"])
        rendered = json.dumps(
            {"pad.txt": files["pad.txt"].decode("utf-8")},
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertGreater(len(rendered.encode("utf-8")), policy["max_bytes"])

        message, receipt = initial_repository.build_task(self.task, policy)

        self.assertEqual(message, BRIEF)
        self.assertFalse(receipt["included"])
        self.assertEqual(receipt["reason"], "max_bytes")
        self.assertEqual(receipt["files"], {})
        self.assertEqual(receipt["raw_bytes"], 0)
        self.assertEqual(receipt["policy"], policy)


if __name__ == "__main__":
    unittest.main()
