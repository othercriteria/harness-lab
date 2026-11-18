# Context and dispatch reconnaissance

The reconnaissance goal is complete: 32 real-model trials and two inert cache
sequences are reviewed, and session-entry GPU workloads are restored. This is candidate selection, not reliability
certification. Maintained ladder recipes remain unchanged.

The most useful next reliability candidates are **32K SQLite and Tabreport**.
Keep the **2K reasoning cap** uniform for Qwen3.8-27B. The screen gives no reason
to make 32K universal; 16K Frame is a separate promising efficiency candidate.

## Paired context results

Each arm has the same two task seeds. Entries show full accepted outcomes and
individual warmed task times in seconds, in seed order. Full acceptance includes
source and handoff review, independent correctness, completion and the deadline.

| Task ceiling | Qwen 24K | Qwen 32K | Qwen 16K supplement |
|---|---|---|---|
| Markdown 90 s | 2/2; 41.5, 57.0 | 2/2; 41.0, 57.8 | 1/2; 34.5, 75.9 |
| Frame 180 s | 2/2; 63.8, 90.4 | 2/2; 80.4, 97.4 | 2/2; 55.3, 59.9 |
| Event 300 s | 2/2; 236.4, 146.5 | 1/2; 300.1, 208.5 | — |
| Tabreport 450 s | 1/2; 296.2, 389.9 | 2/2; 273.0, 263.5 | — |
| SQLite 600 s | 2/2; 417.9, 486.2 | 2/2; 300.4, 213.3 | — |

SQLite's 24K runs repeatedly read and checkpointed before implementing, using
six/seven resets. Both 32K runs used one reset and implemented earlier. Tabreport
also used fewer resets at 32K. These gains occurred despite slower generation:
better use of the available context can outweigh lower tokens/second.

The counterexamples matter. Frame was slower at 32K. Both Event cases were
slower, and one expired during independent verification after canonical tests
passed; its handoff also cited the wrong observation. The 24K Tabreport failure
was an incorrect claim of five added tests instead of one, despite correct code.
The 16K Markdown failure claimed an end-to-end check that had not been performed.
All these failures remain in the recorded results.

This is a **configuration-bundle comparison**: 24K uses fit2304 and 32K uses
fit2048. Both placed 63/65 target layers on GPU; 16K/fit2304 placed 64/65. Task
trajectories also differ. Two seeds cannot establish reliability, generalization,
or an isolated causal effect of context size. No task contracts were relaxed.

## Cache and switching

The inert probes used real initial public prompts and one discarded output token
per request. Changing the request reasoning cap 2K→4K→2K preserved identical
rendered prompt tokens and nearly full prefix reuse on one resident backend:
about 0.19–0.23 s versus 2.95 s for the initially cold prefix. This establishes cache
compatibility, not the effect of reasoning cap on coding quality.

Changing allocated context currently requires a backend reload. Merely keeping
weights resident does not guarantee prefix reuse across tasks. The pinned hybrid
backend needs useful recurrent checkpoints or a saved RAM state. Markdown↔Frame
lost reuse despite shared system text, while returning from SQLite restored the
saved Markdown state in about 0.80 s. The backend's saved-state lookup heuristic
and checkpoint boundaries explain the difference.

A separate layout probe moved the exact task-dependent finish-soon sentence from
the system body to the user suffix. The Markdown/Frame common prefix increased
from 2,256 to 2,975 tokens, making a 2,971-token checkpoint reusable. Switch time
fell 2.84→1.04 s and return time 2.58→1.33 s. The SQLite transition did not improve.
Production prompts remain unchanged: one inert sequence is insufficient to
validate instruction-following or full-task behavior, and warmed single-task
campaigns do not receive this cross-task benefit.

## Other champions and GPU residency

The 32K codec probes preserved the expected distinction: codecA returned a
supported impossibility argument in 48.3 s; codecB completed correctly in 44.4 s,
including a separate exhaustive isolated probe. An accepted blocker does not
require making impossible implementation checks green.

