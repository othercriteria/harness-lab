import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from buildflow.cli import main
from buildflow.planner import plan
from buildflow.runner import run
from buildflow.spec import parse_spec
from buildflow.state import load_state, save_state, validate_state


def step(name, deps=None, inputs=None, command=None):
    return {
        "id": name,
        "command": command or ["true"],
        "deps": deps or [],
        "inputs": inputs or [],
    }


def spec(*steps):
    return {"version": 1, "steps": list(steps)}


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "root"
        self.root.mkdir()
        self.state = self.base / "state.json"

    def test_spec_validation_and_detachment(self):
        valid = spec(step("b", ["a"], ["z", "a"]), step("a"))
        before = copy.deepcopy(valid)
        parsed = parse_spec(valid)
        self.assertEqual(parsed["b"]["inputs"], ["a", "z"])
        parsed["b"]["command"].append("changed")
        self.assertEqual(valid, before)
        invalid = [
            None,
            {"version": True, "steps": []},
            {"version": 1, "steps": [], "x": 0},
            spec(step("a"), step("a")),
            spec(step("a", ["missing"])),
            spec(step("a", ["b"]), step("b", ["a"])),
            spec(step("a", ["a"])),
            spec(step("a", ["b", "b"]), step("b")),
        ]
        for name in ["../a", "", "a/b", "1a"]:
            invalid.append(spec(step(name)))
        for path in ["/abs", "../bad", "a//b", "a/./b", "a/../b", "a\\b", ""]:
            invalid.append(spec({"id": "a", "command": ["true"], "inputs": [path]}))
        for bad in invalid:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_spec(bad)

    def test_topological_targets_and_empty_validation(self):
        data = spec(step("z", ["b"]), step("b", ["a"]), step("x"), step("a"))
        self.assertEqual([s["id"] for s in plan(data, self.root)], ["a", "b", "x", "z"])
        self.assertEqual(
            [s["id"] for s in plan(data, self.root, targets=["z", "z"])],
            ["a", "b", "z"],
        )
        self.assertEqual(plan(data, self.root, targets=[]), [])
        for targets in [["missing"], "a"]:
            with self.assertRaises(ValueError):
                plan(data, self.root, targets=targets)
        with self.assertRaises(ValueError):
            plan(spec(step("bad", ["bad"])), self.root, targets=[])

    def test_fingerprint_contract_and_no_mutation(self):
        (self.root / "x").write_bytes(b"\x00\xff")
        data = spec(step("a", inputs=["x"], command=["echo", "hello"]))
        before = copy.deepcopy(data)
        row = plan(data, self.root)[0]
        payload = {
            "id": "a",
            "command": ["echo", "hello"],
            "inputs": [["x", hashlib.sha256(b"\x00\xff").hexdigest()]],
            "deps": [],
        }
        expected = hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode()
        ).hexdigest()
        self.assertEqual(set(row), {"id", "deps", "command", "fingerprint", "cached"})
        self.assertEqual(row["fingerprint"], expected)
        row["command"].append("mutation")
        self.assertEqual(data, before)

    def test_transitive_invalidation_and_cached_skip(self):
        (self.root / "x").write_text("one")
        data = spec(step("a", inputs=["x"]), step("b", ["a"]), step("c"))
        first = run(data, self.root, lambda *_: 0)
        calls = []
        second = run(
            data, self.root, lambda name, cmd: calls.append(name) or 0, first["state"]
        )
        self.assertEqual(calls, [])
        self.assertEqual(set(second["statuses"].values()), {"cached"})
        old = copy.deepcopy(first["state"])
        (self.root / "x").write_text("two")
        third = run(data, self.root, lambda name, cmd: calls.append(name) or 0, old)
        self.assertEqual(calls, ["a", "b"])
        self.assertEqual(third["statuses"]["c"], "cached")
        self.assertEqual(old, first["state"])

    def test_command_change_and_spec_order_independence(self):
        data = spec(step("a"), step("b", ["a"]))
        previous = run(data, self.root, lambda *_: 0)["state"]
        self.assertEqual(
            plan(data, self.root), plan(spec(*reversed(data["steps"])), self.root)
        )
        data["steps"][0]["command"] = ["false"]
        self.assertTrue(all(not s["cached"] for s in plan(data, self.root, previous)))

    def test_input_validation_before_execution(self):
        calls = []
        data = spec(step("a"), step("z", inputs=["missing"]))
        with self.assertRaises((ValueError, OSError)):
            run(data, self.root, lambda *x: calls.append(x) or 0)
        self.assertEqual(calls, [])
        (self.root / "file").write_text("ok")
        (self.root / "link").symlink_to(self.root / "file")
        (self.root / "dir").mkdir()
        (self.root / "dirlink").symlink_to(self.root / "dir", target_is_directory=True)
        (self.root / "dir" / "f").write_text("ok")
        for name in ["link", "dir", "dirlink/f"]:
            with self.assertRaises((ValueError, OSError)):
                plan(spec(step("a", inputs=[name])), self.root)
        alias = self.base / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            plan(spec(), alias)
        self.assertEqual(plan(data, self.root, targets=["a"])[0]["id"], "a")

    def test_fail_fast_and_keep_going(self):
        data = spec(step("a"), step("b", ["a"]), step("c"), step("d", ["b"]))
        calls = []
        result = run(
            data,
            self.root,
            lambda name, cmd: calls.append(name) or (3 if name == "a" else 0),
        )
        self.assertEqual(calls, ["a"])
        self.assertEqual(
            result["statuses"],
            {"a": "failed", "b": "blocked", "c": "not_run", "d": "blocked"},
        )
        calls.clear()
        result = run(
            data,
            self.root,
            lambda name, cmd: calls.append(name) or (3 if name == "a" else 0),
            keep_going=True,
        )
        self.assertEqual(calls, ["a", "c"])
        self.assertEqual(result["statuses"]["c"], "succeeded")
        self.assertEqual(set(result["errors"]), {"a"})
        self.assertTrue(result["errors"]["a"])

    def test_callback_exceptions_and_invalid_results(self):
        def failure(*_):
            raise RuntimeError("boom")

        for callback in [failure, lambda *_: True, lambda *_: "0"]:
            result = run(spec(step("a")), self.root, callback)
            self.assertEqual(result["statuses"], {"a": "failed"})
            self.assertEqual(result["state"]["completed"], {})

        def cancelled(*_):
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            run(spec(step("a")), self.root, cancelled)

    def test_partial_state_retains_unselected_and_drops_stale(self):
        data = spec(step("a"), step("b", ["a"]), step("c"))
        old = run(data, self.root, lambda *_: 0)["state"]
        old["completed"]["removed"] = "f" * 64
        data["steps"][0]["command"] = ["changed"]
        before = copy.deepcopy(old)
        result = run(data, self.root, lambda *_: 1, old, targets=["b"])
        self.assertEqual(result["state"]["completed"], {"c": old["completed"]["c"]})
        self.assertEqual(old, before)

    def test_state_validation_all_boundaries(self):
        bads = [
            None,
            {"version": True, "completed": {}},
            {"version": 1, "completed": {"a": "A" * 64}},
            {"version": 1, "completed": {"../a": "a" * 64}},
            {"version": 1, "completed": {}, "x": 1},
        ]
        for bad in bads:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    validate_state(bad)
                if bad is not None:
                    with self.assertRaises(ValueError):
                        plan(spec(), self.root, bad)
                self.state.write_text("old")
                with self.assertRaises(ValueError):
                    save_state(self.state, bad)
                self.assertEqual(self.state.read_text(), "old")
        original = {"version": 1, "completed": {"a": "a" * 64}}
        detached = validate_state(original)
        detached["completed"].clear()
        self.assertTrue(original["completed"])

    def test_atomic_publication_hook_preserves_and_cleans(self):
        import buildflow.state as module

        data = {"version": 1, "completed": {"a": "a" * 64}}
        self.state.write_text("old bytes")
        before = set(self.base.iterdir())
        with patch.object(
            module, "replace_file", side_effect=OSError("publish failed")
        ) as hook:
            with self.assertRaises(OSError):
                save_state(self.state, data)
            self.assertEqual(hook.call_count, 1)
        self.assertEqual(self.state.read_text(), "old bytes")
        self.assertEqual(set(self.base.iterdir()), before)
        save_state(self.state, data)
        self.assertEqual(load_state(self.state), data)
        self.state.write_text("{bad")
        with self.assertRaises(ValueError):
            load_state(self.state)

    def invoke(self, data, *flags):
        source = self.base / "spec.json"
        source.write_text(json.dumps(data))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([str(source), str(self.root), str(self.state), *flags])
        return code, out.getvalue(), err.getvalue()

    def test_cli_dry_run_has_no_side_effects(self):
        data = spec(
            step(
                "a", command=[sys.executable, "-c", "open('created','w').write('bad')"]
            )
        )
        code, out, err = self.invoke(data, "--dry-run")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["plan"][0]["id"], "a")
        self.assertFalse(self.state.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cli_captures_chatter_and_saves_partial_progress(self):
        data = spec(
            step("a", command=[sys.executable, "-c", "print('chatter')"]),
            step("b", command=[sys.executable, "-c", "raise SystemExit(3)"]),
            step("c"),
        )
        code, out, err = self.invoke(data)
        self.assertEqual((code, err), (1, ""))
        report = json.loads(out)
        self.assertEqual(
            report["statuses"], {"a": "succeeded", "b": "failed", "c": "not_run"}
        )
        self.assertEqual(set(load_state(self.state)["completed"]), {"a"})

    def test_cli_error_has_no_success_output(self):
        import buildflow.state as module

        self.state.write_text(json.dumps({"version": 1, "completed": {}}))
        before = self.state.read_bytes()
        with patch.object(module, "replace_file", side_effect=OSError("disk")):
            code, out, err = self.invoke(spec())
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.strip())
        self.assertEqual(self.state.read_bytes(), before)

    def test_targeted_resume_and_callback_list_mutation(self):
        data = spec(step("a"), step("b", ["a"]), step("c"))

        def callback(name, command):
            command.clear()
            return 0

        before = copy.deepcopy(data)
        result = run(data, self.root, callback, targets=["b"])
        self.assertEqual(result["order"], ["a", "b"])
        self.assertEqual(data, before)
        self.assertEqual(set(result["state"]["completed"]), {"a", "b"})
        resumed = run(data, self.root, lambda *_: 0, result["state"])
        self.assertEqual(
            resumed["statuses"], {"a": "cached", "b": "cached", "c": "succeeded"}
        )
