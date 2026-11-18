# When would keeping a Worker model loaded pay off?

Keep releasing the GPU after each Worker job. Revisit a batch mode when a
planned series has enough same-server handoffs to pay for building and
operating it. Only six archived jobs were explicitly classified as useful work.
Each ran alone in its session. Repeated loading did cost measurable time in
planned experiments, especially Qwen screens.

## What the workstation spent

From November 16 to 18, 2026, Delegate admitted 157 jobs across 26 GPU
sessions. The 151 jobs with complete phase timings took 7.01 hours of
dispatch time. Six jobs had incomplete timings and break any inferred batch.
Each entry below sums elapsed seconds over the indicated jobs.

| Dispatch component | All 151 jobs | Qwen checkpoint session, 7 jobs | Coder-Next #23, 4 jobs | Qwen issue advice, 1 job |
| --- | ---: | ---: | ---: | ---: |
| Server launch through healthy owned endpoint | 2,266 | 107 | 119 | 18 |
| Separate discarded prompt warmup | 0 | 0 | 0 | 0 |
| Timed model requests | 20,490 | 749 | 289 | 339 |
| Remaining agent time | 1,172 | 28 | 13 | 20 |
| Verification | 94 | 4 | 2 | 1 |
| After server shutdown through job closure, including restoration | 503 | 13 | 6 | 6 |
| Other dispatch, including setup and trial overhead | 718 | 31 | 21 | 6 |
| **Total dispatch** | **25,242** | **932** | **450** | **389** |

Columns round independently. Model request time is observed client wait.
Backend initialization warmup falls inside load-to-ready, and first-prompt
processing falls inside the first request. The recorded intervals do not
separate every wrapper operation. On 69 jobs with restoration timestamps,
the median interval from the first Ollama restoration idle check to the
last model reload response was 4.42 seconds. That interval is part of the
post-shutdown time. Human review is outside dispatch.
[Per-job examples, phase totals and timings by model](../results/worker-residency-001.json)

## Which loads could a batch skip?

Consider two consecutive Worker jobs with verified cleanup, complete timings,
the same session, identical saved server profile and launch arguments (apart
from the ephemeral port), and no intervening recorded experiment start.
Count only the second model load. Package inputs, agent policy and seed can
vary across jobs. A time gap is a proxy for an opportunity. The receipts do
not establish that the next request was ready in advance.

| Maximum gap | Eligible handoffs | Later load time |
| --- | ---: | ---: |
| 2 seconds | 35 | 8.1 minutes |
| 5 seconds | 82 | 18.9 minutes |
| 10 seconds | 84 | 19.3 minutes |
| 30 seconds | 85 | 19.6 minutes |
| 60 seconds | 86 | 19.9 minutes |

At 10 seconds, the 84 handoffs form 27 batches in 10 sessions. Eliminating
every later load would save 6.5% of dispatch time in those batches, or 4.6%
across all measured Worker jobs. Qwen 32K accounts for 15.7 of the 19.3
minutes. The Coder-Next #23 batch contributes 35.1 seconds. Its 84.0-second
initial load would still be necessary. The seven-job Qwen checkpoint session
includes six closely spaced jobs with 76.0 seconds in repeat loads. The Qwen
advice job incurred a 17.9-second load with zero opportunity to reuse it.

The same period included 56 recorded non-Worker experiments with 8.28 hours
inside the server owner. Against that time plus measured Worker dispatch, the
19.3 minutes amount to about 2.1%. This is a scale comparison across two
different clocks. Benchmark campaigns can already run several seeds per load.
A Worker change would save time only on eligible Worker jobs.

## Demand and the decision

- **Interactive demand.** Seven of the ten most recent Worker sessions held
  a single job. Across all 26 sessions, all six jobs explicitly classified
  as useful work were singletons. Of the 157 jobs, 136 lacked a classification.
  Generalizing those six to future use would be premature.
- **Other GPU users.** The receipts show a resident Ollama model at entry and
  verified restoration on 74 jobs. At least one endpoint job displaced such
  a model on 31 of the 84 candidate handoffs. Restricting reuse to pairs with
  no displacement on either side leaves 53 handoffs and 12.9 minutes of
  later loads. A loaded model establishes occupancy. Demand from its clients
  during the gap is unknown. Busy submissions can fail before a job record
  is created. Session-level voice and background gates already span jobs.
- **Cost of waiting.** The 84 successful matches alone span 195 seconds of
  inter-job gaps. A speculative idle timer would also occupy the GPU on
  misses. Extending the gap threshold from 10 to 60 seconds finds just two
  additional matches. A queue of explicitly submitted jobs would make future
  demand observable and could release immediately after the final job.
- **Break-even.** A Qwen 32K load took a median 15.81 seconds. Even if all
  of that were recoverable, one hour of implementation would take about 228
  eligible Qwen handoffs to repay in workstation time. If a per-job reset
  and ownership checks cost three seconds, the figure rises to about 281.
  Three seconds is an illustration. Engineering and workstation time can
  have different values. A scheduled 20-job Qwen screen, for example, offers
  roughly five minutes of gross load savings across its 19 handoffs.

Reopen the implementation question when a concrete schedule of Worker batches
makes that arithmetic attractive, or when a caller needs substantially lower
handoff latency. Start with two predeclared jobs, fresh task state and a
measured cache reset. Compare their full dispatch with two jobs that each launch a fresh
server under comparable filesystem-cache conditions. Preserve per-job budgets, receipts and checks, a single bounded GPU
lease, explicit busy behavior, active-request checks, crash recovery and
verified restoration of the session's entry state. The comparison must
record any change to prompt-cache reuse separately. This archive measures
the time available to recover. It contains no resident-mode trial.

To reproduce the tables on the evidence workstation, run
`python -S scripts/analyze_worker_residency.py` from the repository root.
The default cutoff freezes the archive at November 18, 2026, 19:20 UTC.
[Source and accounting rules](../scripts/analyze_worker_residency.py)
