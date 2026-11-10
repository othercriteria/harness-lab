"""CPU-only contract checks; live small-scope checks are explicit CLI commands."""

import fcntl
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from scripts import with_memory_scope as scope


class MemoryScopeTests(unittest.TestCase):
    def test_defaults_and_literal_arguments(self):
        argv = scope.scope_argv(
            "owned.scope",
            140 * 2**30,
            45.2,
            Path("/bulk/anchor"),
            Path("/bulk/out"),
            9,
            10,
        )
        self.assertIn("--property=MemoryMax=150323855360", argv)
        self.assertIn("--property=MemorySwapMax=0", argv)
        self.assertIn("--property=RuntimeMaxSec=46", argv)
        self.assertIn("--expand-environment=no", argv)
        self.assertNotIn("--wait", argv)
        self.assertEqual(argv[-2:], ["9", "10"])

    def test_only_owned_cgroup_path(self):
        self.assertEqual(
            scope.cgroup_path("/user.slice/owned.scope", "owned.scope"),
            Path("/sys/fs/cgroup/user.slice/owned.scope"),
        )
        for relative in (
            "../../owned.scope",
            "/user.slice/other.scope",
            "/../../owned.scope",
        ):
            with self.assertRaises(RuntimeError):
                scope.cgroup_path(relative, "owned.scope")

    def test_limits_must_match_before_launch(self):
        snapshot = {"files": {"memory.max": "100", "memory.swap.max": "0"}}
        props = {
            "values": {
                "MemoryMax": "100",
                "MemorySwapMax": "0",
                "OOMPolicy": "continue",
            }
        }
        scope.validate_limits(snapshot, props, 100)
        snapshot["files"]["memory.swap.max"] = "max"
        with self.assertRaises(RuntimeError):
            scope.validate_limits(snapshot, props, 100)

    def test_oom_survives_missing_final_sample(self):
        samples = [
            {"files": {"memory.events": "low 0\nhigh 0\nmax 12\noom 1\noom_kill 1"}},
            {"files": {}},
        ]
        evidence = scope.oom_evidence(samples, {})
        self.assertTrue(evidence["oom_observed"])
        self.assertEqual(evidence["maximum_observed_memory_events"]["oom_kill"], 1)
        self.assertFalse(scope.oom_evidence([], {})["event_counters_observed"])
        self.assertTrue(
            scope.oom_evidence([], {"values": {"Result": "oom-kill"}})["oom_observed"]
        )

    def test_close_duplicate_does_not_unlock_caller(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (root / "gpu-experiment.lock").open("a") as original:
                fcntl.flock(original, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with mock.patch.dict(
                    os.environ, {"BIG_MODELS_GPU_LOCK_FD": str(original.fileno())}
                ):
                    duplicate = scope.inherited_lock(root)
                self.assertNotEqual(duplicate, original.fileno())
                os.close(duplicate)
                with (
                    (root / "gpu-experiment.lock").open("a") as competitor,
                    self.assertRaises(BlockingIOError),
                ):
                    fcntl.flock(competitor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_wrong_lock_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "gpu-experiment.lock").touch()
            with (
                (root / "other").open("a") as other,
                mock.patch.dict(
                    os.environ, {"BIG_MODELS_GPU_LOCK_FD": str(other.fileno())}
                ),
                self.assertRaises(RuntimeError),
            ):
                scope.inherited_lock(root)

    def test_evidence_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            scope.durable_json(path, {"first": True})
            with self.assertRaises(FileExistsError):
                scope.durable_json(path, {"first": False})
            self.assertEqual(json.loads(path.read_text()), {"first": True})

    def test_cleanup_continues_after_manager_timeout(self):
        child = mock.Mock(returncode=0)
        child.poll.return_value = 0
        calls = []

        def manager(unit, *args):
            calls.append(args)
            if len(calls) == 1:
                raise subprocess.TimeoutExpired("systemctl", 10)
            return subprocess.CompletedProcess([], 0, "", "")

        with (
            mock.patch.object(scope, "systemctl", side_effect=manager),
            mock.patch.object(
                scope,
                "properties",
                return_value={"returncode": 0, "values": {"ActiveState": "inactive"}},
            ),
        ):
            result = scope.cleanup("owned.scope", child, None, 0.001)
        self.assertTrue(result["verified"], result)
        self.assertIn(("kill", "--kill-whom=all", "--signal=SIGKILL"), calls)
        self.assertIn(("stop",), calls)
        self.assertIn("error", result["actions"][0])

    def test_unavailable_manager_is_not_cleanup_proof(self):
        self.assertFalse(
            scope.inactive(
                {"returncode": 1, "values": {}, "stderr": "Failed to connect to bus"}
            )
        )
        self.assertTrue(
            scope.inactive({"returncode": 0, "values": {"LoadState": "not-found"}})
        )

    def test_admission_happens_before_scope_or_command(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(scope, "available_bytes", return_value=100),
            mock.patch.object(scope.subprocess, "Popen") as popen,
        ):
            with self.assertRaisesRegex(RuntimeError, "admission floor"):
                scope.supervise(Path(directory), ["never-run"], 100, 1, 1, 1, 101)
            popen.assert_not_called()


class WholeCommandGlobalGuardTests(unittest.TestCase):
    @staticmethod
    def sample(seconds=0, *, available=32, swap_pages=900_000, full_us=0):
        return {
            "monotonic": seconds,
            "available_bytes": available * 2**30,
            "swap_out_pages": swap_pages,
            "page_size_bytes": 4096,
            "memory_full_total_us": full_us,
        }

    def test_reads_explicit_global_counters(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            (proc / "pressure").mkdir()
            (proc / "meminfo").write_text("MemAvailable: 33554432 kB\n")
            (proc / "vmstat").write_text("pswpin 50\npswpout 900000\n")
            (proc / "pressure/memory").write_text(
                "some avg10=0 total=10\nfull avg10=0 total=20\n"
            )
            sample = scope.global_resource_sample(proc)
        self.assertEqual(sample["available_bytes"], 32 * 2**30)
        self.assertEqual(sample["swap_out_pages"], 900_000)
        self.assertEqual(sample["memory_full_total_us"], 20)

    def test_hash_phase_swap_uses_pre_command_baseline(self):
        baseline = self.sample()
        # Simulate the entire hash phase before any model server exists.
        after_hash = self.sample(20, swap_pages=900_000 + 65_537)
        observation = scope.global_guard_observation(baseline, baseline, after_hash, 0)
        self.assertEqual(observation["reasons"][0]["limit"], "maximum_swap_out_mib")
        self.assertGreater(observation["swap_out_growth_mib"], 256)
        # Existing absolute swap/counter use at baseline is not itself a failure.
        self.assertEqual(
            scope.global_guard_observation(baseline, baseline, baseline, 0)["reasons"],
            [],
        )

    def test_consecutive_psi_intervals_and_reset(self):
        baseline = previous = self.sample()
        streak = 0
        for t, fraction in enumerate([0.3, 0.3, 0.1, 0.3, 0.3, 0.3], start=1):
            current = self.sample(
                t, full_us=previous["memory_full_total_us"] + int(fraction * 1e6)
            )
            observation = scope.global_guard_observation(
                baseline, previous, current, streak
            )
            streak = observation["pressure_streak"]
            self.assertEqual(bool(observation["reasons"]), t == 6)
            previous = current
        self.assertEqual(streak, 3)
        self.assertEqual(observation["reasons"][0]["consecutive_samples"], 3)

    def test_available_floor_is_immediate_and_thresholds_are_strict(self):
        baseline = self.sample()
        at_limit = self.sample(
            1, available=16, swap_pages=900_000 + 65_536, full_us=200_000
        )
        self.assertEqual(
            scope.global_guard_observation(baseline, baseline, at_limit, 0)["reasons"],
            [],
        )
        below = self.sample(2, available=15)
        self.assertEqual(
            scope.global_guard_observation(baseline, baseline, below, 0)["reasons"][0][
                "limit"
            ],
            "minimum_available_memory_gib",
        )

    def test_counter_regression_fails_closed(self):
        baseline = self.sample(5)
        for current in [
            self.sample(4),
            self.sample(6, swap_pages=899_999),
            self.sample(6, full_us=-1),
        ]:
            with self.assertRaisesRegex(RuntimeError, "regressed"):
                scope.global_guard_observation(baseline, baseline, current, 0)

    def test_swap_counter_cannot_regress_above_original_baseline(self):
        baseline = self.sample()
        previous = self.sample(1, swap_pages=900_010)
        current = self.sample(2, swap_pages=900_009)
        with self.assertRaisesRegex(RuntimeError, "regressed"):
            scope.global_guard_observation(baseline, previous, current, 0)

    def test_background_observer_failure_sets_trigger_without_disk_io(self):
        guard = scope.WholeCommandGlobalGuard(self.sample())
        with (
            mock.patch.dict(
                scope.WHOLE_COMMAND_GLOBAL_GUARD, {"poll_interval_seconds": 0.001}
            ),
            mock.patch.object(
                scope,
                "global_resource_sample",
                side_effect=OSError("counter unavailable"),
            ),
            mock.patch.object(scope, "durable_json") as write,
        ):
            guard.start()
            self.assertTrue(guard.triggered.wait(2))
            guard.thread.join(timeout=2)
            write.assert_not_called()
        self.assertEqual(guard.trigger["reasons"][0]["limit"], "observer_error")
        with self.assertRaises(scope.WholeCommandGlobalGuardExceeded):
            guard.raise_if_triggered()

    def run_mocked_supervisor(
        self, output, *, enabled, hash_trip=False, final_trip=False
    ):
        """Real lifecycle/evidence logic; no systemd, child, GPU or host samples."""
        state = {"unit": None, "guard": None, "started": False, "cleaned": False}
        baseline = self.sample()
        swapped = self.sample(10, swap_pages=baseline["swap_out_pages"] + 65_537)
        fake_child = mock.Mock(pid=12345, returncode=None)
        fake_child.poll.side_effect = lambda: 0 if state["cleaned"] else None
        memory_bytes = 140 * 2**30

        def popen(argv, **kwargs):
            state["unit"] = next(
                x.split("=", 1)[1] for x in argv if x.startswith("--unit=")
            )
            scope.durable_json(
                output / "anchor-ready.json",
                {
                    "pid": fake_child.pid,
                    "process_group": os.getpgrp(),
                    "cgroup": "/fake/" + state["unit"],
                },
            )
            return fake_child

        def properties(unit):
            self.assertEqual(unit, state["unit"])
            return {
                "returncode": 0,
                "values": {
                    "ControlGroup": "/fake/" + unit,
                    "MemoryMax": str(memory_bytes),
                    "MemorySwapMax": "0",
                    "OOMPolicy": "continue",
                    "ActiveState": "active",
                },
            }

        def start_guard(guard):
            state["guard"] = guard
            guard.raise_if_triggered()  # Keep sampling deterministic in this test.

        def gate(fd, data):
            if data == b"start\n":
                state["started"] = True
                if enabled:
                    recorded = json.loads(
                        (output / "whole-command-global-baseline.json").read_text()
                    )
                    self.assertEqual(recorded["sample"], baseline)
                    self.assertIn("before start gate", recorded["phase"])
                if hash_trip:
                    state["guard"].observe(swapped)
                    # No server/result was ever started in this simulated hash phase.
                else:
                    scope.durable_json(
                        output / "child-result.json",
                        {
                            "returncode": 0,
                            "timed_out": False,
                            "elapsed_seconds": 0.1,
                        },
                    )
            return len(data)

        def cleanup(unit, child, path, grace):
            self.assertEqual(unit, state["unit"])
            self.assertIs(child, fake_child)
            self.assertEqual(path, Path("/fake-owned-cgroup"))
            # Final counters are sampled before cleanup, but opt-in pressure
            # relief does not wait for bulk telemetry/evidence writes.
            self.assertEqual((output / "scope-end.json").exists(), not enabled)
            if enabled:
                self.assertFalse((output / "cgroup-samples.jsonl").exists())
            state["cleaned"] = True
            fake_child.returncode = 0
            return {"verified": True, "owned_unit": unit}

        final = swapped if hash_trip or final_trip else baseline
        with (
            mock.patch.object(scope, "available_bytes", return_value=170 * 2**30),
            mock.patch.object(scope.subprocess, "Popen", side_effect=popen),
            mock.patch.object(scope, "properties", side_effect=properties),
            mock.patch.object(
                scope, "cgroup_path", return_value=Path("/fake-owned-cgroup")
            ),
            mock.patch.object(
                scope,
                "cgroup_sample",
                return_value={
                    "files": {
                        "memory.max": str(memory_bytes),
                        "memory.swap.max": "0",
                        "memory.events": "oom 0\noom_kill 0\n",
                    },
                    "errors": {},
                },
            ),
            mock.patch.object(
                scope, "global_resource_sample", side_effect=[baseline, final]
            ) as samples,
            mock.patch.object(scope.WholeCommandGlobalGuard, "start", new=start_guard),
            mock.patch.object(scope.os, "write", side_effect=gate),
            mock.patch.object(scope, "cleanup", side_effect=cleanup),
        ):
            status = scope.supervise(
                output,
                ["simulated-weight-hash-then-server"],
                memory_bytes,
                5,
                1,
                1,
                160 * 2**30,
                whole_command_global_guard=enabled,
            )
            self.assertEqual(samples.call_count, 2 if enabled else 0)
        self.assertTrue(state["started"])
        self.assertTrue(state["cleaned"])
        self.assertTrue((output / "scope-end.json").exists())
        self.assertTrue((output / "cgroup-samples.jsonl").exists())
        return status, json.loads((output / "result.json").read_text())

    def test_hash_guard_uses_owned_cleanup_and_preserves_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            status, result = self.run_mocked_supervisor(
                output, enabled=True, hash_trip=True
            )
            evidence = json.loads(
                (output / "whole-command-global-guard.json").read_text()
            )
            self.assertFalse((output / "child-result.json").exists())
            self.assertGreaterEqual(
                len(
                    (output / "whole-command-global-samples.jsonl")
                    .read_text()
                    .splitlines()
                ),
                2,
            )
        self.assertEqual(status, 1)
        self.assertFalse(result["passed"])
        self.assertEqual(result["failure"]["type"], "WholeCommandGlobalGuardExceeded")
        self.assertTrue(result["cleanup"]["verified"])
        self.assertTrue(result["final_cgroup_read_complete"])
        self.assertIn("not process- or scope-attributed", evidence["attribution"])
        self.assertEqual(
            evidence["trigger"]["reasons"][0]["limit"], "maximum_swap_out_mib"
        )

    def test_short_successful_child_cannot_hide_final_swap_trigger(self):
        with tempfile.TemporaryDirectory() as directory:
            status, result = self.run_mocked_supervisor(
                Path(directory), enabled=True, final_trip=True
            )
        self.assertEqual(result["command_result"]["returncode"], 0)
        self.assertEqual(status, 1)
        self.assertFalse(result["passed"])
        self.assertEqual(result["failure"]["type"], "WholeCommandGlobalGuardExceeded")

    def test_disabled_default_does_not_read_global_counters(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            status, result = self.run_mocked_supervisor(output, enabled=False)
            self.assertFalse((output / "whole-command-global-baseline.json").exists())
        self.assertEqual(status, 0)
        self.assertTrue(result["passed"])
        self.assertNotIn("whole_command_global_guard", result)


@unittest.skipUnless(
    os.environ.get("MEMORY_SCOPE_LIVE_ROOT"),
    "Requires host systemd/cgroup access and a fresh MEMORY_SCOPE_LIVE_ROOT; "
    "creates 128 MiB scopes and deliberately tests OOM/process termination",
)
class LiveMemoryScopeTests(unittest.TestCase):
    def output(self, name):
        root = Path(os.environ["MEMORY_SCOPE_LIVE_ROOT"]).resolve()
        self.assertTrue(root.is_relative_to(scope.BULK))
        path = root / name
        path.mkdir(parents=True, exist_ok=False)
        return path

    def run_scope(self, name, code, *, timeout=5, fd=None):
        output = self.output(name)
        status = scope.supervise(
            output,
            [sys.executable, "-c", code],
            128 * 2**20,
            timeout,
            1,
            0.05,
            2**30,
            fd,
        )
        result = json.loads((output / "result.json").read_text())
        self.assertTrue(result["cleanup"]["verified"], result)
        return status, result, output

    def test_success_and_inherited_lock(self):
        output_root = Path(os.environ["MEMORY_SCOPE_LIVE_ROOT"])
        lock_root = output_root / "test-lock"
        lock_root.mkdir(parents=True)
        with (lock_root / "gpu-experiment.lock").open("a") as original:
            fcntl.flock(original, fcntl.LOCK_EX | fcntl.LOCK_NB)
            code = (
                "import fcntl,os; "
                "fd=int(os.environ['BIG_MODELS_GPU_LOCK_FD']); "
                "fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB); "
                "print('$HOME'); os.close(fd)"
            )
            status, result, output = self.run_scope(
                "success-lock", code, fd=original.fileno()
            )
            self.assertEqual(status, 0, result)
            self.assertTrue(result["final_cgroup_read_complete"])
            self.assertEqual((output / "command.log").read_text().strip(), "$HOME")
            ready = json.loads((output / "anchor-ready.json").read_text())
            child = json.loads((output / "child-started.json").read_text())
            self.assertEqual(ready["process_group"], child["process_group"])
            with (
                (lock_root / "gpu-experiment.lock").open("a") as competitor,
                self.assertRaises(BlockingIOError),
            ):
                fcntl.flock(competitor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_nonzero_command_preserved(self):
        status, result, _ = self.run_scope("exit7", "raise SystemExit(7)")
        self.assertEqual(status, 7)
        self.assertFalse(result["passed"])
        self.assertEqual(result["command_result"]["returncode"], 7)

    def test_cgroup_oom_preserved(self):
        status, result, _ = self.run_scope("oom", "payload=bytearray(256*1024*1024)")
        self.assertEqual(status, 137, result)
        self.assertTrue(result["resource_evidence"]["oom_observed"], result)
        self.assertGreaterEqual(
            result["resource_evidence"]["maximum_observed_memory_events"]["oom_kill"], 1
        )

    def test_timeout_removes_ignoring_descendant(self):
        code = (
            "import os,signal,time; "
            "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
            "os.fork(); time.sleep(60)"
        )
        status, result, _ = self.run_scope("timeout-descendant", code, timeout=0.3)
        self.assertEqual(status, 124, result)
        self.assertTrue(result["command_result"]["timed_out"])

    def test_repeated_termination_cleanup(self):
        output = Path(os.environ["MEMORY_SCOPE_LIVE_ROOT"]) / "repeat-term"
        argv = [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "scripts/with_memory_scope.py"),
            "--output",
            str(output),
            "--memory-max-gib",
            "0.125",
            "--minimum-available-gib",
            "1",
            "--command-timeout",
            "10",
            "--shutdown-timeout",
            "1",
            "--sample-interval",
            "0.05",
            "--",
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
        ]
        child = subprocess.Popen(argv, start_new_session=True)
        try:
            until = time.monotonic() + 10
            while not (output / "child-started.json").exists():
                self.assertIsNone(child.poll())
                self.assertLess(time.monotonic(), until)
                time.sleep(0.05)
            child.send_signal(signal.SIGTERM)
            time.sleep(0.05)
            if child.poll() is None:
                child.send_signal(signal.SIGTERM)
            self.assertEqual(child.wait(timeout=15), 143)
            result = json.loads((output / "result.json").read_text())
            self.assertTrue(result["cleanup"]["verified"], result)
            self.assertEqual(result["failure"]["signal"], 15)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
