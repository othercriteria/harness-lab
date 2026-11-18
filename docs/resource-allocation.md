# Choosing the next local-agent experiment

This is a finite-horizon planning framework, not a new scheduler or a forecast of
returns. The selected planning anchor is a **compelling, reproducible
demonstration in 2–4 weeks**. Regular apprentice use and learning for its own sake
are legitimate alternative objectives, analyzed separately. There is no assumed
infinite stream of future tasks to repay today's engineering.

**Recommendation:** make the current system legible and reproducible to someone
who did not follow its construction, instrument the few missing costs during
that work, and treat scoped continuations as a bounded optional investigation.
The demonstration should not depend on a new context mechanism succeeding.

The substantive result is not that scoped continuations are unpromising. It is
that we cannot rank them by a speed percentage alone. Their strongest plausible
benefit here is avoiding repeated investigation or enabling better completion;
cache reuse is a separate, narrower hypothesis. A useful negative result can
earn a place in the demonstration if it answers a clear question.

## 1. What the Resource Balance Principle supplies

Omohundro's Resource Balance Principle says to allocate a resource until its
marginal contribution to expected utility is equal across the uses receiving it.
For our purposes this is a local optimality condition, not a complete objective
or an algorithm. It requires a specified payoff, resource constraints and a
model of consequences. [Omohundro, §4.1][omohundro]

Three qualifications matter:

1. **Resources have separate constraints.** A GPU hour, an outer engineer's
   active hour, a user's attentive hour and a calendar hour are not interchangeable.
   An implementation can proceed during a model run without consuming a second
   GPU slot. An unattended experiment can consume little user attention but
   displace another workload on the workstation.
2. **Equality applies to smooth, interior choices.** An unused option can have a
   lower marginal return. Indivisible changes, startup costs, threshold effects
   and complementary features require comparing small bundles, not blindly
   equalizing spending or always choosing the best isolated tweak.
3. **Even an oracle about technical outcomes would not supply preferences.**
   Knowing that a feature saves 10% of inference time does not tell us how many
   relevant tasks remain, whether inference is limiting progress, or whether a
   better explanation of the existing system is more useful.

This is our application of the principle; the constraints, models and numbers
below are not claims from Omohundro's paper.

## 2. A small model of the whole project

Let the state contain the current recipes and harness, evidence about them,
remaining work, demonstration readiness, and beliefs about future performance.
Let `T` be the delivery date. A policy chooses among implementation, experiments,
acceptance/review, useful delegated work, explanation/replay work, and stopping.

The objective is:

```text
expected value of useful accepted work before T
+ value of a credible, usable demonstration at T
+ explicitly valued knowledge gained by T
− external costs and losses
```

The third term is for knowledge valued in its own right. Learning that improves
future decisions already contributes through those future decisions; counting
the same benefit again as "learning value" would double count it. Similarly, a
patch that improves the harness and appears in the demonstration is one change
with several consequences, not two independent productivity gains.

Constraints include:

```text
At every instant: local-model GPU owners ≤ 1, within the host's available windows.
Sum of actual GPU-lease durations, including required setup, ≤ available GPU time.
Outer active work ≤ outer capacity; user attention ≤ user attention budget.
Precedence, review/closure, memory placement and delivery deadlines must hold.
Sandbox/evaluator separation and evidence integrity remain hard constraints.
```

The GPU lease is the relevant coarse resource: a CPU-bound part of a model run
still prevents another evaluated model from acquiring ownership. GPU utilization
is useful diagnostic data, but 40% utilization is not 60% schedulable spare
capacity. Session-level exclusion of other services is a separate opportunity
cost: a long quiet session may block external uses even between trial leases.

Aggregate hours are necessary but not sufficient. A set of eight-minute trials
does not fit into a collection of five-minute access windows. Trials also have
preparation and review dependencies. The calculations below deliberately relax
those scheduling details, so their capacity is an upper planning bound, not a
promise about a real queue.

In a smooth relaxation, each binding resource has a *shadow price*: the value
of a little more of that resource at the current optimum. A GPU improvement is
worth little for throughput if review is the bottleneck, although reduced
electricity, latency or interference can still have direct value. A quiet GPU
window immediately before a delivery deadline can be worth much more than one
several weeks earlier. Shadow prices change with the state; they are not a
permanent conversion between GPU time and human time.

The full sequential version is simply:

```text
V(state, beliefs, budgets, time)
  = best feasible choice of:
      value delivered by the next action
      + expected V(updated state, updated beliefs, remaining budgets, later time)
```

