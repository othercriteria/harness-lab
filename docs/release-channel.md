# The 60-second JavaScript rung

Given an unordered export, select the highest currently published build for one
release channel. A later revision can withdraw or reinstate a build. The
original pilot used two public examples, eleven canonical cases and a separate
panel of four cases frozen before the first model run. Version 2 adds two
canonical cases and checks mutable inputs. The ceiling is model time on this
workstation. A blind reviewer estimated 3–7 minutes for
a JavaScript engineer and sealed a first solution in 27 seconds. We have no
human timing measurement. [Public brief](../tasks/release-channel/public/task.md)
· [Admission, seeds and scores](../results/release-channel-pilot-001.json)

## What ran

| Recipe and sample | Ceiling | Correct, clean and in time | Handoffs accepted | Task time |
| --- | ---: | ---: | ---: | --- |
| Qwen3.8-27B, development | 90 s | 2/2 | 2/2 | 19.6 and 21.1 s |
| Flint, same development seeds | 90 s | 2/2 | 2/2 | 25.1 and 16.1 s |
| Coder-Next, same development seeds | 90 s | 2/2 | 2/2 | 41.7 and 26.8 s |
| Qwen3.8-27B, shorter-ceiling development | 60 s | 2/2 | 2/2 | 24.5 and 34.8 s |
| Qwen3.8-27B, fresh confirmation seeds | 60 s | 10/10 | 7/10 | Median 22.3 s, range 19.4–36.0 s |

All 18 submissions also passed all four held-out cases in isolated replay.
The model-load costs for the 90-second batches were 15.8 s for Qwen, 56.8 s
for Flint and 48.8 s for Coder-Next. Those are single observed starts. The
ten confirmation trials each reused 4,253 of 4,257 initial prompt tokens after
a discarded public-prefix warmup. Their median first edit completed at about
10.3 s and their first public test started at about 15.8 s. An empty Node
process took a median 44 ms inside the sandbox over five launches. The first
edit and test figures are estimates from receipt timestamps.

The three qualified handoffs had correct implementations. One described four
filesystem entries as four files. A second tested all 720 permutations but
checked the backing array for mutation. Its assertion would miss reordering
of an argument array. A third reported five shuffles for a four-iteration
loop and had the same backing-array limitation. Source review, frozen-input
checks and actual command evidence are recorded separately.
[Per-trial findings](../results/release-channel-pilot-001.json)


Keep Qwen at 60 seconds for this rung. Two confirmation runs used more than
30 seconds. The two-seed challenger probes establish feasibility and leave
relative reliability open. All results here concern the same development task.

## What the Verifier can distinguish

We checked nine implementations against the same public contract. A local Worker
proposed mistakes from the public files. The Maintainer reviewed the rules,
removed duplicates and sealed executable examples and independent witnesses before
scoring. Each witness called the candidate on ordinary mutable records and checked
the return, record values and array member identities. Canonical and witness
expectations stayed outside the candidate process. [Frozen panel](../examples/checking-release-verifier/panel.json) · [Results and provenance](../results/release-channel-sensitivity-001.json)

| Behavior | Public tests | Canonical v1 | Canonical v2 |
| --- | --- | --- | --- |
| Reference solution | Pass | Pass | Pass |
| Replace a saved record on an equal revision | Pass | Pass | Pass |
| Treat any past publication as current (starter) | Fail | Fail | Fail |
| Keep the first record seen for each build | Pass | Fail | Fail |
| Keep the last record seen for each build | Fail | Fail | Fail |
| Sort the caller’s array in place | Pass | Fail | Fail |
| Cache a derived flag on the caller’s records | Pass | Pass | Fail |
| Fold channel names to lowercase | Pass | Pass | Fail |
| Compare builds as decimal strings | Pass | Pass | Fail |

The equal-revision variant is valid because ties agree on state. Two of
Worker’s descriptions reduced to “ever published” and count as one mistake.
Version 1 caught in-place sorting because Node threw on a frozen array.
The non-strict cache assignment silently did nothing on a frozen record. On a
mutable record it left an extra property, even though the function returned the
right build.

Version 2 exercises both input forms in one isolated Node invocation and
checks the caller’s array and records after the mutable call. Two added cases
distinguish `9` from `10` under numeric ordering and `stable` from `Stable` under
exact channel matching. All 18 archived submissions passed the revised checks in
CPU replay. Their original timings, scores and handoff judgments still describe
the original campaign. The seven selected mistakes measure only these examples.

On the configured workstation, replay the panel in the development shell. Choose
a new output directory for each invocation.

```sh
python examples/checking-release-verifier/replay.py /tmp/release-panel-v2
```

For a v1 comparison, pass `--task` with the `tasks/release-channel` directory
from revision `6b774adc5dd52fceaf3b1544b700cb15c78dc517`. The replay writes
individual sandbox receipts and a matrix, and flags changes to either published
result. No model or GPU is required.

## Run the task

The standard operating procedure applies on the configured workstation,
including session-level GPU gating and restoration. The shipped
`qwen38-27b-ranalayout-32k-scoped-v1` server profile has the same contents
as the Qwen server profile recorded in the campaign. The JS task protocol
selects ordinary continuation. For a new seed and fresh output directory:

```sh
.venv/bin/python scripts/launch_pilot.py \
  --profile qwen38-27b-ranalayout-32k-scoped-v1 \
  --protocol release-channel-qwen-60-v1 --tasks release-channel \
  --weight-verification metadata --seeds 19230 \
  --output /bulk/dlk/local-harness/runs/js-release-qwen-60-example-001
```

This command records a fresh-start trial. To reproduce warm timing, add
`--prefix-warmup-request` pointing to the initial public request from a
development trial under the same protocol. The run verifies the rendered prefix.
The agent runs `node tests/public.cjs` in its workspace. The current verifier
invokes the submitted function on mutable and frozen inputs in a separate
read-only Node sandbox, compares typed results outside the sandbox and checks
the submitted file set.
[Operating procedure](operations.md)
