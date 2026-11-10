import hashlib
import tempfile
import unittest
from pathlib import Path

from fileindex.catalog import diff_catalogs, load_catalog, save_catalog
from fileindex.scanner import scan_tree


class PublicTests(unittest.TestCase):
    def test_single_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_bytes(b"hello")
            cat = scan_tree(tmp)
            self.assertEqual(
                cat["files"]["a.txt"]["sha256"], hashlib.sha256(b"hello").hexdigest()
            )
            self.assertEqual(cat["files"]["a.txt"]["size"], 5)

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.json"
            empty = {"version": 1, "files": {}}
            self.assertEqual(load_catalog(path), empty)
            save_catalog(path, empty)
            self.assertEqual(load_catalog(path), empty)

    def test_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "x").write_text("x")
            self.assertEqual(
                diff_catalogs({"version": 1, "files": {}}, scan_tree(tmp))["added"],
                ["x"],
            )