Its terminal value is the demonstration and remaining useful knowledge at `T`;
unallocated GPU time is not itself a failure. We do not attempt to solve this
large problem. It tells us which effects a tractable approximation must retain.

## 3. What we know, and what we do not

The [evidence snapshot](../results/resource-allocation-evidence-001.json) records
source hashes and derived timing fields. It includes all original assignments
in the selected panels, not only successes. These are development observations,
not deployable reliability estimates.

| Observation | Implication | Limitation |
| --- | --- | --- |
| Latest Qwen panel: 9 assignments, 7 full results; 1,334 s task time and 1,531 s dispatch | The current default already supports a small, substantive demonstration | One seed on selected assignments; acceptance work is not in these clocks |
| Reported Qwen prefill: 124.28 s, or 9.31% of task time / 8.12% of dispatch | Cache-only savings have a modest fixed-trajectory ceiling on this panel | Scope benefits can also change generation, repetition and correctness |
| All 104 Qwen requests have recorded responses; four resets across four assignments | This prefill sum does not silently treat a missing terminal response as zero | Backend accounting is still not a full causal timing decomposition |
| Nineteen earlier apprentice jobs: 3,376 s task / 3,763 s dispatch; median difference about 20 s/job | Small-job lifecycle costs deserve attention | Dispatch-minus-task is not all removable overhead or pure GPU occupation |
| Six bounded reviews: 756 s task / 878 s dispatch, with roughly 1–3 minutes of outer review per case | Acceptance work can be comparable to inference | Coarse interleaved estimates; preparation and repairs are not fully measured |
| Earlier frozen reliability cohort: 132/150 full results, including 13 handoff-only failures | Correct source, supported reporting and clean completion are separate levers | Historical recipe cohort; not the current recipe's success probability |

The largest missing quantities are the number and mix of future useful
assignments, active preparation/acceptance costs, audience comprehension, and the
remaining work needed to make a demonstration independently navigable. We have
far more precise token counts than estimates of several quantities that could
reverse the next-step decision.

Maintain three evidence classes:

- **Measured:** pinned attempt times, exact outcomes, artifact sizes, reported
  prefill, explicit source/receipt facts.
- **Estimated but not measured well:** review effort, implementation duration,
  fraction of future work affected by a mechanism, likely reuse of an artifact.
- **Preferences/scenarios:** delivery date, audience, amount of user attention,
  willingness to spend on curiosity, value of extra capability versus clarity.

Do not turn goal elapsed time or a hosted-agent token count into a human labor
estimate. Do not add dispatch and task time; one contains the other.

## 4. Oracle experiment: known gains can still be the wrong next step

For a homogeneous stream, suppose an attempt costs `g` GPU-lease seconds, `o`
outer-active seconds and `h` user-attention seconds. It yields a fully accepted
result with probability `p` under a specified review/repair policy. Costs include
unsuccessful attempts. With budgets `G, O, H` in seconds and accepted demand `D`:

```text
useful accepted-work capacity ≈ min(D, pG/g, pO/o, pH/h)
```

This fluid approximation permits fractional expected outputs and enough eligible
attempts to use the budgets. It is not the probability of finishing a fixed list
of tasks; heterogeneous costs, correlated failures and deadline tails require a
different calculation. Repairs that improve `p` also change `o` and possibly `g`.

Here is a **deliberately invented**, perfectly known example: `p=.8`, `g=3 min`,
`o=6 min`, `h=30s`. Investment costs are temporarily omitted to expose the
bottleneck; including them can only make a proposed improvement less attractive
on this narrow capacity metric.

| Available work regime | Baseline | GPU time −10% | Outer effort −⅓ | User attention −⅓ | Acceptance .8→.9 |
| --- | ---: | ---: | ---: | ---: | ---: |
| GPU constrained: 4 GPU h, 20 outer h, 4 user h | 64 | 71.1 | 64 | 64 | 72 |
| Outer constrained: 40 GPU h, 4 outer h, 4 user h | 32 | 32 | 48 | 32 | 36 |
| User constrained: 40 GPU h, 20 outer h, 15 user min | 24 | 24 | 24 | 36 | 27 |
| Enough capacity, demand for six accepted units | 6 | 6 | 6 | 6 | 6 |

