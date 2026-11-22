"""Register and verify Worker packages in a temporary store with inert dependencies."""

import hashlib
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import delegate_package as packages
from delegate_artifacts import create_snapshot

ROOT = Path(__file__).resolve().parents[1]


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return json.dumps(value).encode()


class PackageRegistrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = self.root / "harness"
        self.repo = self.root / "assigned-repository"
        self.store = self.root / "store"
        for name in [
            "uv.lock",
            "flake.lock",
            "pyproject.toml",
            "scripts/driver.py",
            "configs/agent.json",
            "configs/python-test-libraries.json",
        ]:
            put(self.project / name, b"{}")
        launcher = self.project / ".venv/bin/python"
        freeze = {
            "runtime_dependencies": {str(launcher): put(launcher, b"inert launcher")}
        }
        # Exercise the real protocol loader with the same structured handoff and checkpoint policy as Worker.
        registry = json.loads((ROOT / "configs/delegate-recipes-v1.json").read_bytes())
        recipe = next(
            entry
            for entry in registry["recipes"]
            if entry["id"] == "apprentice-qwen-32k-v1"
        )
        protocol = json.loads((ROOT / recipe["protocol_path"]).read_bytes())
        protocol.update(
            behavioral_gate="cli-state-v1", python_test_library="benchmark-only"
        )
        fixture_recipe = {
            "id": "fixture",
            "task": "example",
            "profile": "chosen",
            "server_config_path": "profiles.json",
            "protocol_path": "limits.json",
            "runtime_freeze": "freeze.json",
            "server_config_sha256": put(
                self.project / "profiles.json",
                json_bytes({"chosen": {"model": "local"}, "other": {}}),
            ),
            "protocol_sha256": put(self.project / "limits.json", json_bytes(protocol)),
            "runtime_freeze_sha256": put(
                self.project / "freeze.json", json_bytes(freeze)
            ),
        }
        for index in ("delegate-recipes-v1.json", "frontier-practical-recipes-v1.json"):
            put(
                self.project / "configs" / index,
                json_bytes({"recipes": [fixture_recipe]}),
            )
        put(self.repo / "bin/tool", b"starter")
        (self.repo / "bin/tool").chmod(0o750)
        put(self.repo / "guide.md", b"documentation")
        put(self.repo / "unselected", b"other material")
        self.checker = self.root / "expected.txt"
        put(self.checker, b"private expectation")
        self.spec = {
            "label": "Edit the tool",
            "brief": "Improve bin/tool.",
            "recipe_id": "fixture",
            "input_files": ["bin/tool", "guide.md"],
            "allowed_write_paths": ["bin/tool", "new.md"],
            "checks": [
                {"name": "outer check", "argv": ["/bin/python3", "-V"], "timeout": 3}
            ],
            "check_files": {"expected.txt": str(self.checker)},
            "task_seconds": 90,
            "verification_seconds": 15,
            "admission": {
                "mode": "outer_only_experimental",
                "approved": True,
                "reason": "test fixture",
            },
        }
        self.admit()

    def admit(self):
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            snapshot = create_snapshot(
                self.repo,
                self.spec["input_files"],
                self.spec["allowed_write_paths"],
                Path(directory) / "snapshot",
            )
        self.spec["admission"]["public_contract_sha256"] = packages.public_contract_id(
            snapshot["snapshot_id"], self.spec["brief"]
        )

    def register(self):
        return packages.register(
            self.spec, project=self.project, source_project=self.repo, store=self.store
        )

    def test_register_verify_and_reuse_exact_package(self):
        first = self.register()
        package, record = packages.verify_package(first["package_id"], self.store)
        task = package / "runtime/tasks/delegated-task"
        public = task / "public"
        self.assertEqual(
            {
                p.relative_to(public).as_posix()
                for p in public.rglob("*")
                if p.is_file()
            },
            {"task.md", "guide.md", "bin/tool"},
        )
        self.assertEqual((public / "bin/tool").read_bytes(), b"starter")
        self.assertEqual((public / "bin/tool").stat().st_mode & 0o111, 0o110)
        brief = (public / "task.md").read_text()
        for line in [
            self.spec["brief"],
            "- editable: bin/tool",
            "- editable: new.md",
            "- read-only: guide.md",
        ]:
            self.assertIn(line, brief.splitlines())
        self.assertEqual(
            (task / "private/expected.txt").read_bytes(), self.checker.read_bytes()
        )
        self.assertEqual(
            json.loads((task / "private/checks.json").read_bytes())["checks"],
            self.spec["checks"],
        )
        self.assertEqual(
            json.loads((package / "runtime/configs/servers.json").read_bytes()),
            {"chosen": {"model": "local"}},
        )
        limits = json.loads(
            (package / "runtime/configs/protocols/delegated-v1.json").read_bytes()
        )
        self.assertEqual(
            [
                limits[k]
                for k in (
                    "task_wall_seconds",
                    "agent_wall_seconds",
                    "verification_reserve_seconds",
                    "request_timeout_seconds",
                )
            ],
            [90, 75, 15, 75],
        )
        self.assertNotIn("behavioral_gate", limits)
        self.assertNotIn("python_test_library", limits)
        self.assertEqual(record["snapshot_id"], first["snapshot_id"])
        self.assertEqual(self.register(), first)
        self.assertEqual(list(package.parent.iterdir()), [package])

        self.checker.write_bytes(b"revised expectation")
        second = self.register()
        self.assertEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertNotEqual(first["package_id"], second["package_id"])
        packages.verify_package(first["package_id"], self.store)

    def test_task_selector_and_blind_admission_with_writable_notebook(self):
        del self.spec["recipe_id"]
        self.spec.update(
            recipe_task="example", apprentice_notes=True, checkpoint_progress=True
        )
        put(self.repo / "SUBAGENTS.md", b"working notes")
        self.spec["input_files"].append("SUBAGENTS.md")
        self.spec["allowed_write_paths"].append("SUBAGENTS.md")
        self.spec["admission"] = {"approved": True}
        for field in ("blind_review", "sealed_solution"):
            path = self.root / field
            self.spec["admission"][field] = {
                "path": str(path),
                "sha256": put(path, field.encode()),
            }
        self.admit()
        registration = self.register()
        package, record = packages.verify_package(
            registration["package_id"], self.store
        )
        self.assertEqual(
            record["apprentice_notes"],
            {
                "enabled": True,
                "path": "SUBAGENTS.md",
                "sha256": hashlib.sha256(b"working notes").hexdigest(),
                "editable": True,
            },
        )
        task = package / "runtime/tasks/delegated-task"
        self.assertEqual((task / "public/SUBAGENTS.md").read_bytes(), b"working notes")
        self.assertIn("Read SUBAGENTS.md", (task / "public/task.md").read_text())
        self.assertEqual(
            json.loads((task / "task.json").read_bytes())["admission_mode"],
            "blind_reviewed",
        )
        self.assertTrue(
            json.loads(
                (package / "runtime/configs/protocols/delegated-v1.json").read_bytes()
            )["checkpoint_progress"]
        )
        (self.root / "sealed_solution").write_text("changed")
        with self.assertRaisesRegex(ValueError, "admission evidence"):
            self.register()

    def test_changed_contract_is_rejected_before_publication(self):
        for field, value in [
            ("brief", "Another assignment"),
            ("allowed_write_paths", ["bin/tool"]),
        ]:
            with self.subTest(field), patch.dict(self.spec, {field: value}):
                with self.assertRaisesRegex(ValueError, "different public contract"):
                    self.register()
        (self.repo / "guide.md").write_text("new input")
        with self.assertRaisesRegex(ValueError, "different public contract"):
            self.register()
        self.assertEqual(list((self.store / "packages").iterdir()), [])

    def test_changed_recipe_inputs_are_rejected(self):
        for name in ("profiles.json", "limits.json", "freeze.json"):
            path = self.project / name
            original = path.read_bytes()
            with self.subTest(name):
                path.write_bytes(original + b"\n")
                with self.assertRaisesRegex(ValueError, "Recipe .*changed"):
                    self.register()
            path.write_bytes(original)
        self.assertFalse((self.store / "packages").exists())

    def test_profile_is_pinned_even_if_checkout_changes_during_preparation(self):
        def snapshot_while_profile_changes(*args, **kwargs):
            snapshot = create_snapshot(*args, **kwargs)
            put(
                self.project / "profiles.json",
                json_bytes({"chosen": {"model": "next"}}),
            )
            return snapshot

        with patch.object(packages, "create_snapshot", snapshot_while_profile_changes):
            first = self.register()
        package, _ = packages.verify_package(first["package_id"], self.store)
        profile = json.loads((package / "runtime/configs/servers.json").read_bytes())
        self.assertEqual(profile["chosen"]["model"], "local")
        with self.assertRaisesRegex(ValueError, "Recipe .*changed"):
            self.register()

    def test_registration_rechecks_an_existing_package(self):
        first = self.register()
        package = self.store / "packages" / first["package_id"]
        changed = package / "runtime/tasks/delegated-task/private/expected.txt"
        changed.write_bytes(b"altered")
        with self.assertRaisesRegex(ValueError, "file integrity"):
            self.register()
        self.assertEqual(changed.read_bytes(), b"altered")
        self.assertEqual(list(package.parent.iterdir()), [package])

    def test_rejects_unadmitted_or_unverifiable_assignments(self):
        cases = [
            ({"recipe_task": "example"}, "exactly one"),
            ({"recipe_id": "unregistered"}, "registered recipe"),
            ({"verification_seconds": 46}, "verification reserve"),
            ({"admission": {"approved": False}}, "admission required"),
            ({"check_files": {"checks.json": str(self.checker)}}, "check filename"),
            ({"apprentice_notes": True}, "explicit input"),
        ]
        for override, reason in cases:
            with self.subTest(override=override), patch.dict(self.spec, override):
                with self.assertRaisesRegex(ValueError, reason):
                    self.register()
        self.assertEqual(list((self.store / "packages").glob("*")), [])

    def test_rejects_changed_registration_metadata_and_environment_target(self):
        first = self.register()
        package = self.store / "packages" / first["package_id"]
        metadata = package / "package.json"
        original = metadata.read_bytes()
        changed = json.loads(original)
        changed["label"] = "another assignment"
        metadata.write_bytes(json_bytes(changed))
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            packages.verify_package(first["package_id"], self.store)
        metadata.write_bytes(original)

        replacement = self.root / "other-env"
        put(replacement / "bin/python", b"inert launcher")
        link = package / "runtime/.venv"
        link.unlink()
        link.symlink_to(replacement)
        with self.assertRaisesRegex(ValueError, "environment link"):
            packages.verify_package(first["package_id"], self.store)

    def test_task_copies_preserve_admitted_execute_permissions(self):
        first = self.register()
        task = (
            self.store
            / "packages"
            / first["package_id"]
            / "runtime/tasks/delegated-task"
        )
        for parent in [task / "public", task / "private/snapshot/public"]:
            with self.subTest(copy=parent.relative_to(task)):
                tool = parent / "bin/tool"
                original_mode = tool.stat().st_mode
                tool.chmod(0o700)
                try:
                    with self.assertRaisesRegex(ValueError, "permission"):
                        packages.verify_package(first["package_id"], self.store)
                finally:
                    tool.chmod(original_mode)
        packages.verify_package(first["package_id"], self.store)

    def test_concurrent_identical_registrations_return_one_package(self):
        barrier = Barrier(2, timeout=10)
        rename = Path.rename

        def publish_together(source, destination):
            barrier.wait()
            return rename(source, destination)

        with (
            patch.object(Path, "rename", publish_together),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            jobs = [pool.submit(self.register) for _ in range(2)]
            first, second = [job.result() for job in jobs]
        self.assertEqual(first, second)
        package, _ = packages.verify_package(first["package_id"], self.store)
        self.assertEqual(list(package.parent.iterdir()), [package])
