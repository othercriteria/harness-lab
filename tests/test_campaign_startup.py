"""Exercise the campaign entry points with public config and synthetic host state."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import launch_pilot
import model_registry
import serve_trial


class CampaignStartupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.campaign = self.root / "campaign"
        self.args = ["lab", "--profile", "qwen36-instruct", "--tasks", "config-overlay"]

    def plan(self, extra):
        buffer = io.StringIO()
        argv = [*self.args, "--output", str(self.campaign), "--dry-run", *extra]
        with (
            patch.object(launch_pilot, "RUNS_ROOT", self.root),
            patch.object(sys, "argv", argv),
            patch.object(os, "execv", side_effect=AssertionError("unexpected launch")),
            contextlib.redirect_stdout(buffer),
        ):
            launch_pilot.main()
        self.assertFalse(self.campaign.exists())
        # Each owner receives its own arguments followed by -- and its child.
        layers = {}
        args = json.loads(buffer.getvalue())
        while "--" in args:
            end = args.index("--")
            layers[Path(args[1]).stem] = args[2:end]
            args = args[end + 1 :]
        layers[Path(args[1]).stem] = args[2:]
        return layers

    def test_warmup_budget_is_reserved_once_outside_scored_trials(self):
        request = self.root / "initial.json"
        request.write_text(
            json.dumps(
                {
                    "messages": [
                        {"role": "system", "content": "Implement the task."},
                        {"role": "user", "content": "Public task"},
                    ]
                }
            )
        )
        seeds = ["--seeds", "7", "8"]
        cold = self.plan(seeds)
        warm = self.plan([*seeds, "--prefix-warmup-request", str(request)])
        self.assertEqual(
            list(warm),
            [
                "with_background_released",
                "with_speech_released",
                "with_ollama_released",
                "with_memory_scope",
                "serve_trial",
            ],
        )
        timeouts = []
        for wrapper in list(warm)[:-1]:
            seconds = int(warm[wrapper][warm[wrapper].index("--command-timeout") + 1])
            cold_seconds = int(
                cold[wrapper][cold[wrapper].index("--command-timeout") + 1]
            )
            self.assertEqual(seconds - cold_seconds, 150)
            timeouts.append(seconds)
        self.assertTrue(all(a > b for a, b in zip(timeouts, timeouts[1:])))
        self.assertIn("--whole-command-global-guard", warm["with_memory_scope"])
        self.assertIn("--require-inherited-gpu-lock", warm["with_memory_scope"])
        self.assertEqual(
            warm["serve_trial"][-5:],
            ["--seeds", "7", "8", "--prefix-warmup-request", str(request)],
        )

    def test_guard_records_crossing_before_launch_and_closes_campaign(self):
        mib = 2**20

        def sample(at, growth, full_us):
            return {
                "available": 128 * 2**30,
                "monotonic": at,
                "swap_out_bytes": 500 * mib + growth,
                "memory_pressure_total_us": {"full": full_us},
            }

        before = sample(100, 0, 1_000_000)
        boundary = sample(102, 128 * mib, 1_040_000)
        over = sample(107, 128 * mib + 4096, 1_090_000)

        self.campaign.mkdir()
        (self.campaign / "inputs.json").write_text('{"files":{}}')
        experiment = self.campaign / "experiment"
        registry = self.root / "registry"
        argv = [*self.args, "--output", str(experiment)]

        def simulate_hashing(profile, *, mode, guard):
            guard()
            self.fail("crossing the cumulative swap limit must stop hashing")

        with (
            patch.object(serve_trial, "RUNS_ROOT", self.root),
            patch.object(sys, "argv", argv),
            patch.dict(os.environ, BIG_MODELS_GPU_LOCK_FD="synthetic"),
            patch.object(
                serve_trial.lifecycle,
                "gpu_experiment_lock",
                return_value=contextlib.nullcontext(),
            ),
            patch.object(
                serve_trial,
                "resources",
                side_effect=[before, boundary, over, dict(over)],
            ),
            patch.object(
                serve_trial, "local_json", return_value={"models": []}
            ) as local,
            patch.object(
                serve_trial, "verify_profile_weights", side_effect=simulate_hashing
            ) as verify,
            patch.object(
                serve_trial.subprocess,
                "Popen",
                side_effect=AssertionError("unexpected process"),
            ),
            patch.object(
                serve_trial,
                "record_campaign",
                side_effect=lambda path: model_registry.record_campaign(path, registry),
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(serve_trial.main(), 1)
        verify.assert_called_once()
        local.assert_called_once()
        observations = [
            json.loads(line)
            for line in (experiment / "telemetry.jsonl").read_text().splitlines()
        ]
        self.assertEqual(
            [row["swap_out_growth_bytes"] for row in observations],
            [128 * mib, 128 * mib + 4096],
        )
        self.assertEqual(
            [row["interval_full_memory_stall_percent"] for row in observations], [2, 1]
        )
        summary = json.loads((experiment / "summary.json").read_bytes())
        self.assertIn("swap-out guard", summary["error"]["message"])
        self.assertFalse(summary["completed"])
        self.assertTrue(summary["client_stopped"] and summary["server_stopped"])
        receipt = json.loads((experiment / "registry-receipt.json").read_bytes())
        evidence = json.loads(Path(receipt["observation"]).read_bytes())
        self.assertEqual(evidence["stage"], "startup")
        self.assertEqual(evidence["trials"], [])