In the final row, reliability can still greatly improve the chance of delivering
the complete demonstration on schedule; the throughput cap hides that effect.
For illustration only, three independent first attempts all pass with probability
`.8³=.512` versus `.9³=.729`. Real demo cases need not be independent. Retained
replays remove live stochasticity from presentation but cannot be represented as
fresh successes or evidence of general reliability.

This answers the oracle question: the same certain performance improvement has
different value depending on the remaining work and constraints. A metric such
as "percentage faster across the ladder" cannot decide the allocation by itself.

## 5. Repairing the 100-hour hurdle

For a fixed workload, let `B` be its future baseline GPU hours **after the change
is available and before the horizon**, `f` the share actually affected, and `r`
the fractional time reduction on that share. Let implementation/validation cost
`E_G` GPU hours and `E_O` outer hours. If GPU time is marginally valuable, write
`rho = value of an outer hour / value of a GPU hour`. The narrow efficiency
break-even condition is:

```text
B × f × r > E_G + rho × E_O
```

Add maintenance, user attention, rollout/reconfirmation, regression losses and
calendar delay where relevant. If a 10% throughput gain rather than a 10% time
reduction is specified, the fixed-work time saving is `1 − 1/1.10 = 9.09%`.
Also distinguish a fixed-work saving from extra work completed under a fixed
time budget; they are different denominators.

For example, suppose a change costs 2 GPU hours plus 4 outer hours and saves 15%
on 30% of future runtime. At `rho=0` it needs **44.4 future GPU hours** to repay
its direct GPU investment; at `rho=.25`, **66.7 hours**; at `rho=1`, **133.3
hours**. Those are assumptions, not a quote for scoped-continuation development.
On 40 future GPU hours it saves only 1.8 hours before costs. It can still be worth
doing for capability, knowledge or demonstration value, but not on that speed-only
argument.

An early efficiency win helps subsequent experiments as well as useful tasks.
Count those genuine planned experiments in `B`. Do not justify a feature by
inventing hundreds of additional experiments whose only purpose is to amortize
the feature. A substantial backend/model change can shorten its useful lifetime.
The delivery date and the expected stability of the recipe both truncate exposure.

Complementarity matters: a change that is unattractive alone can be valuable
with another change that removes the remaining bottleneck. Compare a few coherent
bundles when there is a concrete interaction, and charge the costs of the bundle.
Do not give every speculative feature credit for a possible future partner.

## 6. Experiments buy decisions, and sometimes useful artifacts

Rational metareasoning values computation through its consequences for later
actions. Selection problems differ from ordinary reward-earning bandits: a
benchmark trial can be useful because it informs a later choice, even if it
produces no useful patch. This does not make bandits irrelevant; it means our
campaign mixes information acquisition, engineering and occasional direct work.
[Russell and Wefald][russell]; [Hay et al.][hay]

For a fixed downstream decision and budget, expected sample information has value

```text
E_over_possible_data[max_action E(value | data)]
− max_action E(value with current information).
```

Subtract experiment, review and delay costs. A full policy comparison also lets
the alternative spend those resources elsewhere. Information that would not
change any action has no *instrumental* decision value, though it may have
explicit knowledge or communication value. Greater confidence can change an
action such as accepting an artifact, offering it for use or narrowing a claim;
those count too. [Heath et al., EVSI tutorial][evsi]

The [calculation script](../scripts/analyze_resource_allocation.py) includes an
exact synthetic example. A candidate has a 30% prior chance of cutting task time
by 10%, otherwise increasing it by 5%. Adoption costs one GPU-hour-equivalent.
A noisy diagnostic distinguishes the states with 75% positive signals in the
good state and 25% in the bad state. Setup costs .15 and each observation .08 in
the same chosen opportunity-cost units. These are **not fitted beliefs about any
real candidate**.

| Remaining baseline workload | Value of free perfect information | Best fixed diagnostic count (cap 12) | Net value, fixed count | Net value, adaptive stopping |
| --- | ---: | ---: | ---: | ---: |
| 10 GPU h | 0 | 0 | 0 | 0 |
| 40 GPU h | .90 | 4 | .088 | .256 |
| 100 GPU h | 2.70 | 7 | 1.503 | 1.830 |

The adaptive rule pays the same costs and updates the same belief; it can stop
early on decisive results. It averages 3.98 observations in the 40-hour scenario
and 5.69 in the 100-hour scenario. Its value is higher because it spends
observations selectively, not because stopped trials are erased. These are
bounded complete diagnostic observations, not truncation of a running coding
trial after looking at its outcome.

