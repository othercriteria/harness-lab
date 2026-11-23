# Local Harness Lab

How much coding work can you delegate to a local model on a single workstation GPU and confidently accept afterwards? Local Harness Lab gives a model a small repository task, a time budget, and an isolated workspace. It records the edits, tool calls and checks so a maintainer can decide whether to use the result.

**Start here:** [Review two Worker submissions](examples/reviewing-worker-output/README.md). Inspect a patch that landed and the command behind a handoff that was rejected. Both examples use evidence included in this repository.

## A change the Worker made

When a coding session runs low on context, the harness can ask the model to save a note, clear older messages, and continue. In two recorded reviews, the model had already written its deliverable. Its note said that only submission remained. Both times it reset and reread its output before submitting.

We gave our local coding agent, the **Worker**, a small piece of the fix. It wrote a Python function that decides when the harness can offer final submission at a checkpoint, plus 14 tests. A **Maintainer** independently checked the patch, applied it, and wired the function into the running harness. You can inspect the [landed change](examples/reviewing-worker-output/accepted/worker.patch) and its [review and application record](results/checkpoint-finalization-worker-landing-001.json).

In the follow-up experiment, the Worker submitted directly in both runs where it got that choice. One of those handoffs still failed outer review. The worked example lets you inspect the evidence that led to that decision. All six probes completed cleanly and passed structural checks. Three earned full acceptance. [Experiment results](results/checkpoint-finalization-conclusions-001.json)

## Try the Lab

- **In a browser**, review the accepted patch and rejected handoff in the [worked example](examples/reviewing-worker-output/README.md).
- **On CPU**, start at the root of a clone on Linux with Git and Python 3.13. The command below checks three recorded evidence files against their inventory. Then follow the [walkthrough instructions](examples/reviewing-worker-output/README.md) to run the 14 policy tests using the bundled files from development revision `8f98938c`. For checks on the current revision, run `poe check` in the dev shell. [Hosted CI workflow](.github/workflows/ci.yml) · [Developer checks](docs/operations.md#portable-developer-checks)
- **For live inference**, the workstation recipes assume an `x86_64-linux` dev shell, a validated GPU backend and weights, local storage, and Linux sandbox and service controls. A DGX Spark operator can start with the CPU example, then identify replacements for the shell, backend, paths and controls. Spark inference has yet to be measured here. [Flake](flake.nix) · [Workstation setup](docs/operations.md#environment) · [Isolation](docs/isolation.md)

```sh
python3 examples/check_evidence.py examples/reviewing-worker-output/files.json
```

## How work reaches the repository

The Maintainer selects the source files the Worker can see and the paths it can edit. **Delegate** packages that snapshot, dispatches the job and collects the proposed changes. The Worker uses a coding loop built on mini-SWE-agent. A separate **Verifier** runs checks outside the Worker’s workspace. The Maintainer can then inspect the diff and handoff, accept or reject the work, and apply an accepted patch after checking that its inputs are still current. [Delegation mechanics](docs/delegation-artifacts.md) · [Isolation and limits](docs/isolation.md)

For new model-assisted changes, `git log --grep='^Model-Author:'` shows which model wrote which part of a landing and where to find its evidence. [Model credit guide](docs/model-credit.md)

## Explore the lab

- **Inspect a Worker in Observatory.** Open a recorded tool call, its output, the proposed patch and the reason it was rejected. The example runs locally with Python 3.13. [View the recorded job](examples/replaying-worker-trace/README.md#open-the-job-in-observatory)
- **Compare coding agents.** Worker, Aider, OpenCode and mini-SWE-agent took the same assignments on one local model. On an issue-export feature, all 32 resulting artifacts passed the frozen code checks. Only one handled a valid input the checks missed. The guide compares timing and reviewed results across four tasks. [Comparison and results](docs/standard-worker-comparison.md)
- **Compare on Terminal-Bench 2.1.** Worker and Harbor’s Terminus-2 used the same local Qwen model on five selected tasks. Both passed four upstream verifiers, including a Coq proof that also passed an independent kernel check. On async cancellation, their submissions failed the same check for different reasons. [Task results and diagnostics](examples/harbor-terminus/README.md#follow-up-results) · [Evaluation clocks and conditions](examples/harbor-terminus/timing.md)
- **Run or review a job.** Prepare the inputs for a real Observatory fix from a fresh clone, then follow the job through review. [Prepare a Worker package](examples/preparing-worker-package/README.md) · [Preparing an assignment](docs/delegate-preparation.md) · [Operator guide](docs/operations.md)
- **Explore the ladder.** The published tasks range from a 60-second JavaScript repair to a 720-second Git backport. [Tasks, ceilings and evidence](docs/ladder.md)
- **Understand this release.** Browse the public development history and [issue tracker](https://github.com/othercriteria/harness-lab/issues). The three offline examples include the historical files they need. [Snapshot provenance and scope](SNAPSHOT.md)

## License

The Lab’s original code and documentation are available under the [MIT License](LICENSE). Third-party material carries its own license terms. [Third-party attributions and license notices](docs/third-party-attribution.md)