Flint failed Git90 at 82.7 s without implementing, and Git720 at 550.7 s after
64 requests and four resets, again without source changes. Coder's CPU32 Git90
produced correct code and Git delivery but missed structured finalization at
84.0 s. Its Git720 control stopped at 64 requests in 234.3 s with partial work
stashed and no new target commits. Request-limit failures do not establish that
the full wall-time allowance was insufficient.

The user-requested Coder placement follow-up moves one expert block from CPU to
GPU (CPU32→31) and lowers fit reserve 2048→1536 MiB, keeping context, sampling,
backend, task and seed fixed. GPU model weights increased by 864 MiB; projected
free memory fell from about 2576 to 1714 MiB without a placement fallback.
The matched short treatment fully passed in 69.9 s. Observed decode throughput
rose 53.3→55.2 tokens/s, but requests fell 26→23 and trajectories differed, so the
14.1 s task-time gain is not a pure throughput estimate. The long treatment also
hit 64 requests, at 234.9 s: stable had a new commit without the required regression
test, while legacy remained unfinished. Decode rose 52.7→54.4 tokens/s, but the
task still failed. The two treatment runs passed resource and cleanup guards;
that is limited operational evidence, not a general stability guarantee.

A historical Coder run with a 128-request allowance reached finalization after
117 requests, but failed required regression-test delivery on an earlier task.
It is evidence that the request limit matters, not a demonstrated fix. These
single-seed Git screens do not replace the historical Qwen Git confirmations.

## Delegation and dogfooding

Start with serial specialist contexts on one resident model if exploring local
delegation. Independent subtasks still pay for repeated reads, context recovery,
handoffs, checks and integration. Heterogeneous batching needs savings large
enough to cover those costs plus weight switching and repair. Published cloud
or multi-GPU speedups do not establish a latency win on this workstation.

For dogfooding, the smallest useful slice is a durable CLI snapshot-to-artifact
job with submit/status/result/cancel. Reuse the canonical GPU lock with a busy
response, existing execution isolation, separate verification and trace capture.
Export a normalized allowed-path patch, check the original snapshot is still
current, and let the outer agent review and apply it. A thin local stdio MCP can
follow the first useful patch. These are design proposals, not implemented tools.

## Evidence and follow-up

The [candidate index](../configs/context-routing-candidates-v1.json) identifies
exact frozen recipes and reproduction requirements. The
[context summary](../results/context-routing-context-screen-001.json),
[resource analysis](../results/context-routing-resource-analysis-001.json),
[supplement](../results/context-routing-supplement-001.json),
[placement comparison](../results/context-routing-coder-placement-001.json),
[cache probe](../results/context-cache-probe-001.json), and
[layout probe](../results/context-cache-layout-probe-001.json) preserve detailed
bindings and qualifications. See the
[delegation proposal](../results/workstation-delegation-proposal-001.json) and
[dogfooding proposal](../results/dogfood-interface-proposal-001.json) for designs
and research sources.

The user requested a future 32K reliability goal, especially SQLite/Tabreport,
not necessarily the next goal. Use fresh predeclared seeds, refreshed 24K
controls and a chosen panel size then; this campaign does not add automatic
20-run sweeps. Preserve the failing controls and inspect tail behavior as well
as success counts. Smaller-context tuning, task-level prompt-layout validation,
request-budget tuning and Coder microbatch sizing are separate follow-ups.

The [completion audit](../results/context-routing-completion-audit-001.json)
rechecks frozen inputs, all per-trial review bindings, conformance, cleanup, cache
evidence and session 013 restoration. [Conclusions](../results/context-routing-conclusions-001.json)
provide the machine-readable index.

Future dogfooding candidate (2026-11-16): a bounded pass over unexplained numeric
constants, proposing names and documenting their resource assumptions. Keep it
separate from the current call-budget capacity fix; review behavior preservation
and isolation limits before adopting any cleanup.
