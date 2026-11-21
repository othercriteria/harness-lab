# Does switching recipes pay for a short task?

Keep the already resident recipe for the short jobs represented here when it has demonstrated full acceptance on that family. On this workstation, a rule trained on past task times found one switch among five comparable starting states at observed setup prices. That switch cost an estimated 10.05 seconds. The evidence supports deferring automatic dispatch. A different workload mix, particularly a known batch, could change the decision. [Issue #21](https://github.com/othercriteria/harness-lab/issues/21)

## What was available at dispatch

The archive has two short families with matched seeds, reviewed submissions and model-load receipts. The comparison uses family, ceiling, prior development results and current resident recipe. Both 120-second codec contracts get the same route, with equal weight for each. The caller need not know which contract is feasible. The 90-second release-channel comparison is a separate decision. RANA is the codec fallback and Qwen3.8-27B with the RANA tensor layout is the release-channel fallback. The arms, including Coder-Next, are specific to each family's configuration. The study does not establish a universal fallback for the production Worker.

| Family | Decision inputs | Outcomes used for scoring |
| --- | --- | --- |
| Codec | One development attempt per variant and recipe, seeds 14900 and 14910. Four recipes screened. | Both variants, seeds 14930 and 14931, for RANA and Coder-Next. Eight reviewed trials. |
| Release channel | First development seed 19200, Qwen, Flint and Coder-Next. Cold prefix on each. | Second development seed 19201 on all three, with a reused prefix. Three reviewed trials. |

This is retrospective. The prior choice of codec finalists and aggregate results were known. The scoring code withholds evaluation times and verdicts from recipe selection. The second JavaScript seed is a within-pilot check. Neither family is an unseen task. [Codec confirmation](../results/frontier-codec-joint-decision-001.json) · [Release-channel pilot](../results/release-channel-pilot-001.json)

The baseline keeps the resident recipe or uses the family fallback on empty entry. The alternative screens recipes and chooses the lowest development mean plus the cost of changing recipes. The time screen combines measured cold prefill of the public prompt with generation time from a final tool call on prior attempts. Its largest value was 24.89 seconds at the 120-second ceiling and 18.01 seconds at the 90-second ceiling. All arms fit. This estimates two sampled operations and leaves workspace work, tools and review outside the estimate. It supplies no hard impossibility cutoff. An independent full-acceptance screen excluded Flint on codec after one rejected handoff in two development attempts.

We price one hypothetical dispatch at a time. Staying resident costs zero additional setup. Switching costs either zero in the idealized comparison or the target's lowest or highest observed development load plus dedicated prefix warmup. On empty entry both policies pay for their target. JavaScript development used no separate warmup and supplied just one load observation per arm. Those prices are component estimates. We lack matched eviction, restoration and whole-dispatch switching times. We use per-campaign setup receipts directly. The [adjacent-job accounting](../scripts/analyze_worker_residency.py) applies when replaying an actual queue with observed gaps and competing jobs. The scored task times include all attempts, including rejected ones where present. Missing held-out alternatives remain unscored.

## Which decisions changed?

Positive seconds below favor the selected recipe over keeping the resident one. Each codec row sums four independent dispatches across two seeds and both variants. Each release-channel row has one scored dispatch. These scenarios reuse trials, so their rows cannot be pooled as independent evidence.

| Family and resident | Choice with free switching | Seconds saved | Choice at measured setup prices | Seconds saved |
| --- | --- | ---: | --- | ---: |
| Codec, RANA | Stay | 0 | Stay | 0 |
| Codec, Coder-Next | Switch to RANA | −23.22 | Stay | 0 |
| Release channel, Qwen | Stay | 0 | Stay | 0 |
| Release channel, Flint | Switch to Qwen | −4.99 | Stay | 0 |
| Release channel, Coder-Next | Switch to Qwen | +5.76 | Switch to Qwen | −10.05 |

The observed low and high prices produced the same choices. Including setup changed two of the five decisions relative to free switching. On empty entry the rule retained the family fallback in both families. Codec with Flint or base Qwen layout resident lacks paired confirmation outcomes. All 11 evaluation trials in the table earned full acceptance.

**Codec.** Development favored RANA by 2.82 seconds per job. Confirmation favored Coder-Next on both paired seeds, by 10.09 and 1.52 seconds per job after averaging the two variants within each seed. That is the setup premium a switch from RANA could afford in hindsight. In the actual two campaigns per arm, each sharing one startup over two trials, Coder-Next saved 23.22 task seconds across four attempts. Loading and warming those campaigns brought its component total to 182.48 seconds against RANA's 181.44. The single-dispatch result and the batch comparison answer different questions.

**Release channel.** On the cold development seed, Qwen beat Coder-Next by 22.11 seconds, enough to cover Qwen's observed 15.81-second load. On the next, prefix-warm seed the advantage was only 5.76 seconds. The estimated 10.05-second loss already gives the switched-to Qwen its warmed task time. Replacing just its warm first-prompt cost with its measured cold one would add about 2 seconds. No live switch was measured.

A diagnostic suggested by that miss distinguishes a loaded model from a model holding a reusable prefix. Saving just 6.30 seconds of Coder-Next's 15.23-second first prefill would have canceled the predicted benefit of switching to a cold Qwen. The observed Coder-Next prompt saving between the two seeds was 15.05 seconds. Generation also varied. This calculation identifies a field worth recording prospectively, without establishing a second routing rule on the same seeds.

## Rejection and retry

The separate **60-second** Qwen confirmation produced ten correct implementations and seven accepted handoffs. The three rejected attempts occupied 77.48 task seconds. The archive contains no matched challenger at that ceiling. As a sensitivity check, treat successive disjoint seed pairs as five jobs and allow one fresh-seed retry after independent rejection. In chronological order this moves from 2/5 to 5/5 accepted and from 120.20 to 201.74 task seconds. Reversing the order inside each pair gives 5/5 on the first attempts and no retries. These are hypothetical review-triggered retries on a ready model. Maintainer review delay and model switching would add costs. The [blind submission-selection study](serial-selection.md) tests a reviewer who must make the retry decision before seeing the second submission. [Original acceptance record](release-channel.md)

## When to revisit

Reopen the comparison when ordinary work supplies repeated same-family jobs where the incumbent and challenger have comparable accepted and rejected attempts, the starting recipe and prefix state are known, and the expected single-job or batch saving approaches the measured setup cost. Start with a small matched contrast at that crossover. Record usable-result time including load, prefill, review rejection, retry and any restoration. Keep batch size and ceiling visible at dispatch. A short job alone supplies little reason to evict an already useful resident.

Reproduce every policy row, the prefix diagnostic and both retry orderings from a clean clone with the standard library.

```sh
python3 scripts/backtest_dispatch.py
```

The compact input records campaign IDs, recipe identities, original receipt or summary digests, and the sampled backend timing digests. The JavaScript retry calculation reads the published pilot directly. The full historical workstation store is needed only to re-extract the original backend receipts. [Frozen inputs](../results/dispatch-backtest-inputs-001.json) · [Calculation](../scripts/backtest_dispatch.py)
