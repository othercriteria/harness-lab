"""Exercise pinned Harbor's single-step clocks using prepared offline log-task images."""

import argparse
import asyncio
import json
import time
from pathlib import Path
from uuid import uuid4

from harbor.agents.nop import NopAgent
from harbor.models.trial.config import TrialConfig
from harbor.models.verifier.result import VerifierResult
from harbor.trial.hooks import TrialEvent
from harbor.trial.trial import Trial
from harbor.verifier.base import BaseVerifier


class MarkerAgent(NopAgent):
    def __init__(self, *, delay, **kwargs):
        super().__init__(**kwargs)
        self.delay = delay

    async def run(self, instruction, environment, context):
        result = await environment.exec(command="echo timing-marker > /app/summary.csv")
        if result.return_code:
            raise RuntimeError("Could not write the timing marker")
        await asyncio.sleep(self.delay)


class MarkerVerifier(BaseVerifier):
    def __init__(self, *, delay, **kwargs):
        super().__init__(**kwargs)
        self.delay = delay

    async def verify(self):
        result = await self.environment.exec(command="cat /app/summary.csv")
        if result.return_code or result.stdout.strip() != "timing-marker":
            raise RuntimeError("Marker did not reach the separate verifier")
        (self.trial_paths.trial_dir / "transferred-marker.txt").write_text(
            result.stdout
        )
        await asyncio.sleep(self.delay)
        return VerifierResult(rewards={"reward": 1})


async def run(task, output):
    output.mkdir(parents=True, exist_ok=False)
    run_id = uuid4().hex[:12]
    for case, agent_delay, agent_limit, verify_delay, verify_limit, error in (
        ("complete", 1, 5, 2, 5, None),
        ("agent-timeout", 20, 4, 2, 5, "AgentTimeoutError"),
        ("verifier-timeout", 1, 5, 20, 4, "VerifierTimeoutError"),
        ("both-timeout", 20, 4, 20, 4, "AgentTimeoutError"),
    ):
        config = TrialConfig(
            task={"path": task},
            agent={
                "import_path": "timing_control:MarkerAgent",
                "override_timeout_sec": agent_limit,
                "kwargs": {"delay": agent_delay},
            },
            verifier={
                "import_path": "timing_control:MarkerVerifier",
                "override_timeout_sec": verify_limit,
                "kwargs": {"delay": verify_delay},
            },
            environment={"type": "docker", "kwargs": {"auto_mounting": False}},
            trial_name=f"h83-{case}-{run_id}",
            trials_dir=output / case,
        )
        trial = await Trial.create(config)
        offsets = {}

        async def record(event):
            offsets[event.event.value] = round(time.monotonic() - start, 4)

        for event in TrialEvent:
            trial.add_hook(event, record)
        start = time.monotonic()
        result = await trial.run()
        elapsed = time.monotonic() - start
        recorded = (result.finished_at - result.started_at).total_seconds()
        actual_error = result.exception_info and result.exception_info.exception_type
        reward = result.verifier_result and result.verifier_result.rewards
        expected_reward = None if verify_delay > verify_limit else {"reward": 1}
        marker = (trial.paths.trial_dir / "transferred-marker.txt").read_text().strip()
        observed = {
            "case": case,
            "trial": config.trial_name,
            "agent_delay": agent_delay,
            "agent_limit": trial.agent_timeout_sec,
            "verifier_delay": verify_delay,
            "verifier_limit": trial.verifier_timeout_sec,
            "hook_monotonic_offsets": offsets,
            "run_monotonic_seconds": elapsed,
            "whole_trial_seconds": recorded,
            "marker": marker,
            "error": actual_error,
            "reward": reward,
            "reward_valid": result.reward_valid,
        }
        (output / case / "timing.json").write_text(
            json.dumps(observed, indent=2) + "\n"
        )
        print(case, actual_error, reward, f"{elapsed:.3f} s", flush=True)
        if (actual_error, reward, result.reward_valid, marker) != (
            error,
            expected_reward,
            expected_reward is not None,
            "timing-marker",
        ):
            raise RuntimeError(f"Unexpected timing control result: {observed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared_log_task", type=Path)
    parser.add_argument("fresh_output", type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.prepared_log_task.resolve(), args.fresh_output.resolve()))
