import dataclasses
import hashlib
import io
from pathlib import Path
import stat
import struct
import tempfile
import unittest
import warnings
import zipfile
import zlib

from bundle_reader import BundleError, BundleInfo, FileRecord, extract_bundle, inspect_bundle


def zipped(entries, compression=zipfile.ZIP_STORED):
    stream = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(stream, "w", compression=compression) as output:
            for entry in entries:
                name, content, *mode = entry
                info = zipfile.ZipInfo(name)
                info.compress_type = compression
                info.external_attr = (mode[0] if mode else 0o600) << 16
                output.writestr(info, content)
    return stream.getvalue()


def patch_header(data, local_offset, central_offset, value):
    result = bytearray(data)
    struct.pack_into("<H", result, local_offset, value)
    central = result.index(b"PK\x01\x02")
    struct.pack_into("<H", result, central + central_offset, value)
    return bytes(result)


class Acceptance(unittest.TestCase):
    def test_empty_archive(self):
        data = zipped([])
        self.assertEqual(inspect_bundle(data), BundleInfo((), (), 0))
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "empty"
            self.assertEqual(extract_bundle(data, str(dest)), BundleInfo((), (), 0))
            self.assertTrue(dest.is_dir())
            self.assertEqual(list(dest.iterdir()), [])

    def test_result_types_hashes_and_immutability(self):
        payload = bytes(range(256))
        result = inspect_bundle(zipped([("b", payload), ("a", b"")]))
        self.assertEqual(result, BundleInfo((FileRecord("a", 0, hashlib.sha256(b"").hexdigest()),
                                            FileRecord("b", 256, hashlib.sha256(payload).hexdigest())), (), 256))
        self.assertIs(type(result.files), tuple)
        self.assertIs(type(result.directories), tuple)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.total_bytes = 9
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.files[0].path = "other"

    def test_order_and_compression_do_not_change_result(self):
        entries = [("z/c", b"one"), ("a/", b""), ("z/b", b"two")]
        self.assertEqual(inspect_bundle(zipped(entries)),
                         inspect_bundle(zipped(list(reversed(entries)), zipfile.ZIP_DEFLATED)))

    def test_unicode_and_spaces_are_literal(self):
        entries = [(" café /雪.txt", b"snow"), ("A", b"upper"), ("a", b"lower")]
        result = inspect_bundle(zipped(entries))
        self.assertEqual([f.path for f in result.files], sorted(e[0] for e in entries))
        self.assertEqual(result.directories, (" café ",))

    def test_explicit_and_implicit_directories(self):
        data = zipped([("a/b/c", b"value"), ("a/b/", b""), ("a/", b""), ("empty/deep/", b"")])
        self.assertEqual(inspect_bundle(data).directories, ("a", "a/b", "empty", "empty/deep"))

    def test_bad_paths(self):
        for name in ["/", "/abs", "a//b", "a/./b", "a/../b", "../up", "a\\b", "x:y", "a/:b", "a//"]:
            with self.subTest(name=name), self.assertRaises(BundleError):
                inspect_bundle(zipped([(name, b"")]))

    def test_original_nul_name_is_rejected(self):
        data = zipped([("badXname", b"data")]).replace(b"badXname", b"bad\x00name")
        with self.assertRaises(BundleError):
            inspect_bundle(data)

    def test_duplicate_explicit_paths(self):
        for entries in [[("x", b"a"), ("x", b"b")], [("x/", b""), ("x/", b"")]]:
            with self.subTest(entries=entries), self.assertRaises(BundleError):
                inspect_bundle(zipped(entries))

    def test_file_directory_conflicts_in_both_orders(self):
        for pair in [[("a", b"file"), ("a/", b"")],
                     [("a", b"file"), ("a/b", b"child")],
                     [("a/b", b"file"), ("a/b/c/", b"")]]:
            for entries in [pair, list(reversed(pair))]:
                with self.subTest(entries=entries), self.assertRaises(BundleError):
                    inspect_bundle(zipped(entries))

    def test_nonempty_directory(self):
        with self.assertRaises(BundleError):
            inspect_bundle(zipped([("dir/", b"payload")]))

    def test_type_bits_and_mismatches(self):
        for kind in [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFSOCK]:
            with self.subTest(kind=kind), self.assertRaises(BundleError):
                inspect_bundle(zipped([("entry", b"x", kind | 0o777)]))
        for name, kind in [("entry", stat.S_IFDIR), ("entry/", stat.S_IFREG)]:
            with self.subTest(name=name), self.assertRaises(BundleError):
                inspect_bundle(zipped([(name, b"", kind | 0o700)]))
        result = inspect_bundle(zipped([("d/", b"", stat.S_IFDIR | 0o700),
                                        ("d/f", b"x", stat.S_IFREG | 0o400),
                                        ("plain", b"y", 0o600)]))
        self.assertEqual(result.total_bytes, 2)

    def test_limits_are_inclusive_and_directories_do_not_count(self):
        data = zipped([("d/", b""), ("d/a", b"12"), ("b", b"34")], zipfile.ZIP_DEFLATED)
        self.assertEqual(inspect_bundle(data, max_files=2, max_file_bytes=2, max_total_bytes=4).total_bytes, 4)
        for limits in [{"max_files": 1}, {"max_file_bytes": 1}, {"max_total_bytes": 3}]:
            with self.subTest(limits=limits), self.assertRaises(BundleError):
                inspect_bundle(data, **limits)

    def test_argument_types_and_limit_validation(self):
        class BytesSubclass(bytes):
            pass
        valid = zipped([])
        for data in [bytearray(valid), memoryview(valid), BytesSubclass(valid), "", None]:
            with self.subTest(type=type(data).__name__), self.assertRaises(BundleError):
                inspect_bundle(data)
        for key in ["max_files", "max_file_bytes", "max_total_bytes"]:
            for value in [True, False, 0, -1, 1.5, "2", None]:
                with self.subTest(key=key, value=value), self.assertRaises(BundleError):
                    inspect_bundle(valid, **{key: value})

    def test_unsupported_compression_and_encryption(self):
        data = zipped([("a", b"content")])
        for invalid in [patch_header(data, 8, 10, 12), patch_header(data, 6, 8, 1)]:
            with self.assertRaises(BundleError):
                inspect_bundle(invalid)

    def test_malformed_and_corrupt_content(self):
        data = zipped([("a", b"payload")])
        for invalid in [b"not zip", data[:20], data.replace(b"payload", b"Payload", 1)]:
            with self.assertRaises(BundleError):
                inspect_bundle(invalid)

    def test_declared_length_cannot_hide_payload_suffix(self):
        for method in [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED]:
            data = bytearray(zipped([("a", b"abcdef")], method))
            central = data.index(b"PK\x01\x02")
            for offset in [22, central + 24]:
                struct.pack_into("<I", data, offset, 3)
            for offset in [14, central + 16]:
                struct.pack_into("<I", data, offset, zlib.crc32(b"abc"))
            with self.subTest(method=method), self.assertRaises(BundleError):
                inspect_bundle(bytes(data))

    def test_deflate_stream_must_end_at_compressed_span_boundary(self):
        original = zipped([("a", b"abcdef" * 20)], zipfile.ZIP_DEFLATED)
        original_central = original.index(b"PK\x01\x02")
        for delta in [-1, 1]:
            if delta == 1:
                data = bytearray(original[:original_central] + b"x" + original[original_central:])
            else:
                data = bytearray(original[:original_central-1] + original[original_central:])
            central = original_central + delta
            end = data.index(b"PK\x05\x06")
            for offset in [18, central+20]:
                value = struct.unpack_from("<I", data, offset)[0]
                struct.pack_into("<I", data, offset, value+delta)
            struct.pack_into("<I", data, end+16, central)
            with self.subTest(delta=delta), self.assertRaises(BundleError):
                inspect_bundle(bytes(data))

    def test_parser_accepted_prefix_trailing_bytes_and_int_subclass(self):
        class Limit(int):
            pass
        data = zipped([("a", b"x")])
        self.assertEqual(inspect_bundle(b"prefix" + data + b"trailing", max_files=Limit(1)),
                         inspect_bundle(data))

    def test_existing_destinations_and_bad_type(self):
        data = zipped([("a", b"payload")])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / "file"; file.write_bytes(b"sentinel")
            directory = root / "dir"; directory.mkdir()
            link = root / "link"; link.symlink_to(root / "absent")
            for dest in [file, directory, link]:
                with self.subTest(dest=dest.name), self.assertRaises(BundleError):
                    extract_bundle(data, dest)
            self.assertEqual(file.read_bytes(), b"sentinel")
            self.assertEqual(list(directory.iterdir()), [])
            self.assertTrue(link.is_symlink())
            for bad in [None, 7, b"target"]:
                with self.assertRaises(BundleError):
                    extract_bundle(data, bad)

    def test_all_validation_precedes_any_writes(self):
        invalids = [zipped([("good", b"x"), ("../bad", b"x")]),
                    zipped([("good", b"x"), ("dir/", b"notempty")]),
                    zipped([("good", b"x"), ("bad", b"x", stat.S_IFLNK | 0o777)])]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for data in invalids:
                with self.assertRaises(BundleError):
                    extract_bundle(data, root / "output")
                self.assertEqual(list(root.iterdir()), [])
            with self.assertRaises(BundleError):
                extract_bundle(zipped([("a", b"12")]), root / "output", max_total_bytes=1)
            self.assertEqual(list(root.iterdir()), [])

    def test_extracted_tree_and_inspection_agree(self):
        data = zipped([("root/d/file", b"\x00\xff\n"), ("empty/", b""), ("root/z", b"")])
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "output"
            info = extract_bundle(data, dest)
            self.assertEqual(info, inspect_bundle(data))
            paths = {str(p.relative_to(dest)): p for p in dest.rglob("*")}
            self.assertEqual(set(paths), {"root", "root/d", "root/d/file", "root/z", "empty"})
            self.assertFalse(any(p.is_symlink() for p in paths.values()))
            for record in info.files:
                content = paths[record.path].read_bytes()
                self.assertEqual((len(content), hashlib.sha256(content).hexdigest()),
                                 (record.size, record.sha256))
