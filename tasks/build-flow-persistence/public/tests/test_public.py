"""Small executable examples of the engine's normal workflow."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from buildflow.planner import plan
from buildflow.runner import run
from buildflow.state import load_state


class PublicTests(unittest.TestCase):
    def test_empty(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(plan({"version": 1, "steps": []}, root), [])

    def test_single(self):
        calls = []
        with tempfile.TemporaryDirectory() as root:
            result = run(
                {"version": 1, "steps": [{"id": "a", "command": ["true"]}]},
                root,
                lambda name, command: calls.append((name, command)) or 0,
            )
        self.assertEqual(result["statuses"], {"a": "succeeded"})
        self.assertEqual(calls, [("a", ["true"])])

    def test_missing_state(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(
                load_state(Path(root) / "missing"), {"version": 2, "completed": {}}
            )


class EngineExamples(unittest.TestCase):
    def test_generated_pipeline_reuses_then_invalidates_cache(self):
        data = {
            "version": 1,
            "steps": [
                {
                    "id": "prepare",
                    "command": ["prepare"],
                    "inputs": ["source"],
                    "outputs": ["build/intermediate"],
                },
                {
                    "id": "package",
                    "command": ["package"],
                    "deps": ["prepare"],
                    "inputs": ["build/intermediate"],
                    "outputs": ["build/package"],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source").write_bytes(b"first")
            calls = []

            def execute(name, command):
                calls.append(name)
                (root / "build").mkdir(exist_ok=True)
                if name == "prepare":
                    contents = (root / "source").read_bytes() + b":prepared"
                    (root / "build/intermediate").write_bytes(contents)
                else:
                    contents = (root / "build/intermediate").read_bytes() + b":packed"
                    (root / "build/package").write_bytes(contents)
                return 0

            preview = plan(data, root)
            self.assertEqual([row["id"] for row in preview], ["prepare", "package"])
            self.assertEqual(
                [row["disposition"] for row in preview], ["run", "deferred"]
            )
            self.assertIsNone(preview[1]["fingerprint"])
            self.assertFalse((root / "build").exists())

            first = run(data, root, execute)
            self.assertEqual(calls, ["prepare", "package"])
            self.assertEqual(
                first["statuses"], {"prepare": "succeeded", "package": "succeeded"}
            )
            self.assertEqual(first["errors"], {})
            self.assertEqual(
                (root / "build/package").read_bytes(), b"first:prepared:packed"
            )

            calls.clear()
            second = run(data, root, execute, first["state"])
            self.assertEqual(calls, [])
            self.assertEqual(
                second["statuses"], {"prepare": "cached", "package": "cached"}
            )

            (root / "source").write_bytes(b"changed")
            third = run(data, root, execute, second["state"])
            self.assertEqual(calls, ["prepare", "package"])
            self.assertEqual(
                third["statuses"], {"prepare": "succeeded", "package": "succeeded"}
            )
            self.assertEqual(
                (root / "build/package").read_bytes(), b"changed:prepared:packed"
            )

    def test_cli_dry_run_then_build_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "work"
            root.mkdir()
            (root / "source").write_bytes(b"hello")
            spec_path = base / "spec.json"
            state_path = base / "state.json"
            command = [
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; "
                "Path('output').write_bytes(Path('source').read_bytes()+b'!'); "
                "print('normal command chatter'); "
                "print('normal command diagnostic', file=sys.stderr)",
            ]
            spec_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "steps": [
                            {
                                "id": "build",
                                "command": command,
                                "inputs": ["source"],
                                "outputs": ["output"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            argv = [
                sys.executable,
                "-m",
                "buildflow",
                str(spec_path),
                str(root),
                str(state_path),
            ]

            def invoke(*flags):
                result = subprocess.run(
                    argv + list(flags),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(len(result.stdout.splitlines()), 1)
                return json.loads(result.stdout)

            preview = invoke("--dry-run")
            self.assertEqual(preview["plan"][0]["disposition"], "run")
            self.assertFalse((root / "output").exists())
            self.assertFalse(state_path.exists())

            first = invoke()
            self.assertEqual(first["statuses"], {"build": "succeeded"})
            self.assertEqual(first["errors"], {})
            self.assertEqual((root / "output").read_bytes(), b"hello!")
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved, first["state"])
            self.assertEqual(saved["version"], 2)
            self.assertEqual(invoke()["statuses"], {"build": "cached"})
