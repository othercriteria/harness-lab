# Four coding harnesses on the same local model

Worker, Aider and OpenCode took similar time on a small evidence reader. Aider
was much faster on an issue exporter, where almost every implementation still
needed repair. Worker was the only harness to deliver two fully accepted
Tabreport changes in the additional two-seed comparison. Task choice changed
both the timing and the reason a maintainer might reject an artifact.

## How the comparisons work

All four harnesses talk to the same local model on one RTX 4090. The Lab gives
each a disposable workspace, then runs the submitted code in a separate
evaluator. The **warm time** starts with the model ready and ends after the
attempt and any in-budget verification. Loading the weights, priming the first
public prompt and subsequently reviewing the source and handoff are separate
costs.

A **machine pass** requires green canonical and external checks, clean completion
and a finish within the ceiling. A **full result** also requires that the source
satisfy the brief, the edits stay within scope, and the terminal account be
supported by the trace. Aider can finish by applying a patch and running its
configured test command. Mini can submit with a shell marker. Worker usually
makes more claims in a structured handoff, which gives the reviewer more to
check.

## Eight-seed comparison on two repository assignments

Each harness took both assignments at every seed from 19550 through 19557.
All 64 attempts used Qwen3.8-27B with the RANA tensor precision layout, a 32k
context, a 2k reasoning cap and a 240-second ceiling. Dispatch order varied
across seeds. Aider received the source filenames up front, used automatic
public tests and had an 8,192-token chat-history allowance. Worker received
its repository preload. Different prompts, tools and file exposure are part
of what these workflow timings measure.

| Harness | Issue selection, machine / full (of 8) | Median seconds | Evidence reader, machine / full (of 8) | Median seconds |
|---|---:|---:|---:|---:|
| Worker | 8 / 0 | 104.6 | 8 / 7 | 44.5 |
| Aider | 8 / 1 | 53.2 | 8 / 8 | 47.7 |
| OpenCode | 5 / 0 | 111.4 | 8 / 7 | 48.0 |
| mini-SWE-agent | 8 / 0 | 152.6 | 7 / 7 | 86.8 |

Medians include every assigned attempt. On **issue selection**, all 32 artifacts
passed the frozen code checks. Aider finished faster than Worker on all eight
matched seeds, by a median of 49.8 seconds. Seven of its eight edits still
rejected a valid spelling of issue 7 with 4,500 leading zeroes. Seed 19555 was
the exception. Aider validated
the decimal digits, stripped leading zeroes as text and sent `7` to the lookup.
Other solutions commonly validated the digits and then called `int` on the
original string. Some wrote extensive passing edge tests around much shorter
numbers. A separate isolated replay fed all 32 exporters the same padded input.
Only the seed 19555 Aider artifact produced the expected packet and made one
lookup for issue 7.