Free perfect information bounds the value of sampling about this fixed decision.
It does not bound the value of implementation that creates a new option, or a
useful artifact produced by an experiment. The toy treats the future workload as
still deliverable after sampling; near a real deadline, sampling also reduces
remaining exposure and can be less valuable. Unknown likelihoods, task dependence,
development adaptation and multiple endpoints prevent importing the toy's exact
optimal policy into the real harness.

This is why a bounded staged investigation is often preferable to either a large
sweep or no experiment. The stages need a named decision, plausible outcomes that
change it, and the next block's full cost. Heterogeneous-resource best-arm research
supports treating sampling cost explicitly, but does not solve our combined
engineering and demonstration objective. [Li and Cheung][resource-bandits]

## 7. Reliability and learning have real experimental costs

Twenty trials are not a universal unit of rigor. Under IID sampling, 20/20 has a
one-sided 95% exact lower success bound of about .861. A true .95 recipe produces
20/20 only about 35.8% of the time. Repeating until a perfect panel appears does
not create the intended reliability evidence. New seeds on an old task also do
not test generalization to a new task.

For another **assumed** planning example, suppose paired task-time differences
have standard deviation 30% of baseline time. A normal approximation for 80%
power at a two-sided 5% threshold requires roughly:

| True mean time reduction | Approximate paired observations | GPU time at 6 min/pair |
| --- | ---: | ---: |
| 5% | 283 | 28.3 h |
| 10% | 71 | 7.1 h |
| 20% | 18 | 1.8 h |

These are not sample-size prescriptions for our skewed, failure-containing runs.
They show why proving a small benefit can cost more than exploiting it over a
short horizon. Correctness is a separate endpoint, and pairing on numeric seeds
does not guarantee low variance. Mechanistic probes can cheaply eliminate some
hypotheses before costly end-to-end runs; they cannot establish task reliability.

A failure can have high information value even though it produces no accepted
work. Conversely, a twentieth passing replay can have low information value
once it cannot change any decision or claim. Fresh task coverage, investigation
of a new failure class, or a demonstration rehearsal may then be better uses of
the next GPU slot. Preserve failure analysis and sufficient assurance for the
actual intended use; this is not a license to skip acceptance checks.

## 8. The demonstration changes the objective

A useful demonstration is a short path from a claim to evidence that another
person can inspect. More features do not automatically improve that path.

A minimal candidate package would contain:

- One bounded implementation/test contribution and one bounded review, with exact
  public inputs, outputs, acceptance decisions and attributable outer repairs.
- One informative incomplete or rejected attempt, showing that green checks and
  clean finalization are not substitutes for source and claim review.
- A pinned recipe/environment, replayable saved traces, a short route through
  Observatory, and an optional fresh-run path with cold/warm costs distinguished.
- An explicit boundary diagram: local model, isolated workspace, independent
  evaluator, outer review/application, GPU ownership and restoration.
- A short account of one engineering decision with before/after evidence and
  qualifications. The quantization-layout comparison already supplies a candidate.

This is a proposed demonstration brief, not a newly admitted benchmark task or a
claim that those materials have already been assembled. No new audience contact
or publication is implied. Private trace contents would need selection/redaction
before any public release. A replay is labeled a replay; a local reproducibility
claim does not imply another machine has been tested.

The terminal benefit can be decomposed conceptually as

```text
P(delivered by date)
× P(understood by intended audience | delivered)
× value of the resulting use, discussion or decision | understood.
```

These are conditional factors, not assumed independent events and not calibrated
probabilities. They expose an important bottleneck: if evidence is difficult to
navigate, another 5% inference improvement may barely affect the payoff. A
technical reviewer should be able to distinguish what the user/outer engineer
designed, what the local model did, what was repaired and what the evidence proves.

Local utility should also be compared with the available hosted model or direct
implementation. A local delegate need not beat either on total labor to justify
a bounded demonstration or an experiment about controllable local execution.
But we should not quietly turn that exploratory value into a claim of economic
replacement. A compact external-system comparison can add vocabulary and reveal
missing assumptions; broad new tool installation is not required to tell the
current system's story.

## 9. Scoped continuations as a worked decision

The [deferred design](../results/deferred-scoped-continuations-001.json) saves a
parent context, executes a bounded scope on the same resident model, retains
workspace changes, and restores the parent with a compact result and evidence.
It is not workspace rollback, free parallel inference, or guaranteed cache
restoration. Keep three hypotheses separate:

| Hypothesis | What would support it | What could defeat its value |
| --- | --- | --- |
| Reuse the parent prefix | Exact-backend prefill/cached-token measurements after restoration | Hybrid-state reconstruction or ordinary continuation already gets the same reuse |
| Avoid context accumulation and repeated work | Less repeated inspection/reasoning at equal total budgets | Return summaries, lost details, stale assumptions and reorientation erase savings |
| Improve decomposition/completion | More supported useful results on tasks with a natural bounded investigation | Models choose poor scopes, lose dependencies or produce misleading summaries |

The latest Qwen panel's prefill accounting places an idealized cache-only ceiling
at 9.31% of task time. Actual parent-prefix savings are a subset of that time,
and incur overhead. This does **not** limit gains from changed generation,
smaller-context decoding, better reasoning or preventing a failure. Nor does it
generalize to longer tasks. It shifts the proposed experiment toward the latter
hypotheses instead of treating cache reuse as the main expected prize.

Before building a general tool surface, use this staged plan:

1. **Trace applicability and design, initially offline.** Identify a few actual
   bounded investigations, record their outputs/workspace dependencies, and say
   what the parent would need back. Exclude tasks selected only because a cached
   replay is convenient. Estimate affected runtime and return/reorientation costs.
   A plausible benefit must exceed those costs or unlock a valuable task.
2. **Minimal controlled probe, only after a separate experiment decision.** Compare
   ordinary continuation, restored parent with retained changes, and fresh
   context with the same return information. Start with fixed child results so
   we can isolate reorientation/cache behavior. Charge child, summary, restoration
   and return work to one cumulative budget. Measure actual backend reuse, not
   the mere presence of a stored transcript. This does not yet test autonomous
   scope selection or end-to-end gains.
3. **Small end-to-end screen if the mechanism survives.** Use natural assignments,
   the common incumbent, predeclared limits and complete artifact review. Separate
   externally selected scopes from model-selected scopes. Fresh task definitions
   still require the repository's blind-review/independent-solution admission.
   A null result is a valid stopping result; do not retrofit the task to guarantee
   a favorable scope. Expand only if the next decision warrants another block.

Across stages, retain changed-workspace manifests, invalidate stale check/read
receipts, preserve observation visibility correctly, keep cumulative budgets and
the full outer trace, and maintain the sandbox/evaluator boundary. Those are
implementation obligations, not optional costs to omit from the estimate.

The mechanism could be a good research demonstration even if net throughput is
unchanged, provided it answers a predeclared question and the actual costs and
failure modes remain visible. That is an explicit knowledge/demo justification,
not an efficiency claim. The current goal has not implemented or run these stages.

## 10. The original demonstration allocation

