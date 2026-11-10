import builtins
import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fileindex.catalog import diff_catalogs, load_catalog, save_catalog
from fileindex.cli import main
from fileindex.scanner import scan_tree


def entry(digest="a" * 64, size=1, mtime=1):
    return {"size": size, "mtime_ns": mtime, "sha256": digest}


def catalog(files=None):
    return {"version": 1, "files": files or {}}


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "root"
        self.root.mkdir()
        self.dest = self.base / "catalog.json"

    def test_nested_binary_hidden_symlinks(self):
        (self.root / "z").mkdir()
        (self.root / "z/b").write_bytes(bytes(range(256)))
        (self.root / ".hidden").write_bytes(b"")
        (self.root / "link").symlink_to(self.root / "z/b")
        (self.root / "dirlink").symlink_to(self.root / "z", target_is_directory=True)
        result = scan_tree(self.root)
        self.assertEqual(list(result["files"]), [".hidden", "z/b"])
        self.assertEqual(
            result["files"]["z/b"]["sha256"],
            hashlib.sha256(bytes(range(256))).hexdigest(),
        )
        self.assertEqual(
            result["files"][".hidden"]["sha256"], hashlib.sha256(b"").hexdigest()
        )

    def test_invalid_root(self):
        with self.assertRaises((ValueError, OSError)):
            scan_tree(self.root / "missing")
        alias = self.base / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            scan_tree(alias)

    def test_reuse_without_open_and_no_mutation(self):
        p = self.root / "a"
        p.write_bytes(b"first")
        previous = scan_tree(self.root)
        before = copy.deepcopy(previous)
        with (
            patch("builtins.open", side_effect=AssertionError("unexpected open")),
            patch.object(Path, "open", side_effect=AssertionError("unexpected open")),
        ):
            current = scan_tree(self.root, previous)
        self.assertEqual(previous, before)
        self.assertEqual(current, previous)
        current["files"]["a"]["size"] = 999
        self.assertEqual(previous, before)

    def test_metadata_invalidates_and_deleted_disappears(self):
        p = self.root / "a"
        p.write_bytes(b"one")
        (self.root / "gone").write_bytes(b"x")
        old = scan_tree(self.root)
        p.write_bytes(b"two")
        now = old["files"]["a"]["mtime_ns"] + 1_000_000_000
        os.utime(p, ns=(now, now))
        (self.root / "gone").unlink()
        new = scan_tree(self.root, old)
        self.assertEqual(
            diff_catalogs(old, new),
            {"added": [], "removed": ["gone"], "changed": ["a"]},
        )
        p.write_bytes(b"three")
        os.utime(p, ns=(now, now))
        self.assertNotEqual(
            scan_tree(self.root, new)["files"]["a"]["sha256"],
            new["files"]["a"]["sha256"],
        )

    def test_digest_only_diff_sorted(self):
        old = catalog({"z": entry(), "b": entry(), "same": entry()})
        new = catalog(
            {
                "new2": entry(),
                "new1": entry(),
                "b": entry("b" * 64),
                "same": entry(size=8, mtime=9),
            }
        )
        before = copy.deepcopy((old, new))
        self.assertEqual(
            diff_catalogs(old, new),
            {"added": ["new1", "new2"], "removed": ["z"], "changed": ["b"]},
        )
        self.assertEqual((old, new), before)

    def test_schema_validation_at_all_boundaries(self):
        invalid = [
            {},
            catalog({"../escape": entry()}),
            catalog({"/abs": entry()}),
            catalog({"a//b": entry()}),
            catalog({"a\\b": entry()}),
            catalog({"a": entry(size=True)}),
            catalog({"a": entry(mtime=-1)}),
            catalog({"a": entry("A" * 64)}),
            {"version": True, "files": {}},
            {"version": 2, "files": {}},
            {"version": 1, "files": {}, "extra": 0},
        ]
        for bad in invalid:
            with self.subTest(bad=bad):
                self.dest.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    load_catalog(self.dest)
                with self.assertRaises(ValueError):
                    scan_tree(self.root, bad)
                with self.assertRaises(ValueError):
                    diff_catalogs(catalog(), bad)
                with self.assertRaises(ValueError):
                    diff_catalogs(bad, catalog())
                before = self.dest.read_bytes()
                with self.assertRaises(ValueError):
                    save_catalog(self.dest, bad)
                self.assertEqual(self.dest.read_bytes(), before)
        self.dest.write_text("{bad")
        with self.assertRaises(ValueError):
            load_catalog(self.dest)

    def test_atomic_replace_failure_preserves_bytes_and_cleans(self):
        self.dest.write_text("old bytes")
        before = set(self.base.iterdir())
        for target, failure in (
            ("os.replace", OSError("disk failure")),
            ("json.dump", OSError("write failed")),
            ("json.dump", TypeError("serialization failed")),
        ):
            with patch(target, side_effect=failure):
                with self.assertRaises(type(failure)):
                    save_catalog(self.dest, catalog({"a": entry()}))
            self.assertEqual(self.dest.read_text(), "old bytes")
            self.assertEqual(set(self.base.iterdir()), before)
        save_catalog(self.dest, catalog({"a": entry()}))
        self.assertEqual(load_catalog(self.dest), catalog({"a": entry()}))

    def test_chunked_hashing_and_io_propagation(self):
        target = self.root / "big"
        content = b"x" * 200000
        target.write_bytes(content)
        original = io.open

        class Bounded:
            def __init__(self, f):
                self.f = f

            def __enter__(self):
                self.f.__enter__()
                return self

            def __exit__(self, *args):
                return self.f.__exit__(*args)

            def read(self, n=-1):
                if not 0 < n <= 65536:
                    raise AssertionError("unbounded read")
                return self.f.read(n)

            def __getattr__(self, k):
                return getattr(self.f, k)

        def opened(path, *args, **kwargs):
            f = original(path, *args, **kwargs)
            return Bounded(f) if Path(path) == target else f

        with (
            patch("io.open", side_effect=opened),
            patch.object(builtins, "open", side_effect=opened),
        ):
            self.assertEqual(
                scan_tree(self.root)["files"]["big"]["sha256"],
                hashlib.sha256(content).hexdigest(),
            )
        with (
            patch.object(Path, "open", side_effect=PermissionError("denied")),
            patch("builtins.open", side_effect=PermissionError("denied")),
            patch("io.open", side_effect=PermissionError("denied")),
        ):
            with self.assertRaises(OSError):
                scan_tree(self.root)

    def test_cli_dry_run_and_commit(self):
        (self.root / "a").write_text("a")
        out = io.StringIO()
        with redirect_stdout(out):
            rc = main([str(self.root), str(self.dest), "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertFalse(self.dest.exists())
        self.assertEqual(
            json.loads(out.getvalue()), {"added": ["a"], "removed": [], "changed": []}
        )
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(self.root), str(self.dest)]), 0)
        before = self.dest.read_bytes()
        (self.root / "a").unlink()
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main([str(self.root), str(self.dest), "--dry-run"]), 0)
        self.assertEqual(json.loads(out.getvalue())["removed"], ["a"])
        self.assertEqual(self.dest.read_bytes(), before)

    def test_cli_failure_before_success_output(self):
        (self.root / "a").write_text("a")
        save_catalog(self.dest, catalog())
        before = self.dest.read_bytes()
        out, err = io.StringIO(), io.StringIO()
        with (
            patch("os.replace", side_effect=OSError("disk failure")),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            rc = main([str(self.root), str(self.dest)])
        self.assertEqual(rc, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("disk failure", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        self.assertEqual(self.dest.read_bytes(), before)
