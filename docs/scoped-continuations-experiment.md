# Scoped continuations: measured experiment

Decision, 2026-11-17: **keep the prototype experimental and defer the end-to-end
pilot. Full history with the same return is the best measured option.** Parent
restoration is useful compared with throwing away all conversational history, but
this experiment does not justify making it a default or expanding the pilot now.

[Machine-readable conclusions](../results/scoped-continuations-experiment-conclusions-001.json) ·
[All comparison rows and reviews](../results/scoped-continuations-comparison-001.json) ·
[Cache diagnostics](../results/scoped-continuations-cache-001.json) ·
[Final validity audit](../results/scoped-continuations-experiment-audit-001.json).

## Results

Mean resumed seconds, two seeds per cell; earlier work and experimental priming
are excluded from this table and charged separately in the campaign cost ledger.

| Historical continuation | Full history + return | Restored parent + return | Fresh task + return |
|---|---:|---:|---:|
| Apprentice review | 63.4 | 79.7 | 112.1 |
| SQLite investigation → submission | 29.0 | 33.0 | 52.6 |
| Dual-branch Git backport | 102.7 | 172.7 | 228.5 |
| **Total across six continuations** | **390.2** | **570.8** | **786.5** |
| Strictly accepted, including handoff | 6/6 | 5/6 | 6/6 |

Full history was faster in five of six paired comparisons. Restored parent won
one review repeat, 72.7 versus 79.6 seconds, but was 46.3% slower in total. Fresh
context was 101.5% slower in total; restored parent beat fresh in all six pairs.
All eighteen deliverables met the selected bounded contracts. The one strict
failure was a correct review finding accompanied by a false claim that the
whole workspace hash remained unchanged after adding review.json. Waiving that
reporting defect would not change the timing comparison.

Source review also found a production-quality wart in the second restored Git
result: it reuses a mutable exception instance, so later failures can change an
earlier saved diagnostic and retain/grow traceback state. Exception lifetime and
concurrent use are outside this bounded task contract; the caveat is preserved
without retroactively changing frozen acceptance. No candidate source was landed.

Restoration removed about 2K–3K initial tokens; fresh context removed about
9K–11K. Nevertheless, completion tokens totaled 25.0K / 38.4K / 56.0K for
full/restored/fresh. Measured generation time was 276 / 431 / 615 seconds, whereas
prompt processing totaled 41 / 50 / 58 seconds. The reduced views led to more
subsequent activity, including reorientation and checks. Not every repeated read
was unnecessary, and these totals are not a causal decomposition of wasted work.
New ordinary context resets were 1 / 2 / 2. Smaller initial context did not ensure
less subsequent context pressure.

The 24 inert cache sequences show automatic parent-prefix reuse on this exact
hybrid backend, but its advantage varies with checkpoint availability. In one
resident condition full/restored took 0.29/1.06 seconds; in another 3.89/0.34.
Textual prefix overlap alone is not enough to predict the reusable state or a
speed win. These one-token diagnostics are not task performance measurements.

## Pilot decision and costs

The broad retained-information gate has a positive signal: parent restoration
beats fresh context. It would be inaccurate to describe that signal as absent.
The practical control, however, is full history with the same return, and there
is no persuasive net benefit over it. Under the predeclared weak-signal/no-rescue
rule, defer the discretionary end-to-end pilot rather than spending its additional
120-minute envelope on a new task and live child-return behavior. This is a
scoped negative adoption result, not a claim that scoped continuation cannot work.

Whole launcher lifetimes were **3.7 minutes for cache diagnostics and 35.4 minutes
for continuation experiments**, including startup, priming, verification, the
infrastructure failure, and shutdown. These are GPU-session occupation costs,
not a measure of outer implementation or review labor. Both fit their original
30/100-minute envelopes. The conditional pilot used zero GPU time.

The campaign is closed. Session 029's gpu-voice and ollama-background states were
restored and verified against the session-entry record. No flake/direnv changes
or environment restart are needed.

## What was compared

The exact resident Qwen3.8-27B/RANA-layout 32K recipe was held fixed. Twenty-four
inert sequences tested prefix reuse on the actual backend. Eighteen planned model
continuations cross three historical cases, two seeds and three context views:
full parent+episode+return, restored parent+return, and fresh system+task+return.
Each matched group starts with identical workspace, scratch, public evidence,
remaining budgets and the same outer-authored return. Parent and episode prompts
are primed before each dispatch. Priming is recorded separately from continuation
time; prior work is not credited as newly executed work.

The cases are a bounded apprentice review, SQLite CLI investigation followed by
submission, and a partially completed dual-branch Git backport. SQLite is already
implemented correctly at the cut; Git still needs the legacy adaptation. These
are selected continuation problems, not fresh tasks or whole-task reliability
trials. Full history also receives the compact return: this does not isolate the
value of writing that return versus ordinary unsummarized execution.

## Implementation and validity

The opt-in prototype supports one serial child scope at a time, a structured
return, retained workspace/scratch, immutable task authority, cumulative budgets,
complete outer traces and bounded read-only access to historical observations.
The staged runner installs the declared views directly. Scripted controls exercise
entry/return and recovery; actual model trials exercise continuation and ordinary
context recovery. Live model selection of scope boundaries and authorship of the
return remain unmeasured.

The initial batch stopped safely at its first Git context reset: the adapter had
not imported historical cleanup receipts. This was an infrastructure defect, not
a model failure. The repair validates old receipts in an outer-only archive and
continues checking all new execution boundaries. The failed attempt remains in
the evidence and cost ledger. Six unaffected completions were retained; the
interrupted cell and remaining eleven ran under a new freeze. Every matched
case/seed triad uses a single freeze. No task, sampling, weights, return or budget
was adjusted in response to its result.

There are 143 targeted checks with no skips, plus isolated scripted integration
controls and Observatory backend/JavaScript checks. The final audit checks staged
fixture bindings, identical initial worlds and views, cumulative counters and
new boundary cleanup. Each candidate also receives outer source/handoff review;
raw summaries are not rewritten to incorporate these judgments.

## Limits and what would justify revisiting

Two seeds on three selected worlds cannot establish reliability or universal
superiority. Only about 2K–3K episode tokens are removed by parent restoration in
these cases; initial full contexts fit comfortably within 32K. The experiment
therefore leaves open a different regime: much longer disposable investigations,
stronger context pressure, or a larger amount of valuable parent work remaining.

Regression bisection and resolving documentation-versus-implementation authority
remain plausible prospective cases. A new investigation should demonstrate why
its discarded material creates a real bottleneck, include full-history with the
same return as a control, and charge child generation, return construction,
retrieval and reorientation. Smaller context alone is insufficient evidence of a
useful optimization. The broader resource-allocation discussion remains deferred.
