import copy
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from fileindex.scanner import scan_tree


class ContractExamples(unittest.TestCase):
    def test_regular_files_only_sorted_including_empty_and_dotfiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'root'
            root.mkdir()
            (root / 'z').write_bytes(b'z')
            (root / '.hidden').write_bytes(b'')
            (root / 'sub').mkdir()
            (root / 'sub' / 'a').write_bytes(b'a')
            (root / 'file_link').symlink_to(root / 'z')
            (root / 'dir_link').symlink_to(root / 'sub', target_is_directory=True)
            result = scan_tree(root)
            self.assertEqual(list(result['files']), ['.hidden', 'sub/a', 'z'])
            self.assertEqual(result['files']['.hidden']['sha256'], hashlib.sha256(b'').hexdigest())
            link_root = Path(tmp) / 'root_link'
            link_root.symlink_to(root, target_is_directory=True)
            with self.assertRaises((ValueError, OSError)):
                scan_tree(link_root)

    def test_reuse_metadata_pair_then_rehash_same_size_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'entry'
            path.write_bytes(b'old')
            previous = scan_tree(tmp)
            # The previous digest is authoritative when size AND mtime match.
            # A distinct valid digest makes reuse observable without depending
            # on a particular file-opening implementation.
            previous['files']['entry']['sha256'] = 'a' * 64
            original = copy.deepcopy(previous)
            reused = scan_tree(tmp, previous)
            self.assertEqual(reused['files']['entry']['sha256'], 'a' * 64)
            self.assertEqual(previous, original)
            old_mtime = previous['files']['entry']['mtime_ns']
            path.write_bytes(b'new')
            os.utime(path, ns=(old_mtime + 2_000_000_000, old_mtime + 2_000_000_000))
            changed = scan_tree(tmp, previous)
            self.assertEqual(changed['files']['entry']['sha256'], hashlib.sha256(b'new').hexdigest())
            self.assertEqual(previous, original)
            path.unlink()
            self.assertEqual(scan_tree(tmp, previous), {'version': 1, 'files': {}})
