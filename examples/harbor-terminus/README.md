# Run Terminus-2 and Worker on Terminal-Bench tasks

Harbor runs two coding agents against the same local Qwen model and small panels of Terminal-Bench 2.1 tasks. Terminus-2 sends keystrokes to a persistent terminal. Worker uses its usual native tools and a fresh shell for each command. Both agents work in disposable containers. Harbor transfers each submitted artifact into a separate offline verifier and records the upstream reward. [Terminus-2 baseline](https://github.com/othercriteria/harness-lab/issues/78) · [Worker smoke](https://github.com/othercriteria/harness-lab/issues/79)

## Prepare and check the tasks on CPU

Use Linux, Docker with Compose, Python 3.13, uv, Git and a fresh bulk directory. The commands below start at the Lab repository root. Docker needs network access to build the images. The task and verifier run offline. The two controls for each task should produce rewards of 1 for the reference and 0 for the unchanged workspace.

```sh
example="$PWD/examples/harbor-terminus"
export HARBOR_SMOKE_ROOT=/bulk/dlk/local-harness/research/harbor-smoke-reproduction
mkdir -p "$HARBOR_SMOKE_ROOT/controller-home"
git clone --filter=blob:none --no-checkout https://github.com/harbor-framework/terminal-bench-2-1 "$HARBOR_SMOKE_ROOT/upstream"
git -C "$HARBOR_SMOKE_ROOT/upstream" sparse-checkout set tasks/polyglot-c-py tasks/fix-git
git -C "$HARBOR_SMOKE_ROOT/upstream" checkout --detach 12b7565679ce5006230b820666353673a133db93
uv venv --python 3.13 "$HARBOR_SMOKE_ROOT/.venv"
client="$HARBOR_SMOKE_ROOT/.venv/bin/python"
uv pip install --python "$client" -r "$example/requirements.txt"
python "$example/prepare.py" "$HARBOR_SMOKE_ROOT"
for task in polyglot-c-py fix-git; do
  for agent in oracle nop; do
    env -i PATH="$PATH" HOME="$HARBOR_SMOKE_ROOT/controller-home" \
      HARBOR_SMOKE_ROOT="$HARBOR_SMOKE_ROOT" HARBOR_TELEMETRY=0 LITELLM_LOCAL_MODEL_COST_MAP=True \
      "$client" "$example/trial.py" "$task" "$agent" "h78-$task-$agent-control" || exit 1
  done
done
```

Preparation pins the upstream task commit, the base images by digest, the verifier Python image, and the Harbor Python dependency versions used on the reference host. It records the locally built image IDs under `build/<task>/images.json`. The derivative images install terminal utilities from the distribution package repositories, so rebuilding later may produce different image IDs. The upstream pytest assertions are copied byte for byte. The offline launcher installs their runner at image build time and preserves the pytest options and binary reward convention. Harbor transfers `/app/polyglot` or the whole `/app/personal-site` repository, including Git metadata.

## Run one warm attempt per task

On the reference workstation, the following command holds one GPU lease for the pair. It needs the existing Lab weights, inference binary, user-service controls, and memory guard. Use a fresh label and lifecycle directory for a new pair. Other machines can run `trial.py TASK terminus-2 NAME http://127.0.0.1:PORT` with the equivalent owned local endpoint and a clean controller environment including `OPENAI_API_KEY=local-placeholder`.

```sh
label=terminus-reproduction-001
receipts="/bulk/dlk/local-harness/runs/h78-$label"
py="$PWD/.venv/bin/python"
"$py" scripts/with_background_released.py --output "$receipts/background" --command-timeout 2800 -- \
  "$py" scripts/with_speech_released.py --output "$receipts/voice" --command-timeout 2500 -- \
  "$py" scripts/with_ollama_released.py --output "$receipts/ollama" --command-timeout 2220 -- \
  "$py" scripts/with_memory_scope.py --output "$receipts/memory" --memory-max-gib 48 \
    --minimum-available-gib 48 --command-timeout 2040 --shutdown-timeout 90 \
    --require-inherited-gpu-lock --whole-command-global-guard -- \
  "$py" "$example/pair.py" "$HARBOR_SMOKE_ROOT" "$label"
```

Each warm-up sends the Terminus JSON prompt and the public instruction with an empty terminal pane and generates one discarded token. The scored trial starts with the actual pane. The server stays resident between tasks. The 600-second cap applies to agent execution. Read `trials/<name>/result.json` for each phase, `agent/trajectory.json` for the ATIF trace, and `verifier/ctrf.json` for the individual checks. The environment boundary and warm-up receipts sit beside the trial result. A shell timer around the entire command also counts image startup, server loading, artifact transfer, verifier execution and cleanup.

## Run Worker on the same images

Run `uv sync --locked` in the Lab dev shell to prepare `.venv/bin/python` for Worker. Harbor uses the separate environment in the bulk directory. The reference comparison checks all four runnable Linux/amd64 image manifests against the baseline receipt. Its saved image archive and GPU profile are workstation-local. To repeat that exact pairing, restore the recorded images with `docker load -i task-images-linux-amd64.tar` after preparation if necessary. For a smoke with your own build, pass `--prepared-images` to `trial.py`. This checks the images against the IDs your preparation recorded and writes the binding into the trial directory. A comparison on those images would need its own Terminus baseline. [Image identities and archive checksum](../../results/harbor-terminus-smoke-078.json)

Run these scripted rehearsals before using the GPU. Each one creates, reads and edits a marker, recovers its context under scripted pressure, reads the archived history from the next shell, then submits a structured handoff. The Git rehearsal also makes a commit and compares its identity and branch with those visible inside the verifier. Both upstream rewards should be zero because the edits only exercise the handoff.

```sh
for task in polyglot-c-py fix-git; do
  env -i PATH="$PATH" HOME="$HARBOR_SMOKE_ROOT/controller-home" \
    HARBOR_SMOKE_ROOT="$HARBOR_SMOKE_ROOT" HARBOR_TELEMETRY=0 LITELLM_LOCAL_MODEL_COST_MAP=True \
    "$client" "$example/trial.py" "$task" worker-control "h79-$task-control" --prepared-images || exit 1
done
```

For a single newly built task on an owned endpoint, use `trial.py TASK worker NAME http://127.0.0.1:PORT --prepared-images` in the clean controller environment above. For the reference scored Worker pair, choose a fresh label and receipts directory in the GPU command above and append `worker` to the final `pair.py` invocation. The warm-up sends one request with Worker’s actual tools, system prompt and public task and discards the single generated token. Each trial records its trajectory and handoff under `agent/worker/`. The model can read historical checks and work in the original image directory through `/workspace`. Bash commands run as an unprivileged user. Files in the workspace and `/tmp` persist between calls. The supervisor reaps background processes at the end of each call.

## Terminus-2 results on the reference workstation

| Task | Agent | Environment + agent setup | Verification phase | Whole Harbor trial | Upstream reward |
| --- | ---: | ---: | ---: | ---: | ---: |
| `polyglot-c-py` | 366.4 s | 4.2 s | 15.8 s | 397.8 s | 1 |
| `fix-git` | 157.7 s | 4.1 s | 16.1 s | 189.6 s | 1 |

Terminus-2 signaled completion on both tasks. On the polyglot task, Qwen repeatedly broke a working version while trying to silence compiler warnings, then recovered and exercised a wider numeric range. On the Git task, several terminal inputs went into a pager before Qwen regained the shell, recovered the detached commit and resolved a merge conflict. The upstream Git tests check two file contents. A separate read-only graph check confirmed that the submitted `master` contains the initial branch tip and the recovered commit.

The first scored requests reused 352 of 891 prompt tokens on polyglot and 253 of 794 on Git. Full-trial time includes artifact collection and environment teardown. Each baseline task has one observation. [Machine-readable results and trace identifiers](../../results/harbor-terminus-smoke-078.json) · [Paired Worker issue](https://github.com/othercriteria/harness-lab/issues/79)

## What changed with Worker

| Task | Worker agent | Terminus agent | Worker whole trial | Worker / Terminus upstream reward |
| --- | ---: | ---: | ---: | :---: |
| `polyglot-c-py` | 271.7 s | 366.4 s | 303.7 s | 1 / 1 |
| `fix-git` | 40.3 s | 157.7 s | 73.9 s | 1 / 1 |

Both Worker attempts submitted a structured handoff under the 600-second agent ceiling. Each agent used the same model, seed, task checksum and runnable images. On their first scored requests Worker reused 3,821 of 3,825 prompt tokens on polyglot and 3,725 of 3,729 on Git. The two agents have different prompts, tools and warm-up inputs. One paired seed supports a feasibility claim. A speed or reliability ranking would need repeated trials.

On Git, Worker used the reflog to identify the lost commit, inspected both sides of the conflict and merged it. It finished in eight model responses. A read-only graph check on the transferred repository confirmed that both original tips were ancestors of the checked-out `master`. Terminus reached the same graph condition after spending several turns in a pager.

On polyglot, Worker recovered its context once, repaired a C printing error and tested both language paths. Its handoff disclosed a fixed-width limit but placed the first overflow at `F(93)`, one input too early. A post-hoc check compiled both sealed submissions in isolated containers and compared each language path with independently computed values at 92, 93, 94 and 100. Worker’s C program gave wrong answers at 94 and 100 while exiting successfully. Its Python program and both Terminus paths passed all four. The upstream verifier exercises three smaller inputs. The task brief gives no upper bound.

**Adapter history.** The first Worker polyglot attempt stopped at 196.2 seconds with reward 0. Its shell supervisor had recorded that descendants were gone, but the adapter had omitted the cleanup receipts Worker requires before context recovery. After the repair, both scripted CPU controls crossed that boundary and the pair ran once on the repaired adapter. An earlier Git control also exposed a shell resource-limit warning in a captured commit ID. The receipts retain both interruptions, the successful controls, artifact hashes and phase timings. [Worker results and audit](../../results/harbor-worker-smoke-079.json)

## Follow a Harbor Worker in Observatory

From the Lab checkout, point Observatory at the experiment directory containing Harbor’s `trials/`. You can repeat the option to include earlier experiments.

```sh
python3 -S scripts/observe.py --harbor "$HARBOR_SMOKE_ROOT"
```

Open the loopback address it prints. **Follow newest** selects the latest scored Worker trial. Expand a timeline row to inspect a prompt, model response, tool arguments, output or checkpoint. **Diff & verification** shows the structured handoff and Harbor’s separate upstream reward. Agent and verifier times come from Harbor’s phase records. A failed or interrupted attempt stays visible even when it earned a numeric reward. Scripted controls and Terminus runs remain in Harbor’s trial directories. Terminus writes its own trace at `agent/trajectory.json`.

## Reproduce the two-task follow-up

The second panel uses `log-summary-date-ranges`, which submits a CSV, and `cancel-async-tasks`, which submits an importable Python module. Use a fresh experiment directory, the same upstream revision and the same controller environment as above. Select these tasks during sparse checkout and preparation.

```sh
git -C "$HARBOR_SMOKE_ROOT/upstream" sparse-checkout set tasks/log-summary-date-ranges tasks/cancel-async-tasks
python "$example/prepare.py" "$HARBOR_SMOKE_ROOT" log-summary-date-ranges cancel-async-tasks
```

Run `trial.py TASK AGENT NAME` in the clean controller environment for each task and each of `oracle`, `nop` and `worker-control`. Expect rewards of 1, 0 and 0, respectively. The Worker control also checks that its edited file reached the verifier. Preparation retains the upstream async verifier’s driver-copy step and uses the log oracle’s preinstalled command-line utilities.

For scoring, append `followup` to the GPU command’s final `pair.py` invocation. Allow 3,300 seconds for the memory wrapper and successively longer outer timeouts (3,500, 3,700 and 3,900 seconds for Ollama, speech and background). Each agent still gets 600 seconds. Worker goes first on the log task and Terminus goes first on cancellation. All four trials check their locally prepared image IDs before starting.

### Follow-up results

| Task | Worker agent time | Terminus-2 agent time | Upstream checks passed (Worker / Terminus) | Reward (Worker / Terminus) |
| --- | ---: | ---: | ---: | ---: |
| `log-summary-date-ranges` | 91.7 s | 107.6 s | 2 of 2 / 2 of 2 | 1 / 1 |
| `cancel-async-tasks` | 383.0 s | 600.0 s (timeout) | 5 of 6 / 5 of 6 | 0 / 0 |

Both agents submitted byte-identical CSVs with the required header, row order and 15 counts. The cancellation results look alike in the scoreboard. The submissions fail for different reasons when a queue is still present.

- **Worker** started only the two active jobs. Cancelling the gather had already cancelled its children. The exception handler called `cancel()` on them again while their cleanup was awaiting. Neither cleanup finished. Worker’s own real-SIGINT test wrote markers synchronously in its cleanup, so its 21 passing checks missed the failure.
- **Terminus-2** treated jobs waiting in the queue as also needing cleanup and started them during shutdown. Its last recorded turn requested completion. Harbor requested confirmation, performed proactive summarization and hit the agent ceiling. Harbor still transferred and graded the file. The whole trial took 646.4 seconds, including 30.6 seconds in verification.

A separate probe cancelled the caller while two of four jobs were running and kept the event loop alive to observe the result. The upstream reference started and cleaned up two jobs. Terminus started and cleaned up four. Both Worker jobs recorded a cancellation count of two when their cleanup was interrupted. All three implementations also supported factories returning already-resolved futures. The probe ran on sealed submissions and leaves the original rewards intact. [Probe source](probe_cancellation.py) · [Timings, hashes and observations](../../results/harbor-followup-smoke-001.json) · [Timing follow-up](https://github.com/othercriteria/harness-lab/issues/83)
