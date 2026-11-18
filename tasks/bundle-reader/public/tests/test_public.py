import hashlib
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

from bundle_reader import BundleError, BundleInfo, FileRecord, extract_bundle, inspect_bundle


def archive(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for name, content in entries:
            output.writestr(name, content)
    return stream.getvalue()


class PublicTests(unittest.TestCase):
    def test_inspection_and_extraction(self):
        data = archive([("empty/", b""), ("docs/a.txt", b"hello"), ("z", b"\x00\xff")])
        expected = BundleInfo(
            (FileRecord("docs/a.txt", 5, hashlib.sha256(b"hello").hexdigest()),
             FileRecord("z", 2, hashlib.sha256(b"\x00\xff").hexdigest())),
            ("docs", "empty"), 7)
        self.assertEqual(inspect_bundle(data), expected)
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "output"
            self.assertEqual(extract_bundle(data, destination), expected)
            self.assertEqual((destination / "docs/a.txt").read_bytes(), b"hello")
            self.assertEqual((destination / "z").read_bytes(), b"\x00\xff")
            self.assertEqual(list((destination / "empty").iterdir()), [])

    def test_invalid_path_creates_nothing(self):
        data = archive([("safe.txt", b"okay"), ("../escape", b"bad")])
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "output"
            with self.assertRaises(BundleError):
                extract_bundle(data, destination)
            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_inclusive_limits(self):
        data = archive([("a", b"ab"), ("b", b"cd")])
        self.assertEqual(inspect_bundle(data, max_files=2, max_file_bytes=2,
                                        max_total_bytes=4).total_bytes, 4)
        for limits in [{"max_files": 1}, {"max_file_bytes": 1}, {"max_total_bytes": 3}]:
            with self.subTest(limits=limits), self.assertRaises(BundleError):
                inspect_bundle(data, **limits)

    def test_existing_destination_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "output"
            destination.mkdir()
            sentinel = destination / "keep"
            sentinel.write_bytes(b"unchanged")
            with self.assertRaises(BundleError):
                extract_bundle(archive([("a", b"new")]), destination)
            self.assertEqual(sentinel.read_bytes(), b"unchanged")
            self.assertEqual(list(destination.iterdir()), [sentinel])
