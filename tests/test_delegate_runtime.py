"""Registration must verify the environment that the detached job will launch."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from delegate_artifacts import create_snapshot, digest, encoded
from delegate_package import file_manifest, sha, verify_package


class RuntimeBindingTests(unittest.TestCase):
    def test_checkout_relocation_and_external_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, active = (root / name / ".venv" for name in ("archive", "public"))
            external = root / "backend"
            external.write_bytes(b"backend")
            for env in (old, active):
                (env / "bin").mkdir(parents=True)
                (env / "bin/python").write_bytes(b"interpreter")
                (env / "module.py").write_bytes(b"module")
            stage = root / "packages" / "stage"
            (stage / "runtime").mkdir(parents=True)
            (stage / "runtime/.venv").symlink_to(active)
            snapshot = create_snapshot(root, ["backend"], ["backend"], stage / "source")
            record = {
                "files": file_manifest(stage),
                "snapshot_id": snapshot["snapshot_id"],
                "venv": str(active),
                "runtime_dependencies": {
                    str(p): sha(p) for p in (old / "bin/python", old / "module.py", external)
                },
            }
            identifier = digest(encoded(record))
            (stage / "package.json").write_text(json.dumps(record))
            stage.rename(stage.with_name(identifier))

            (active / "module.py").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "Changed harness dependency"):
                verify_package(identifier, root)
            (active / "module.py").write_bytes(b"module")
            old.rename(root / "unavailable")
            self.assertEqual(verify_package(identifier, root)[1], record)
            external.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "Changed harness dependency"):
                verify_package(identifier, root)
