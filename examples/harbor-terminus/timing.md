# Which Harbor clock ran out?

Use the task-declared agent and verifier limits when comparing with another Terminal-Bench run. For a workstation latency question, report the whole Harbor trial beside the agent phase and state whether weights and prompt were warm. For a dispatch-to-verified-result promise, also time the caller from dispatch through the availability of the verified result. Each clock answers a different operational question.

New paired runs also write a client-side receipt around the controller subprocess. It includes interpreter startup, image checks, prompt warm-up, the trial and client exit. Backend load stays separate. A CPU no-op run measured 32.124 seconds from dispatch to client exit and 30.909 seconds around Harbor. The four scored replays predate the client timer and report the independent Harbor timer only. Across the four scored trials and four clock-boundary controls, the independent measurement around Harbor agreed with its whole-trial timestamps to within 0.007 seconds. A final scripted Worker run exercised context recovery, artifact transfer and the 900-second configuration on the updated controller.

The original smoke gave both agents 600 seconds. On `cancel-async-tasks`, Terminus requested completion, received a confirmation prompt and entered summarization. Harbor recorded an agent timeout at 600.004 seconds, then graded the transferred file in a 30.615-second verifier phase. The whole trial took 646.412 seconds. The reward of zero was valid and five of six upstream checks passed. Worker submitted under the same cap and also earned zero. [Original results](../../results/harbor-followup-smoke-001.json)

## Short-task replay

| Task | Agent | Earlier agent time, 600 s cap | Replay agent time, 900 s cap | Replay verifier phase | Replay whole trial |
| --- | --- | ---: | ---: | ---: | ---: |
| `fix-git` | Worker | 40.3 s | 172.5 s | 16.1 s | 206.3 s |
| `fix-git` | Terminus-2 | 157.7 s | 101.6 s | 17.5 s | 134.9 s |
| `log-summary-date-ranges` | Worker | 91.7 s | 59.7 s | 16.8 s | 95.7 s |
| `log-summary-date-ranges` | Terminus-2 | 107.6 s | 100.2 s | 17.0 s | 133.1 s |

All eight artifacts across the two timing conditions earned an upstream reward of one. Both replayed Git submissions retained both original tips on `master`. Both CSVs matched the earlier verified bytes. On Git, Worker took 16 model calls and 24 tool calls in the replay, up from eight and ten. The two initial model requests differed only in the stated allowance. The first commands already differed, and the replay inspected the commit graph and its ancestry more extensively. With one observation per agent, task and condition, the reversal in Git finishing order gives little basis for choosing an agent or inferring a ceiling effect. [Trial receipts and controls](../../results/harbor-timing-083.json)

## Where the pinned runner charges time

| Clock | Start and finish | Conditions in this panel |
| --- | --- | --- |
| Backend readiness and prompt warm-up | The controller starts the backend once, then sends one discarded generation before each trial | Outside Harbor trial time. The first scored request can reuse a different number of prefix tokens for each agent. |
| Whole Harbor trial | Harbor initializes the result on entry to `Trial.run()` and timestamps the finish after environment stop | Includes setup, log synchronization, artifact collection, grading and cleanup. The independent monotonic timer around `await trial.run()` also includes final result serialization and scrubbing. Image preparation, trial construction and human review are outside it. |
| Environment and agent setup | Harbor records separate phase timestamps for environment setup and agent setup | Task environment start/build allowance 600 s and agent setup allowance 360 s. Health checks and pre-agent hooks can add elapsed time between named phases. |
| Agent execution | Harbor timestamps the phase after the agent-start hook and applies `asyncio.wait_for` to the agent's run method | 900 s from each task declaration in this panel. The historical smoke explicitly selected 600 s. Phase setup and cancellation unwinding can make recorded elapsed time exceed the allowance. |
| Verifier phase | Begins before entering the separate verifier environment and ends after leaving it | 900 s applies to `verify()`. Starting that environment, uploading artifacts and tearing it down also appear in the recorded phase. An agent timeout can earn a valid reward if the verifier finishes. A verifier timeout leaves the reward unavailable. |
| Native Lab task | Starts at the caller's supplied monotonic dispatch timestamp (or native trial entry when invoked directly). The agent gets the smaller of its cap and the remaining task time after the verification reserve | Setup consumes some of the task clock. In-budget canonical and configured behavioral checks use the remaining time. Delegate dispatch, backend readiness and later maintainer review have separate receipts. |

