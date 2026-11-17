# What the progress reports tell us

The frozen reliability campaign produced useful evidence about **reported work
and verification**, but not a calibrated forecast of completion. The reports help
distinguish inspection, edits, tests and remaining work. Their broad progress
labels and obstacle fields are too weak to support automatic stopping.

This analysis covers freeze 360 only: nine smoke trials and 150 fresh-seed
confirmation attempts on nine known development tasks. The separate Markdown
wording and Frame ceiling experiments are excluded. See the
[cohort results](../results/frontier-reliability-frozen-cohort-001.json),
[prospective analysis policy](../results/frontier-progress-analysis-plan-001.json)
and [attempt ledger](../results/frontier-reliability-all-attempts-001.json).

## Exposure and review

There were 141 valid reports from 54 trials, including nine reports from four
smoke trials. All recorded checkpoint responses passed schema validation; there
were no rejected responses in this cohort. This does not prove that rejection
handling works in every circumstance.

Reporting was disabled in 84 trials, and another 21 completed without an eligible
checkpoint. These are different exposure states, not missing failures or implicit
positive reports. The shorter tasks therefore provide reliability evidence but
little evidence about progress reporting. No artificial checkpoints were added
to manufacture observations.

The confirmation sample contains 50 reporting trials. The prespecified hash
selection chose at most two reports per trial: 91 reports total. All were reviewed,
along with every smoke report and additional reports from failed trials. Those
sets overlap: 109 distinct reports were required and all have bound reviews.
Additional explanatory reviews remain distinguishable from the primary sample.

Primary semantic summaries give each reporting trial equal weight within its
task; a trial with more checkpoints does not count as several independent trials.
The labels retain detailed qualifications rather than collapsing every partial
claim into a binary score. Their fine-grained vocabulary is descriptive and
reviewer-assigned, not a validated measurement scale. Many reviews were sealed
from trace prefixes before the outcome was inspected; each record states its
actual blinding. Do not assume uniform blinding across all historical reviews.

## Costs and coarse signals

| Confirmation task | Reporting trials | Reports | Primary reports | Joint checkpoint time / task time |
| --- | ---: | ---: | ---: | ---: |
| Event import | 15 | 40 | 28 | 14.81% |
| Tabreport | 15 | 55 | 30 | 19.55% |
| SQLite | 10 | 15 | 15 | 10.28% |
| Long Git | 10 | 22 | 18 | 9.94% |

The last column uses total times within each task, including failures. It measures
the joint checkpoint response, which includes the continuation summary as well
as progress reporting, and is already included in task time. It is neither an
estimate of removable reporting overhead nor a causal comparison against running
without checkpoints. Reorientation and later repeated work have additional costs
that this column does not isolate.

Only one of the 50 reporting confirmation trials emitted a nonempty obstacle.
Among the ten long Git trials, three of the four source failures reported no
obstacle at any checkpoint. An empty field is weak reassurance.

Reporting a failing check frequently accompanied successful repair: 10 of 11
Event trials, five of eight Tabreport trials, five of six SQLite trials and two
of three long Git trials that ever reported a failing check ultimately had fully
accepted results. These are retrospective, whole-trial associations. They are not
the probability of success at a particular checkpoint, and they mix historical
baseline failures, current implementation defects and errors in self-written
checks. They cannot directly justify an online stopping rule.

## Concrete lessons from the traces

**Implementation progress and source correctness are distinct.** Long Git trial 0
performed its promised final-revision checks, genuinely passed both supplied
suites and cited the results truthfully. The uniform outer probe nevertheless
showed that legacy service validation bypassed an overridden `write` method.
An accurate progress report can accompany a wrong implementation.

**A failed check can be useful progress.** SQLite trial 3 reported a real current
syntax/import failure at its second checkpoint, then repaired it and completed
with correct source and a truthful handoff. SQLite trial 9 likewise recovered
from an existing-ledger failure. These differ from stale baseline failures even
when their coarse check categories match.

**An evidence error can survive otherwise effective work.** SQLite trial 8
implemented the task correctly and followed through on additional CLI checks,
but described a nonexistent database path as an existing-database dry run. That
unsupported precondition persisted into finalization. More successful test runs
did not repair the evidence claim.

**Plans can repeat without action.** Tabreport trial 9 announced implementation,
tests and checks, then spent the following interval on another orientation pass.
The next interval eventually produced edits. Several other trials reread files
before carrying out their stated next action. Some rereading may be necessary
after context recovery; the traces alone do not establish that all of it is waste.

**A plateau need not imply futility.** Long Git trial 9 truthfully reported empty
implementation and unknown tests at approximately 160 and 311 seconds, while
labelling change “advanced.” It then completed and tested the stable branch and
replaced a risky message-based exception plan with a private-marker design.
The final implementation passed both outer probes in about 587 seconds including
verification. Its broad label overstated concrete advance during the plateau,
but an early stop would have discarded a successful attempt.

The general pattern favors explicit statements of what changed, what was
observed, which revision was checked, and what remains. “Advanced” may mean
orientation, implementation or verification; those meanings should remain
separable. Next-action follow-through also differs from eventual correctness.

## Implications and limits

The evidence supports testing a small factual resumption digest, clearer
command-local check semantics, and better preservation of tested-command status
when output is bounded. Such changes should carry only attempt-public evidence;
they should not expose private evaluator information. Repeated inspection should
be measured before suppressing it: in the long Git traces, rereading sometimes
corrected a mistaken interpretation.

This campaign does not estimate calibrated success probabilities, validate a
futility threshold, or establish a causal effect of progress elicitation. Reports
are checkpoint-selected, tasks are known development material, observations
within a trial are correlated, and human semantic review remains a source of
judgment. Handoff failures range from citation imprecision to unperformed-check
claims, and source failures are a separate outcome. Pooling them into one failure
label loses information useful for both reliability and calibration work.

The durable research directory is
`/bulk/dlk/local-harness/research/frontier-reliability-001/`:

- `progress-dataset.json`: reports, response attempts, exposure and review links.
- `progress-analysis.json`: task-stratified, trial-weighted grounding summaries,
  timing, and outcome-component associations.
- `progress-transitions.json`: adjacent report intervals and trace references.
- `progress-followthrough-examples-001.json`: 13 deliberately selected explanatory
  examples; these are outcome-aware illustrations, not a frequency sample.
- `progress-review-longgit-c09-001.json` through `003.json`: prefix-only reviews
  of the final Git trial; primary reports are 1 and 3, with 2 diagnostic.
- `failure-taxonomy-frozen360.json`: all 18 failed confirmation attempts, including
  severity and interpretation qualifications.

The cohort result file binds the main dataset and analysis bytes by hash. The
coverage and review-binding audits verify artifact linkage and accounting; they
do not replace the semantic judgments recorded in the reviews.