Three OpenCode attempts ended at the Lab’s Git metadata guard. Their artifacts
still passed both frozen code checks. An isolated control reproduced the
index rewrite with `git diff --stat` even with optional locks disabled. Setting
`diff.autoRefreshIndex=false` produced the same statistics and left the index
unchanged. The published scores retain the original outcomes. [Adapter follow-up and control](https://github.com/othercriteria/harness-lab/issues/73)

On the **evidence reader**, Worker, Aider and OpenCode were close on typical
time and differed in how they spent it. Aider needed just one model request on seven of eight reader attempts. Worker finished faster than Aider on five of their seven jointly
accepted seeds, but one Worker run spent 153.7 seconds with repeated checks.
Mini made a median of 12 requests. One mini attempt generated a 25.6 MB scratch
file to test hashing and exceeded the adapter’s snapshot limit before submission
or timed grading. Its last retained implementation later passed both code gates
in an isolated replay. Outer review also caught two errors that code checks could
not see. A Worker report described CLI behavior from two working directories
after using one to call the library directly. An OpenCode report grouped the
empty manifest with cases returning exit 1, although its own probe returned 0.

## Two additional seeds on each of two ladder tasks

Frame Decoder repairs a binary parser that receives fragments of headers and
payloads. Tabreport adds a comparison API, two serializers and a CLI to an
existing Python package. Both briefs also request regression tests. These tasks
were already on the Lab’s ladder. The 16 additional attempts use seeds 19550
and 19551 and ceilings of 180 and 450 seconds, respectively.

| Harness | Frame seconds, seeds 19550 / 19551 | Machine / full (of 2) | Tabreport seconds, same seeds | Machine / full (of 2) |
|---|---:|---:|---:|---:|
| Worker | 48 / 50 | 2 / 2 | 192 / 141 | 2 / 2 |
| Aider | 46 / 46 | 2 / 2 | 35 / 60 | 0 / 0 |
| OpenCode | 57 / 66 | 2 / 2 | 251 / 274 | 0 / 0 |
| mini-SWE-agent | 86 / 77 | 2 / 2 | 220 / 228 | 1 / 0 |

On Frame Decoder, all four harnesses produced the repair and added tests at
both seeds. Each of the eight added test suites passed on the repair and detected
at least one failure on the untouched starter. Aider delivered each repair in
one model response.

On Tabreport, Aider’s first response printed requests for `Read` and `Bash`. Its client
exited successfully, with zero tool calls and zero edits. Its second submission
changed the implementation and passed all 21 supplied tests, but omitted the
requested regressions and mishandled stdout write failures.

Worker delivered both Tabreport changes with supported handoffs. OpenCode hit
the Git metadata guard on both seeds. The second artifact also failed the
canonical stdout encoding-error test. Mini’s first implementation passed both
code gates and its 21 new regressions. Its handoff said the CLI rejects
`--format` and `--output`, although its implementation and its own tests
accepted them. On the second seed mini had already run 48 tests successfully
when its next prompt reached 34,478 tokens in a 32,768-token context. Its
retained implementation passed both code gates on an untimed replay.

Source review also produced a false alarm. A reviewer suspected that writing
CSV with LF record endings could split a label containing a bare carriage
return. In the pinned runtime, the frozen reference and all seven implemented
Tabreport artifacts, including mini’s retained workspace, quoted the field
correctly. The unchanged starter from Aider’s first seed produced no CSV.
This post-run control is recorded separately from the frozen grades. The CPU walkthrough reproduces the CSV observation and the padded-number failure on two identified artifacts. [Replay both source-review objections](../examples/replaying-review-objections/README.md)

**What to use.** Worker remains the Lab’s default when the maintainer needs
inspectable verification. Aider is worth trying for bounded edits with known
source files and fast independent tests. On this evidence two seeds suffice
to expose workflow differences on a new task, but give little precision on
reliability. The 80-row record includes clocks for every attempt, artifact
hashes, separate code and handoff grades, supplemental checks, paired times
and the two untimed recoveries. The older results below keep their original
grading and denominators. [Per-attempt evidence and summary tables](../results/harness-comparison-repeats-055.json)

## When the repository assignments were fresh

The first assignment added repeatable `--issue NUMBER` selection to the Lab’s
GitHub issue exporter. The second implemented a two-file library and CLI to
check a downloaded evidence packet against its SHA-256 inventory. Each brief
and starter received a blind review and an independent solution before the
comparison. The same Qwen weights, 32k context, 2k thinking cap and 240-second
ceiling applied to all harnesses in these blocks.

| Assignment | Seed | Worker | Aider | OpenCode | Upstream mini-SWE-agent |
|---|---:|---:|---:|---:|---:|
| Issue selection | 19100 | 166.8 s | 106.5 s | 96.0 s | No trial |
| Evidence reader | 19116 | 50.1 s | 48.1 s | 50.7 s | 97.0 s |

**Issue selection.** All three submissions finished cleanly with supported
handoffs, passed six canonical tests and five external checks, and still needed
a repair. Each called Python’s integer conversion on an input consisting of
4,500 zeroes followed by `7`. The brief admits that spelling of issue 7.
Python rejected it before the lookup. Worker ran nine extra tests and missed
the same case. The Maintainer integrated OpenCode’s submission, normalized the
digits as text, added regression coverage and checked a real two-issue export.
One earlier OpenCode launcher error occurred before inference and is outside
the three scored attempts. [Original receipts and integration record](https://github.com/othercriteria/harness-lab/blob/70caa016eedfd93cdcbe199702feb5d69d735800/results/standard-workers-issue-selection-001.json)

**Evidence reader.** All four submissions passed four canonical tests, three
external checks, and independent source and handoff review. Aider submitted
both edits in one model response. Worker took four requests, OpenCode eight and
mini thirteen. The Maintainer landed Worker’s two source files unchanged and
added a regression that corrupts one file and removes another. Mini used
upstream 2.4.6’s default agent, prompt, shell tool and action parser with the
Lab’s local inference transport and isolated shell. Aider received the editable
filenames and Worker its usual repository preload. These are comparisons of the
workflows a user actually dispatches. [Original receipts and trace excerpts](https://github.com/othercriteria/harness-lab/blob/d5e335381e4b968bdb7a6b9007cf2828f0d0782a/results/standard-workers-evidence-check-001.json)

## Earlier development screen

The Lab ran two seeds on each of two known development tasks with three coding harnesses. All used the same local Qwen backend. One task repaired a Markdown library and the other changed a Python tabular reporting tool. Task time includes time spent by the harness during the attempt. The ceilings were 120 and 450 seconds.

| Coding harness | Markdown seconds, seeds 18100 / 18101 | Tabreport seconds, seeds 18100 / 18101 | Code checks | Strict full results |
|---|---:|---:|---:|---:|
| Local Harness Lab Worker | 23.6 / 32.4 | 197.6 / 145.3 | 4/4 | 4/4 |
| OpenCode 1.18.25 | 28.9 / 33.4 | 139.1 / 145.1 | 4/4 | 3/4 |
| Aider 0.86.1, adapted non-Git workflow | 39.8 / 40.2 | 208.9 / 143.5 | 4/4 | 4/4 |

Five earlier attempts encountered integration problems and were excluded from the 12 valid trials. The second OpenCode Tabreport run passed code checks but misstated how many tests it added. The review therefore rejected its handoff. This small sample supports comparison on these tasks and seeds. The Markdown task is retired from this distribution. [Recorded comparison and qualifications](../results/standard-workers-conclusions-001.json)

## Follow-up checks on Git inspection and issue selection

The revised native comparison adapter sets `diff.autoRefreshIndex=false` during fixture Git initialization. Two successive brokered diff inspections preserved every protected Git file. A staging attempt triggered the existing metadata guard, and the original index remained intact. A fresh OpenCode run on issue-selection seed 19556 ran the public suite, `git status --short` and `git diff --stat` together, then finished cleanly in 97.5 seconds under the original evaluator. Its exporter still failed the padded-input check. This single run confirms the repaired inspection path. [Adapter revision](../configs/comparison-patches/native-git-diff.patch)

Issue-selection evaluator v2 now checks that issue 7 spelled with 4,500 leading zeroes and a second ordinary `7` produces a one-issue packet and exactly one canonical lookup. The brief, starter and supplied tests match v1 byte for byte. In an isolated CPU replay, 1 of the 32 archived artifacts passed all seven canonical tests, and all 32 passed the five external checks. The historical blind solution and the integrated exporter passed both gates. The starter failed both. Future workstation comparisons can use the combined `comp74-issue-selection-v2` freeze. To reproduce the revisions on a copy of the comparison source, apply the adapter patch and use the published issue-selection fixture and external grader. [Revised fixture](../tasks/issue-selection/task.json) · [External grader](../scripts/grade_issue_selection.py) · [Replay results and freeze identities](../results/native-git-and-exporter-replays-001.json)

The same CPU study compared the first green workspace with the final submission for all 20 Worker attempts. [What changed after the public tests passed](worker-handoff-decisions.md#what-happened-after-the-first-green-suite)

## Upstream terminal tasks

The Terminus-2 smoke uses the same local Qwen profile on two Terminal-Bench 2.1 tasks. It establishes the Harbor path for a paired Worker run. The four-harness results above use different assignments and acceptance criteria. [Smoke recipe and results](../examples/harbor-terminus/README.md)
