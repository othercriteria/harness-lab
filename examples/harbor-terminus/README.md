# Run Terminus-2 against the local Qwen endpoint

This is the two-task Terminal-Bench 2.1 smoke used for [#78](https://github.com/othercriteria/harness-lab/issues/78). Harbor runs Terminus-2 on the controller. The model sends keystrokes to a terminal in a disposable container. Harbor stops that container, copies the declared task artifact into a separate verifier container, and records its reward. The model sees the upstream task brief and terminal output.

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

## Observed on the reference workstation

| Task | Agent | Environment + agent setup | Verification phase | Whole Harbor trial | Upstream reward |
| --- | ---: | ---: | ---: | ---: | ---: |
| `polyglot-c-py` | 366.4 s | 4.2 s | 15.8 s | 397.8 s | 1 |
| `fix-git` | 157.7 s | 4.1 s | 16.1 s | 189.6 s | 1 |

Both agents signaled completion. On the polyglot task, Qwen repeatedly broke a working version while trying to silence compiler warnings, then recovered and exercised a wider numeric range. On the Git task, several terminal inputs went into a pager before Qwen regained the shell, recovered the detached commit and resolved a merge conflict. The upstream Git tests check two file contents. A separate read-only graph check confirmed that the submitted `master` contains the initial branch tip and the recovered commit.

The first scored requests reused 352 of 891 prompt tokens on polyglot and 253 of 794 on Git. Full-trial time includes artifact collection and environment teardown. These two trials establish an end-to-end baseline for the paired Worker smoke. Each task has one observation. [Machine-readable results and trace identifiers](../../results/harbor-terminus-smoke-078.json) · [Paired Worker issue](https://github.com/othercriteria/harness-lab/issues/79)
