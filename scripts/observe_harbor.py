"""Read Harbor's outer results and reuse Observatory's native Worker trace reader."""

from datetime import datetime

from observe import NAME, Evidence, RunCatalog


def seconds(phase):
    if phase and phase.get("started_at") and phase.get("finished_at"):
        return (
            datetime.fromisoformat(phase["finished_at"])
            - datetime.fromisoformat(phase["started_at"])
        ).total_seconds()
    return None


class HarborSource(Evidence):
    def config(self, root):
        config = self.read(root / "config.json") or {}
        agent = config.get("agent") or {}
        if (
            agent.get("import_path") == "harbor_worker:Worker"
            and agent.get("kwargs", {}).get("control") is False
        ):
            return agent
        return None

    def trial(self, run, trial):
        root = self.child(self.root, trial)
        if not self.config(root):
            raise ValueError("Not a scored Harbor Worker trial")
        return self.child(self.child(root, "agent"), "worker")

    def attempts(self):
        rows = []
        for path in self.root.iterdir():
            if NAME.fullmatch(path.name) and path.is_dir() and not path.is_symlink():
                agent = self.config(path)
                if agent:
                    rows.append(((path / "config.json").stat().st_mtime, path, agent))
        return sorted(rows)

    def trace_summary(self, root):
        result = self.read(root.parents[1] / "result.json") or {}
        outcome = self.read(root / "outcome.json") or {}
        handoff = self.read(root / "final-handoff.json")
        checks = self.read(root.parents[1] / "verifier/ctrf.json") or {}
        error = result.get("exception_info") or {}
        if not (result or outcome or handoff):
            return {}
        trial_error = (
            {"type": error["exception_type"], "message": error.get("exception_message")}
            if error.get("exception_type")
            else None
        )
        return {
            "upstream_reward": (result.get("verifier_result") or {})
            .get("rewards", {})
            .get("reward"),
            "reward_valid": result.get("reward_valid"),
            "upstream_checks": checks.get("results", {}).get("summary"),
            "agent_outcome": outcome,
            "final_handoff": handoff,
            "agent_seconds": seconds(result.get("agent_execution")),
            "verifier_seconds": seconds(result.get("verifier")),
            "whole_trial_seconds": seconds(result),
            "trial_error": trial_error,
            "agent_error": trial_error
            if error.get("exception_type") == "AgentTimeoutError"
            else None,
        }

    def trace(self, run, trial, start=None):
        trace = super().trace(run, trial, start)
        cost = trace["cost_breakdown"]
        summary = trace["summary"] or {}
        if cost:
            finished = summary.get("whole_trial_seconds") is not None
            trace["cost_breakdown"] = {
                **cost,
                "status": "recorded Harbor trial"
                if finished
                else "recorded calls so far",
                "task_seconds": summary.get("whole_trial_seconds"),
                "verification_seconds": summary.get("verifier_seconds"),
                "note": "Task time covers the full Harbor trial, including environment setup, transfer and grading. The agent time is shown separately. Request timers overlap backend timers. Loading and prompt warming precede the trial.",
            }
        return trace

    def run(self, name, details=True):
        trials = []
        models = set()
        attempts = self.attempts()
        for _, path, agent in attempts:
            w = self.trial(name, path.name)
            summary = self.trace_summary(w)
            reward = summary.get("upstream_reward")
            error = summary.get("trial_error")
            state = (
                "stopped with error"
                if error
                else f"upstream reward {reward:g}"
                if reward is not None
                else "awaiting verifier"
                if summary.get("agent_outcome")
                else "awaiting Harbor result"
            )
            models.add(agent["model_name"])
            config = self.read(w / "effective-config.json") or {}
            limits = config.get("limits") or {}
            trials.append(
                {
                    "name": path.name,
                    "kind": "harbor",
                    "has_trace": w.is_dir(),
                    "task": agent["kwargs"]["task_key"],
                    "state": state,
                    "reward": reward,
                    "reward_valid": summary.get("reward_valid"),
                    "outcome": (summary.get("agent_outcome") or {}).get("exit_status"),
                    "seed": limits.get("seed"),
                    "configuration": {
                        key: limits.get(key)
                        for key in (
                            "seed",
                            "agent_wall_seconds",
                            "context_capacity_tokens",
                            "reasoning_budget_tokens",
                            "step_limit",
                            "tool_call_limit",
                        )
                    },
                    "boundary": self.read(path / "agent-boundary.json"),
                    "whole_trial_seconds": summary.get("whole_trial_seconds"),
                    "seconds": summary.get("agent_seconds"),
                    "verifier_seconds": summary.get("verifier_seconds"),
                }
            )
        return {
            "name": name,
            "kind": "harbor",
            "model": ", ".join(sorted(models)),
            "protocol": "Harbor · Worker",
            "trials": trials,
            "state": trials[-1]["state"] if trials else "waiting for Worker",
            "source": str(self.root),
            "modified": attempts[-1][0] if attempts else None,
            "config": {"source": "Harbor trial and Worker effective configuration"},
            "lifecycle": {},
        }


class HarborCatalog(RunCatalog):
    def __init__(self, directories):
        self.sources = {}
        for directory in directories:
            directory = directory.resolve()
            if not NAME.fullmatch(directory.name) or directory.name in self.sources:
                raise ValueError(
                    "Harbor experiment roots need distinct valid directory names"
                )
            if (
                not (directory / "trials").is_dir()
                or (directory / "trials").is_symlink()
            ):
                raise ValueError("Harbor experiment requires a trials directory")
            self.sources[directory.name] = HarborSource(directory / "trials")

    def run_index(self):
        return [
            (name, max((row[0] for row in source.attempts()), default=0))
            for name, source in self.sources.items()
        ]

    def run(self, run, details=True):
        return self.sources[run].run(run, details)

    def trace(self, run, trial, start=None):
        return self.sources[run].trace(run, trial, start)

    def artifact(self, run, trial, name):
        return self.sources[run].artifact(run, trial, name)