In Harbor 0.27.0 a single-step agent with no task or override timeout can be unbounded. The schema default for verification is 600 seconds. For agent execution and verification, Harbor takes the trial override when set, otherwise the task value, applies any maximum, then multiplies by the phase multiplier or the global multiplier (default 1). The setup clocks resolve separately. The comparison examples support finite positive Worker ceilings. [Timeout resolution and phase boundaries](https://github.com/harbor-framework/harbor/blob/96c86af3bc6d7e92f21fc771d21273be4714c8e9/src/harbor/trial/trial.py) · [Single-step transfer and grading order](https://github.com/harbor-framework/harbor/blob/96c86af3bc6d7e92f21fc771d21273be4714c8e9/src/harbor/trial/single_step.py) · [Error policy](https://github.com/harbor-framework/harbor/blob/96c86af3bc6d7e92f21fc771d21273be4714c8e9/src/harbor/models/trial/error_policy.py) · [Native Lab deadline](../../scripts/run_trial.py)

Worker receives the same allowance in its local prompt configuration, request timeout and inner loop. Its inner timer begins after the controller launches the child and configures the loop. Harbor remains the outer deadline. This recipe also limits a command to 10 seconds, an attempt to 64 steps and 128 tool calls, and has a deadline-sensitive reasoning allowance. Terminus sends keystrokes to a persistent terminal. Its JSON command duration is capped at 60 seconds and represents time before observing the pane. A command can continue in the terminal. Completion confirmation, further inference, provider retries and proactive summarization all spend the same agent allowance. The comparison sets no separate Terminus model-request timeout. [Worker loop](worker_loop.py) · [Terminus command and completion loop](https://github.com/harbor-framework/harbor/blob/96c86af3bc6d7e92f21fc771d21273be4714c8e9/src/harbor/agents/terminus_2/terminus_2.py)

## Reproduce the clock boundaries on CPU

Use the pinned Harbor environment and the prepared `log-summary-date-ranges` images from the [follow-up smoke](README.md#reproduce-the-two-task-follow-up). Run from the Lab root with Docker available. Choose a fresh output path.

```sh
env -i PATH="$PATH" HOME="$HARBOR_SMOKE_ROOT/controller-home" HARBOR_TELEMETRY=0 LITELLM_LOCAL_MODEL_COST_MAP=True \
  "$HARBOR_SMOKE_ROOT/.venv/bin/python" examples/harbor-terminus/timing_control.py \
  "$HARBOR_SMOKE_ROOT/prepared/log-summary-date-ranges" "$HARBOR_SMOKE_ROOT/timing-controls-001"
```

| CPU case | Agent phase | Verifier phase | Whole trial | Harbor result |
| --- | ---: | ---: | ---: | --- |
| Both finish | 1.103 s | 17.231 s | 33.551 s | Valid reward 1 |
| Agent exceeds 4 s | 4.001 s | 17.185 s | 36.387 s | Agent timeout, valid reward 1 |
| Verifier exceeds 4 s | 1.100 s | 19.185 s | 35.374 s | Verifier timeout, no reward |
| Both exceed 4 s | 4.002 s | 19.048 s | 38.216 s | First exception is the agent timeout, no reward |

The marker reached the separate verifier in all four cases. When both clocks expired, Harbor retained the first exception in `result.json` and recorded the subsequent verifier timeout in `trial.log`. Reading only the exception type would make the second and fourth rows look equivalent. Check `reward_valid` and the presence of a reward before aggregating.

In the ordinary control, a one-second agent delay produced a 1.10-second agent phase. After that hook, another 11.19 seconds elapsed before verification started. This interval contains log synchronization, artifact collection and agent-environment stop. A two-second verifier delay occupied a 17.23-second verifier phase including its environment and transfer. The caller measured 33.552 seconds around the whole trial. These receipts resolve the phase boundaries but do not allocate the inter-phase interval among its individual operations.

The scripted agent writes a marker to the declared artifact path and waits. A separate verifier reads it, waits and awards one point. This synthetic reward tests transfer and timing only. Each case saves the marker, the Harbor result and a monotonic clock receipt. Observatory lists scored Worker runs. CPU controls can be inspected directly in their output directories. In a scored Worker trace, an agent deadline, an unanswered request, a verifier exception and a numeric reward have separate evidence.

## Match conditions before comparing runs

- **Outcome and inputs.** Identify the benchmark revision, task selection, prepared task checksum, image identities, verifier assertions, reward validity, attempt count and retry policy. These examples grade transferred artifacts in a fresh offline container. Upstream tasks can use the original workspace and a different network or dependency setup. Reproduce the environment or declare the differences.
- **Compute and tools.** Keep hardware, inference binary, model bytes, context length, reasoning cap, sampling, effective tool limits and agent versions in the receipt. Here the task declares one CPU, 2 GiB of memory and zero task GPUs. Inference runs on the host RTX 4090. On the log-task Worker container, Docker reported a one-CPU limit, 2 GiB of RAM and a 4 GiB combined memory-and-swap limit. Its storage options were unset, so the task’s 10 GiB storage declaration alone cannot establish an enforced disk quota. The boundary receipt also records the observed image, mounts, privilege and network.
- **Latency.** Record task limits and overrides, setup, agent execution, verifier phase and whole-trial seconds. Record model load, prompt warming and first scored cache reuse separately. Preserve dispatch order, other host workloads and any guard stop. Use a caller-side clock when making an end-to-end latency claim. Matching a ceiling alone cannot establish equivalent environments or throughput.

## Replay the short model panel

The two fastest tasks in the earlier paired smokes were `fix-git` and `log-summary-date-ranges` by combined agent time. Reuse the prepared task directories and image identities so the earlier 600-second runs remain useful comparators. Prepare a fresh experiment root with both tasks under `prepared/`, the local log-task `build/log-summary-date-ranges/images.json`, the pinned Harbor `.venv` and a clean `controller-home/`. The reference run checked the original Linux/amd64 platform manifests for Git and the recorded local image IDs for the log task.

Use the [restoring GPU command](README.md#run-one-warm-attempt-per-task) with `pair.py "$HARBOR_SMOKE_ROOT" "$label" timing` as its final invocation. Allow 4,300 seconds for the memory wrapper and successively longer outer timeouts (4,600, 4,900 and 5,200 seconds for Ollama, speech and background). Worker goes first on Git and Terminus goes first on logs. On newly built images, the individual `trial.py TASK AGENT NAME ORIGIN --task-timeout --prepared-images` entry point binds to the local preparation manifest for each task. Keep those repetitions under their own experiment identity.
