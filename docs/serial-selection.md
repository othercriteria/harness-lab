# How should one GPU spend a task budget?

Keep one implementation attempt as the default. On release selection, a reviewer recovered one accepted handoff by asking for a second candidate. Generating a second candidate on every job recovered the same handoff at 4.7 times the additional task time. On frame decoding, two attempts usually fit comfortably, but the reviewer gained no accepted deliveries. On the Git backport, the reviewer found a defect shared by every historically accepted candidate in the sample. A small executable check explained more than another implementation would have. [Issue #58](https://github.com/othercriteria/harness-lab/issues/58)

## Which finished submission would you take?

We surveyed the eight public task families in the frozen progress-confirmation campaign and the separate JavaScript confirmation. Of 140 attempts, 138 formed 69 non-overlapping adjacent pairs within the same task, recipe and campaign. Under the original judgments, 51 pairs contained two full passes, 17 had one, and one had none. Two odd tails had no partner. This bounds the opportunity in these campaigns. Arbitrarily pairing each failure with every success would make a small sample look much larger.

We chose three entire cohorts to cover short handoff errors, a medium task and a long task with source defects. The organizer knew the aggregate outcomes. One fresh hosted reviewer per family saw the public brief, starter, candidate changes, submitted handoff and original cited commands and outputs. For Git it saw patches computed from the two exported branch trees, the submitted tips and the public release policies. The packet omitted Git internals, ignore files and graph verdicts. Each reviewer inspected the artifacts as text. Cases and the order within each pair were shuffled. The reviewer recorded whether to accept A or request another attempt **before opening B**. It then chose A, B or neither. Historical review, private tests and scores stayed outside the packets. Each reader saw several examples of its own task. [Case-level decisions, original verdicts and receipt digests](../results/serial-selection-001.json)

| Task | Pairs | Keep A | Review A, stop if rejected | Retry on rejection | Always generate both | Best available in hindsight |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Release selection | 5 | 3 | 3 | 4 | 4 | 5 |
| Frame decoding | 10 | 8 | 7 | 8 | 8 | 10 |
| Git backport | 5 | 2 | 0 | 0 | 0 | 4 |

Each entry counts a delivered result that earned historical full acceptance. Rejecting both makes no delivery. The five Git pairs include the double failure. Taking the earlier seed instead of shuffled A yields 2, 8 and 2 full passes respectively. For **source alone**, keeping A delivers 5, 10 and 2 accepted implementations. Paired review delivers 5, 9 and 0. Every original canonical check passed across the 40 attempts. Canonical checks alone would give the selector no way to distinguish them.

The release reviewer caught a mutation check that examined the untouched backing array after passing separate permutation arrays to the function. Both implementations were correct. The reviewer missed a different overclaim about how many files had been counted. On frames, both readers of one submission saw that its saved “split-header” regression actually split a payload. Historical review accepted the broader handoff because an independent scratch check exercised every split point. The blind reviewer treated the claim about the saved test as material and rejected the pair. That is a difference in what the two reviews promised the maintainer. [Release judgments](release-channel.md) · [Blind decisions](../results/serial-selection-001.json)

## When does the time fit?

| Task and ceiling | Keep A, task seconds | Retry on rejection, task + review seconds | Always generate both, task + review seconds | Full passes fitting the cold ceiling, first / gated / paired |
| --- | ---: | ---: | ---: | ---: |
| Release, 60 s | 125 | 150 + 60 | 244 + 92 | 3 / 3 / 0 |
| Frame, 180 s | 598 | 695 + 77 | 1,165 + 125 | 8 / 8 / 8 |
| Git, 720 s | 1,954 | 4,135 + 106 | 4,135 + 106 | 2 / 0 / 0 |

Seconds are sums across jobs. Fit is tested **per job**. Task time includes preparing the workspace, model and tool activity, and the original automatic verifier. Review time is wall time between the hosted reader's start and sealed choices, including tool latency. Human attention and local-model review speed remain unmeasured. Taking A automatically charges zero selection time. Gated retry bought 1, 2 and 5 second attempts respectively. It includes review of A even on jobs that stop there.

With a ready model, always generating both and reviewing yields 1, 8 and 0 full deliveries inside the ceiling. The cold column charges the recorded load and dedicated prefix warmup once per job, about 18, 18 and 20 seconds respectively. All reconstructions assume serial work and reuse of the ready model. Measured batch subprocess time left another 8.71, 16.96 and 9.65 seconds per **whole campaign** outside load, warmup and timed trials. The per-job allocation of startup, inter-trial gaps and teardown is unknown. Additional dispatch, service restoration or downstream acceptance work would consume more time. Measuring end-to-end dispatch would require a prospective run.

We also tested unequal slices and a third attempt. Take disjoint seed-ordered **triples**, so every policy below starts with exactly the same cases. For each slice, ask whether its historical trace finished and received full acceptance before the slice expired. A timed-out trace consumes its whole slice. Unused time from an early finish rolls forward in the unequal schedules. A fresh job gets the original task ceiling, pays load and warmup once at cold entry, and gets an ideal selector with zero review cost.

| Allocation | Release, 3 jobs | Frame, 6 jobs | Git, 3 jobs |
| --- | ---: | ---: | ---: |
| One full attempt | 1 / 1 | 5 / 5 | 2 / 2 |
| Two fixed halves | 2 / 0 | 6 / 6 | 2 / 2 |
| 40%, then 60% plus unused time | 3 / 2 | 6 / 6 | 1 / 1 |
| 65%, then 35% plus unused time | 2 / 1 | 6 / 6 | 2 / 2 |
| 25%, 35%, 40% with unused time | 2 / 0 | 5 / 4 | 1 / 1 |

Cells give ready / cold jobs containing at least one historically accepted trace that fits. One, two and one trailing attempts respectively were unused in this table. As a sensitivity check, we replayed all six position orders within the same triples. Cold release selection ranged from 1 to 3 jobs for the single attempt and from 0 to 2 for the 40/60 split. Three attempts delivered zero in every cold release ordering. In the displayed seed order, allowing carryover made no difference for either equal halves or 40/60 on any family. The unequal slice lengths and seed order explain the apparent release advantage here. A smaller advertised budget can change reasoning, tool use and when the model finishes. These are timing opportunities on fixed traces. They cannot estimate how often a model actually succeeds under a new deadline. For frames there was time for a second answer and often a good one to choose, yet the reviewer could not reliably identify it.

## What the Git reviewer found

The legacy release requires its own validation error to be an exact built-in `ValueError`. Its service must also propagate a third-party writer’s unrelated exception unchanged. Six historically accepted submissions distinguish those two origins by reading an attribute on the exception. A writer can raise its own `ValueError` subclass that supplies diagnostic values for missing attributes. On those six submissions the service converted that unrelated exception into the release’s `INVALID` return status.

After the blind decisions were sealed, we ran the same two one-method writers against both branches of all ten submissions in the Lab's isolated CPU evaluator. One writer raised an ordinary `ValueError`. The other raised a subclass whose fallback returns the string `"unspecified"` for a missing diagnostic attribute. The driver checked that `write` ran exactly once and that the caller received the **same exception object**. Both unmodified starter services passed these propagation controls. All ten stable branches passed. Six legacy branches returned status 2 for the subclass. The other four passed this new witness and had already failed independent subclass-dispatch or same-arguments checks. Together those observations substantiate rejecting every pair on source grounds. They preserve the original six historical passes as a record of what the old review established.

The 22 isolated invocations including the two controls took about 14 seconds in total, roughly 0.6 seconds per branch invocation. This is the execution cost of an already written witness. It excludes discovering, writing and reviewing that witness. We also replayed it on the separate five submissions cited by the public ladder. Four of those legacy branches returned status 2. The fifth passed this particular check. [Witness source and observations](../results/serial-selection-001.json) · [Verifier v6 replay and sealed reference](../examples/checking-backport-verifier/README.md)

## What to try next

Reserve time according to what failed. For release selection, all ten implementations passed the original and held-out checks. Preserving the implementation and asking for a corrected verification claim is a plausible cheaper use of the remaining seconds. For Git, a focused check followed by a repair on the existing branch can retain several minutes of already correct work. A fresh seed becomes more attractive when there is evidence of an implementation dead end and the remaining time covers setup, work and selection. We have measured the defects and the check cost. The success and time of those repairs remain open.

An equal-budget GPU trial of independent restarts is premature here. Revisit it on a family with repeated, distinguishable implementation failures and a first-pass check cheap enough to leave room for another attempt. Compare one uninterrupted implementation with check-triggered repair or restart on fresh seeds. Fix the end-to-end deadline and entry state before dispatch, carry forward unused time, charge all dispatch, warmup, checks, review and cleanup, and score source, handoff, no-delivery and time separately. A third attempt should have to earn its time under the same rule.

Recompute the policy tables with Python 3.13 from the repository root.

```sh
python3 scripts/analyze_serial_selection.py
```
