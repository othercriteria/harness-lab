"""Check the public bindings documented in SNAPSHOT.md from a full clone."""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "examples/reviewing-worker-output"
PREPARE = ROOT / "examples/preparing-worker-package"
PUBLIC_SNAPSHOT = "c7b7b842d9cf7f32b4ca0b89aba04de5ee5e6421"
POLICY_FILES = ("scripts/checkpoint_policy.py", "tests/test_checkpoint_policy.py")
STARTER_FILES = ("observatory/app.js", "tests/test_observe_ui.js")


def blob(revision, name):
    return subprocess.check_output(
        ["git", "cat-file", "blob", f"{revision}:{name}"], cwd=ROOT
    )


def recipe_bytes(root, row, path_key, digest_key):
    name = row[path_key]
    path = (root / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(root):
        raise ValueError(
            f"{path_key} must refer to a file in the public checkout: {name}"
        )
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != row[digest_key]:
        raise ValueError(f"SHA-256 mismatch for {path_key}: {name}")
    return data


class PublicPinTests(unittest.TestCase):
    def test_walkthrough_files_match_their_public_source_revisions(self):
        for directory, revision, files in (
            (
                REVIEW / "historical",
                "af8a47a87b0d122066bde0e3bc73a57c089f008b",
                POLICY_FILES,
            ),
            (
                PREPARE / "starter",
                "6a18691d6be8e5a35219e4ea1d0b94782b2f7c3d",
                STARTER_FILES,
            ),
        ):
            for name in files:
                with self.subTest(revision=revision, file=name):
                    self.assertTrue(
                        (directory / name).read_bytes() == blob(revision, name),
                        f"{directory.relative_to(ROOT)}/{name} differs from {revision}:{name}",
                    )

    def test_bundled_patches_reproduce_the_public_landings(self):
        for patch, starter, landing, files in (
            (
                REVIEW / "accepted/worker.patch",
                None,
                "1410543b7ca025d219d6d9400272a64d9ca01d0f",
                POLICY_FILES,
            ),
            (
                PREPARE / "landed.patch",
                PREPARE / "starter",
                "1aeaefed8ec5364b71bf276a8f74071ae355d41e",
                STARTER_FILES,
            ),
        ):
            with self.subTest(patch=patch.name), tempfile.TemporaryDirectory() as tmp:
                tree = Path(tmp)
                if starter:
                    shutil.copytree(starter, tree, dirs_exist_ok=True)
                subprocess.run(
                    ["git", "apply", "--no-index", str(patch)], cwd=tree, check=True
                )
                self.assertEqual(
                    {
                        p.relative_to(tree).as_posix()
                        for p in tree.rglob("*")
                        if p.is_file()
                    },
                    set(files),
                )
                for name in files:
                    self.assertTrue(
                        (tree / name).read_bytes() == blob(landing, name),
                        f"{patch.name} produced different bytes for {landing}:{name}",
                    )

    def test_walkthrough_runs_all_original_checkpoint_tests(self):
        run = subprocess.run(
            [
                sys.executable,
                "-B",
                "-S",
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-p",
                "test_checkpoint_policy.py",
            ],
            cwd=REVIEW / "historical",
            capture_output=True,
            text=True,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertRegex(run.stderr, r"Ran 14 tests in [^\n]+\s+OK\s*$")

    def test_published_recipe_bindings(self):
        launch = json.loads((ROOT / "configs/servers.json").read_bytes())
        for registry, selector in (
            ("delegate-recipes-v1.json", "id"),
            ("frontier-practical-recipes-v1.json", "task"),
        ):
            rows = json.loads((ROOT / "configs" / registry).read_bytes())["recipes"]
            # Anchor historical claims even if a file and its registry digest change
            # together. Paths can move, and additional recipes need no historical row.
            original = json.loads(blob(PUBLIC_SNAPSHOT, f"configs/{registry}"))[
                "recipes"
            ]
            published = {r[selector]: r for r in original}
            names = [r[selector] for r in rows]
            self.assertEqual(
                len(set(names)), len(names), f"duplicate selector in {registry}"
            )
            self.assertFalse(
                published.keys() - set(names),
                f"missing published recipes in {registry}: {published.keys() - set(names)}",
            )
            for row in rows:
                with self.subTest(registry=registry, recipe=row[selector]):
                    historical = published.get(row[selector])
                    if historical:
                        for field in (
                            "profile",
                            "server_config_sha256",
                            "protocol_sha256",
                            "runtime_freeze_sha256",
                        ):
                            self.assertEqual(
                                row[field],
                                historical[field],
                                f"published {field} changed",
                            )
                    catalog = json.loads(
                        recipe_bytes(
                            ROOT, row, "server_config_path", "server_config_sha256"
                        )
                    )
                    protocol = recipe_bytes(
                        ROOT, row, "protocol_path", "protocol_sha256"
                    )
                    recipe_bytes(ROOT, row, "runtime_freeze", "runtime_freeze_sha256")
                    profile = row["profile"]
                    self.assertEqual(launch[profile], catalog[profile])
                    if selector == "task":
                        limits = json.loads(protocol)
                        self.assertEqual(limits["protocol"], row["protocol"])
                        self.assertEqual(
                            limits["task_wall_seconds"], row["task_ceiling_seconds"]
                        )
                        launch_protocol = (
                            ROOT / "configs/protocols" / (row["protocol"] + ".json")
                        )
                        self.assertTrue(
                            protocol == launch_protocol.read_bytes(),
                            f"launch protocol differs from {row['protocol_path']}",
                        )
                        self.assertTrue(
                            (ROOT / "tasks" / row["task"] / "public/task.md").is_file()
                        )

    def test_changed_protocol_copy_fails_its_recorded_digest(self):
        registry = json.loads((ROOT / "configs/delegate-recipes-v1.json").read_bytes())
        row = next(
            r for r in registry["recipes"] if r["id"] == "apprentice-qwen-32k-v1"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            dest = root / row["protocol_path"]
            dest.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / row["protocol_path"], dest)
            original = recipe_bytes(root, row, "protocol_path", "protocol_sha256")
            dest.write_bytes(original + b"\n")
            with self.assertRaisesRegex(
                ValueError, "SHA-256 mismatch for protocol_path"
            ):
                recipe_bytes(root, row, "protocol_path", "protocol_sha256")
