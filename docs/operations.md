# Operating the Lab

## Environment

For the CPU walkthrough, start in the repository root with Linux, Git and Python 3.13. No model download, private storage or GPU is needed. [Reader walkthrough](../examples/reviewing-worker-output/README.md)

For developer tooling on x86-64 Linux, enter the pinned shell with `nix develop`. The flake supplies Git, Python, Node and the pinned quality tools. Live inference also needs local model weights and a compatible inference backend. The workstation recipes expect the private model and experiment stores below `/bulk/dlk`, a Linux user service manager, Bubblewrap and GPU service controls. The flake does not build the inference backend. A port should supply its own storage, backend, weight and service bindings and verify isolation on the target host before launching model code. This release has no live DGX Spark measurement.

`./lab doctor` inspects the workstation setup. `./lab setup` is specific to the original storage layout. Check the paths and guard conditions before using it on a new machine. [Host checks](../scripts/lab.py) · [Sandbox boundary](isolation.md)

## Delegated work (MVP)

The preparation example reconstructs a complete historical assignment offline. The portable spec identifies the starter files, allowed edits, structural check, budgets and historical recipe. The included registries resolve profile and protocol inputs relative to the project and verify their original content hashes. The launch arguments still identify hardware, weights and backend paths on the measured workstation. Registration and dispatch check the frozen Python dependency digests against the checkout’s selected virtual environment. External dependency paths retain their recorded locations and digests. A host with different inputs needs a new verified freeze. On a port, document a new recipe identity for changed model or configuration bytes. [Preparing a package](../examples/preparing-worker-package/README.md) · [Delegate recipes](../configs/delegate-recipes-v1.json) · [Review and application](delegation-artifacts.md)

A live operator must schedule one GPU workload at a time, check active requests, record the session-entry state of `gpu-voice` and `ollama-background` and verify restoration on exit. The Worker gets only the selected workspace; the verifier gets its own isolated execution. The Maintainer separately reviews the patch and its handoff. [Preparing an assignment](delegate-preparation.md) · [Evidence and review](handoff-receipts.md)

A live rehearsal on the reference RTX 4090 used a clean public clone and a fresh virtual environment installed from its lockfile. The Worker corrected the walkthrough’s landing-commit link. The independent evaluator checked the entire edited file, and the Maintainer verified the public destination before applying the patch. Worker time was 34.5 seconds and dispatch through cleanup was 55.9 seconds. The run used the workstation’s existing model store, inference backend and service controls. [Rehearsal receipt](../results/public-worker-rehearsal-001.json)

### Attribution for landed Worker contributions

Lead the commit message with the change. Say what Worker wrote, what the Maintainer independently verified, and what the Maintainer changed before landing it. Keep the ordinary Git author and committer identities. Use the job and recipe to trace a model contribution without inventing an email address.

Put the following trailers at the end of the message. Use the registered recipe ID and link the review to a versioned receipt a reader can open.

```text
Delegate-Job: <job ID>
Delegate-Package: <frozen package ID>
Delegate-Recipe: <recipe ID>
Delegate-Review: results/<review-receipt>.json
Delegate-Completion: clean
Delegate-Repairs: none
```

Use `clean` when Worker completed its handoff. If it timed out with useful edits on disk, record `incomplete (timeout)` and say which edits the Maintainer recovered and accepted. Replace `none` with a short description when the Maintainer repairs the submission. Preserve the original artifact and record the independent checks separately from Worker's claims. A withheld reference solution belongs in the review history. If its code ships, credit its author for that code.

- **Accepted as submitted.** Worker supplied the checkpoint eligibility predicate and 14 tests. The Maintainer verified the helper in isolation and checked that implementations that always allowed or always denied finalization failed the controls. Caller integration was separate Maintainer work. [Landing commit](https://github.com/othercriteria/harness-lab/commit/1410543b7ca025d219d6d9400272a64d9ca01d0f) · [Receipt](../results/checkpoint-finalization-worker-landing-001.json)
- **Accepted with repairs.** Worker supplied the residency estimator's adjacency and pricing tests. The Maintainer corrected inconsistent timings, consolidated duplicate cases, expanded boundary and batch coverage, and registered the reviewed suite in portable CI. The original tests caught eight faulty implementations. The landed suite caught nine. [Landing commit](https://github.com/othercriteria/harness-lab/commit/967265eeaf33f72fa0f7501fd7ba007bfa66e5e5) · [Receipt](../results/worker-residency-accounting-tests-001.json)

## Watch the outer harness

From a clean clone, `python3 -S scripts/observe.py --example` opens a bundled Worker job with the same timeline and review displays. [Inspect the recorded job](../examples/replaying-worker-trace/README.md#open-the-job-in-observatory)

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

### Workstation checks

On x86-64 Linux with Nix and direnv, review the checkout’s `.envrc` and allow it
with `direnv allow`. In the project dev shell, run `uv sync --locked` once
to install the runtime needed by full test discovery. If the workstation’s
shared uv cache is unavailable, use `uv sync --locked --cache-dir .cache/uv`.
Then run `./lab check` from the repository root.

The command runs the same maintained lint and type checks as CI, a Ruff pass
for syntax and likely execution errors across `scripts/`, `tasks/` and
`tests/`, and full Python test discovery using the checkout’s virtual
environment. Live cgroup tests require explicit opt-in via
`MEMORY_SCOPE_LIVE_ROOT` and ordinarily appear as skipped. The fixture stage
runs the trusted authored starters and references against their public and
acceptance suites, checks expected test counts and outcomes, and verifies the
fixture bytes remain intact. It names each task requiring isolated evaluation
or outer adjudication. Those tasks have no host validation result. A failed
stage returns a nonzero exit status. To inspect the fixture test counts and
outcomes, run `python scripts/check_fixtures.py --host-eligible --report fixture-report.json`.

For a repository-wide style inventory, run `ruff check scripts tasks tests` and
`ruff format --check scripts tasks tests` separately. Both include historical
source and frozen fixtures with known style differences. Preserve their
recorded bytes when addressing findings.
