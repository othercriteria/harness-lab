# Operating the Lab

## Environment

For the CPU walkthrough, start in the repository root with Linux, Git and Python 3.13. No model download, private storage or GPU is needed. [Reader walkthrough](../examples/reviewing-worker-output/README.md)

For developer tooling on x86-64 Linux, enter the pinned shell with `nix develop`. The flake supplies Git, Python, Node and the pinned quality tools. Live inference also needs local model weights and a compatible inference backend. The workstation recipes expect the private model and experiment stores below `/bulk/dlk`, a Linux user service manager, Bubblewrap and GPU service controls. The flake does not build the inference backend. A port should supply its own storage, backend, weight and service bindings and verify isolation on the target host before launching model code. This release has no live DGX Spark measurement.

`./lab doctor` inspects the workstation setup. `./lab setup` is specific to the original storage layout. Check the paths and guard conditions before using it on a new machine. [Host checks](../scripts/lab.py) · [Sandbox boundary](isolation.md)

## Delegated work (MVP)

The preparation example reconstructs a complete historical assignment offline. The portable spec identifies the starter files, allowed edits, structural check, budgets and historical recipe. The included registries resolve profile and protocol inputs relative to the project and verify their original content hashes. The launch arguments still identify hardware, weights and backend paths on the measured workstation. The historical runtime freeze also binds installed Python dependency files on the original workstation. A new host needs its own verified runtime freeze before live registration. On a port, document a new recipe identity for changed model or configuration bytes. [Preparing a package](../examples/preparing-worker-package/README.md) · [Delegate recipes](../configs/delegate-recipes-v1.json) · [Review and application](delegation-artifacts.md)

A live operator must schedule one GPU workload at a time, check active requests, record the session-entry state of `gpu-voice` and `ollama-background` and verify restoration on exit. The Worker gets only the selected workspace; the verifier gets its own isolated execution. The Maintainer separately reviews the patch and its handoff. [Preparing an assignment](delegate-preparation.md) · [Evidence and review](handoff-receipts.md)

## Watch the outer harness

On the original workstation, `./lab observe` starts the read-only loopback dashboard. It reads the experiment store, displays timelines and tool calls, and distinguishes a submitted patch from its verified review and application. The portable examples include selected records that can be read without running that service. [Replay a trace](../examples/replaying-worker-trace/README.md)

## Portable developer checks

Enter the pinned dev shell with `nix develop` or direnv. On Linux with
Python 3.13, you can also activate a separate virtual environment and run
`python -m pip install -r requirements-dev.txt`. Run these commands from the
repository root. The flake checks its five tool versions against the CI pins.

| Command | What it runs |
| --- | --- |
| `poe lint` | Ruff 0.16.4 with rules E4, E7, E9, F, I and UP on the checkpoint code, its selected tests, the portable test list and the ATIF replay example. Formatting is outside this gate. |
| `poe typecheck` | ty on the checkpoint policy, its evidence auditor and the focused policy tests. The live controller also consumes the same parsed policy. |
| `poe test` | The portable Python unittest selection in `tests/portable.py`. |
| `poe check` | Lint, type checking and the portable Python tests. |
| `poe coverage` | The same Python test selection under coverage.py, with statement and branch measurements for `scripts/` and a per-module report. |

CI records covered and total statements and branches in each run summary.
Compare runs with the same test selection and source scope. The report measures
the test process. Standalone example commands, subprocesses, Node rendering,
workstation checks and model runs can exercise additional paths. Inspect
callers and runtime evidence before treating an uncovered path as dead code.
The broader workstation command `./lab check` includes a formatting check,
full test discovery and fixture validation.

Run `poe --help` to list the tasks. To opt in for a clone, run
`poe install-hooks` in the developer environment. The installed hook needs
`poe`, `ruff` and `ty` on the commit process's PATH. With Nix, commit from the
dev shell or use `nix develop --command git commit` from a plain shell.
Both hooks run their full Poe
selection, including files outside the commit. Pre-commit temporarily stashes
unstaged tracked changes, so it checks the indexed versions. Untracked files
remain visible. Both checks are read-only. Use `pre-commit run --all-files` for
a manual check and `pre-commit uninstall` to remove the hook. Tests, coverage,
historical examples, prose checks and Node rendering run separately in CI.