The [budget decision](https://github.com/othercriteria/local-harness-lab/issues/2) tracks application of this framework to current priorities. The table records the original illustrative plan.

The robust recommendation is to establish a small deliverable first and purchase
one bounded investigation option alongside it. Exact time caps below are proposed
working limits, not derived optimums or commitments of user time.

| Work | First budget/decision checkpoint | Continue when | Stop or defer when |
| --- | --- | --- | --- |
| Assemble the demonstration from existing evidence | About 2 outer hours; little/no GPU | A stranger can follow claims → traces → reviews, with clear gaps to close | More polish does not improve the agreed viewing/use path |
| Rehearse the acceptance/use path | At most three fresh assignments, within a provisional 1 GPU-hour block plus separately budgeted review | Results expose a specific delivery or acceptance bottleneck | The deliverable is usable; do not automatically sweep the full ladder |
| Record preparation/review costs | Attach coarse active intervals to those same jobs | The numbers distinguish inference, outer work and user attention as limiting factors | Detailed telemetry would cost more than the allocation decision warrants |
| Scoped-continuation applicability audit | About 1 outer hour, offline | At least a couple of natural scopes and a credible benefit route remain | Existing context handling is adequate, or return costs dominate |
| Optional controlled scope prototype | A new capped decision: initially ≤4 outer hours and ≤1 GPU hour, closure/review included in planning | State handling is correct and a useful behavioral or timing effect is plausible | Cache-only premise fails with no other use, costs exceed the remaining opportunity, or demo delivery slips |

The rehearsal should use an audience-relevant assignment, not merely the easiest
known benchmark. Its preparation can be ordinary apprentice work where that is
authorized, with honest admission labels and independent acceptance. A new
comparative benchmark remains subject to blind admission. No prototype is made
a dependency of delivering the existing-system demonstration.

Other candidates remain available under explicit conditions:

- **Safe timestamp preservation:** a bounded correctness/conventionality fix if
  it removes observed misleading reconstruction behavior without weakening the
  snapshot boundary. It need not wait for a large research mechanism.
- **Earlier evidence-grounded drafts / narrower review stopping:** investigate if
  trace review shows that sufficient findings existed long before handoff, while
  preserving missed-defect and unsupported-claim outcomes.
- **Setup optimization:** investigate if short-task dispatch or exclusive-lease
  measurements show a material removable component. Do not assume the whole
  observed ~20 seconds is avoidable.
- **Another model or broad reliability sweep:** select only for an unresolved
  intended-use decision, a specific claim, or meaningful regression concern.
  The latest model characterization already leaves a practical default.

A five-field decision card is enough: **decision to change; intended payoff by
date; resource costs; evidence that would reverse the choice; stop condition**.
Use ranges and break-even thresholds where effects are uncertain. Keep alternatives
as a Pareto set when no candidate dominates; do not manufacture probabilities or
precise utility weights simply to produce a numerical ranking.

## 11. Checks against attractive but wrong conclusions

- **"GPU is fixed, therefore every speedup is valuable."** Only when it releases
  capacity for valuable work or reduces a direct cost. Fixed supply does not
  imply binding demand, nor does it make review free.
- **"A demonstration is marketing instead of engineering."** Reproducibility,
  attribution and a clear failure case are technical deliverables. Conversely,
  visual polish alone need not teach an audience anything useful.
- **"Knowledge value can justify anything."** State the question and allocate a
  finite curiosity budget prospectively. A null result can satisfy it; endless
  mechanism tuning cannot be justified by renaming each iteration learning.
- **"The current framework favors safe, incremental work forever."** Capability
  thresholds and complementarity can make a risky larger step worthwhile. Compare
  its finite option value with alternatives; do not require a speedup-only case.
- **"External interest is guaranteed by a technically strong artifact."** It is
  unknown. A short explanation/rehearsal can reveal that more engineering is not
  the missing ingredient. Actual external feedback requires a separate user action.
- **"More theory will settle the preferences."** It will not. Stop modeling once
  the next bounded action is stable across plausible scenarios, or the remaining
  uncertainty can only be resolved by use or feedback.

## Reproduction and source boundaries

Run locally without a model, services, downloads or new dependencies:

```sh
python scripts/analyze_resource_allocation.py \
  --output /tmp/resource-allocation-calculations.json
cmp /tmp/resource-allocation-calculations.json \
  results/resource-allocation-calculations-001.json
```

[Scenario inputs](../configs/resource-allocation-scenarios-v1.json) are explicitly
invented and editable. [Calculated outputs](../results/resource-allocation-calculations-001.json)
include input/script hashes; the evidence snapshot preserves original source
hashes and does not require access to bulk traces for recomputation. Sanity checks
cover bottleneck limits, no-information/zero-benefit cases, information-value
bounds and fixed versus adaptive policies. No harness/runtime or frozen experiment
was changed, no GPU work was launched, and no flake/direnv change is required.

The sources establish the conceptual tools, not the project-specific rankings:

- [Omohundro, *The Nature of Self-Improving Artificial Intelligence*, §4.1][omohundro]:
  marginal resource allocation. The PDF is dated 2007, revised 2008; a recent
  search-engine crawl date is not its publication date.
- [Russell and Wefald, *Principles of Metareasoning* (1991)][russell]: computation
  valued through its effect on decisions.
- [Hay, Russell, Tolpin and Shimony, *Selecting Computations* (2012)][hay]: metalevel
  selection and stopping differ from ordinary cumulative-reward bandits.
- [Heath et al., *Simulating Study Data to Support Expected Value of Sample
  Information Calculations*][evsi]: the expected improvement in a downstream
  decision from sample information. We use the definition, not its medical model.
- [Li and Cheung, *Best Arm Identification with Resource Constraints* (2024)][resource-bandits]:
  heterogeneous sampling costs; not an optimality guarantee for our manual plan.

[omohundro]: https://steveomohundro.com/wp-content/uploads/2009/12/nature_of_self_improving_ai.pdf
[russell]: https://doi.org/10.1016/0004-3702(91)90015-C
[hay]: https://people.eecs.berkeley.edu/~russell/papers/uai12-meta.pdf
[evsi]: https://eprints.whiterose.ac.uk/id/eprint/174666/7/0272989x211026292.pdf
[resource-bandits]: https://proceedings.mlr.press/v238/li24c.html
