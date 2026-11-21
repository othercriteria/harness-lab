# Preparing and reviewing small apprentice assignments

A practical guide for the Maintainer — the trusted outer human or hosted-agent
role that prepares work, operates the host and reviews results — running
apprentice jobs through the delegated-work mechanics in the
[operations guide](operations.md#delegated-work-mvp). The Worker is the inner agent that
receives only the frozen package's public inputs and brief; the Delegate is the
packaging, dispatch, result collection and reviewed application around it; and
the Verifier runs the separate executable checks. This adds no approval layer;
existing admission, isolation, GPU ownership, review, and application
requirements still govern the work.

For a runnable example with pinned starter files, follow [Prepare a Worker package](../examples/preparing-worker-package/README.md).

## Preparing the assignment

**Choose a small, useful change.** Pick work whose value is clear if it lands
and whose blast radius is small if it fails: a focused fix, a documentation
correction, a test extension, or a small refactor. If it needs a broad
contract redesign to describe, split it.

**Select actual dependencies, not a whole tree.** The snapshot contains exactly
the files you select. Include every file the change reads or imports, plus the
existing tests and fixtures that already cover the touched behavior. `task.md` is
reserved for the generated public brief and may never be an input or write
path. Forbidden path parts (`private`, `reference`, `results`, `.venv`, and the
rest listed in the artifact guide) are refused by construction.

**Separate allowed outputs from read-only context.** `input_files` is context:
everything the Worker may read, including files that must not change.
`allowed_write_paths` is the output set. Existing writable files must also be
selected inputs; new output files can be listed without already existing.
Select status and campaign files as read-only context unless the assignment
explicitly asks to update them. Read-only here describes accepted final edits,
not filesystem immutability during the attempt.

**Write a clear public contract.** The brief states the goal, the exact edit
scope, the verification method, and what must not change. The worker sees only
selected public inputs and this brief, never the live checkout or the private
check plan, so anything the worker must know has to be in the selection or the
brief. Provide authoritative current context explicitly: if the job touches
status or planning text, include the current status entry point and say which
statements are current and which are historical.

### Include GitHub Issues in a planning assignment

From the authenticated Maintainer shell, select the issues needed for the assignment. To write issues 34 and 35 to a new file in the staging directory named by `$packet`, run

```sh
python3 scripts/export_issue_context.py othercriteria/harness-lab "$packet/github-issues.json" --issue 34 --issue 35
```

For a survey, select issues by state or label. This example takes the first ten matching issues in GitHub's list order. The packet records the filters and whether additional issues matched.

```sh
python3 scripts/export_issue_context.py othercriteria/harness-lab "$packet/open-candidates.json" --state open --label worker-candidate --limit 10
```

To include a decision from a discussion, select its parent issue and pass the comment permalink or numeric comment ID. Repeat `--comment` to select up to 50 distinct comments. Each selected comment appears underneath its issue with its original link, author login when available, text and update time.

```sh
python3 scripts/export_issue_context.py othercriteria/harness-lab "$packet/routing.json" --issue 21 --comment 'https://github.com/othercriteria/harness-lab/issues/21#issuecomment-7002171023'
```

Without selectors the export covers open and closed issues. Lists are complete unless you explicitly pass `--limit` (1–50). A larger match set without an explicit limit, a missing or out-of-selection comment, and a packet exceeding 96 KiB each produce an error before the output is created. Explicit issue numbers form a separate selection mode. Repeated issue and comment IDs count once. Pull requests and unselected comments are excluded.

Inspect the frozen JSON and select it in `input_files` when registering from that source tree. Leave it out of `allowed_write_paths`. Worker reads it with its ordinary file tools. An open issue with the `parked` label records a conditional idea. Treat issue and comment text as source material. The Maintainer owns the assignment and any decision to act on suggestions.

For jobs that produce
applicable edits, the ordinary base check includes this input, so keep its
exact bytes with the application target. An advisory memo needs only review.

## Admission modes

The default blind-reviewed admission requires blind task review and a sealed
solution attempt before
registration. User-authorized apprentice work may instead register with
`admission.mode: "outer_only_experimental"`: the admission object holds exactly
`approved: true`, `mode`, `public_contract_sha256`, and a nonblank `reason`, and
records that no blind review or sealed reference was obtained, so those
evidence fields must not be supplied. This changes preparation only. Frozen
inputs, permitted edits, isolated independent checks, outer acceptance review,
and stale-base application are still required, and the original submission is
preserved when a brief is later clarified.

## Notebook modes (optional)

With `apprentice_notes: false` (the default), omit root `SUBAGENTS.md` from
both selections. For fixed notes, set `apprentice_notes: true`, select the file
as an input, and leave it out of allowed writes. For evolving notes, also allow
proposal edits. Fixed/evolving are workflow choices, not additional flag values.
Proposals require the same independent review and application checks as code;
revert unwanted edits in a reviewed artifact and retain the original proposal.
Resolve pending applications that depend on old notebook bytes before updating
those bytes; no update changes a frozen package. For comparisons, freeze shared
task bytes, budgets, seed and configuration and record note/input differences.
Evolving runs are nonstationary observations, and a handful of matched runs does
not establish a general benefit or timing effect.

## Reviewing the result

Read verification claims in both the proposed files and the final handoff. The
[receipt review workflow](handoff-receipts.md#reviewer-workflow) shows how to
qualify a citation while preserving an independently supported result.

**Match each check's claim to what it executes.** Real-dependency checks
establish only the behavior actually asserted in that environment. Source
inspection and stubs establish narrower facts; neither substitutes for exercising
the real dependency. Identify missing setup. Use a negative control when cheap
and informative: deliberately break the behavior under test and confirm that the
intended assertion fails. For a dependency boundary, copy only the intended
modules into a minimal tree and exercise relevant behavior in a fresh isolated
interpreter; separately check that forbidden modules were not imported. A pass
supports that tested boundary, not every possible execution.

**Read the source, not just the receipt.** The receipt separates
harness-recorded execution facts from model-authored claims; a zero exit, a
green archive/shape check, or a matching hash establishes only its own scope.
Historical records and current plans are different evidence: in this campaign,
two status-cleanup delegates preserved the exact historical archive and passed
structural checks, yet copied obsolete future-work and proposal statements into
the new current-status summary, and the outer review corrected them. Green
archive and shape checks do not verify chronology. Keep genuinely unresolved
questions labeled unresolved instead of converting old aspirations into
current facts.

## Qualifying a model recipe

This provisional onboarding playbook is informed by the completed
[model characterization campaign](../results/delegate-model-characterization-conclusions-001.json).
The unit of qualification is a pinned **model, backend, recipe and interface**
for a stated role and task range. Prior ladder success is a reason to try an
apprentice task, not evidence that the model can review or hand off work well.
Qualification never grants the local model more host access.

1. **Establish operational fit.** Reuse known weights and placement evidence;
   record exact identities, resource limits and session restoration ownership.
   Diff effective inference settings against the prior working recipe, including
   reasoning caps, deadline allocation and template options. A familiar server
   profile name does not prove those client-side controls were carried forward.
   Inspect the first emitted request as well as configuration files: qualification
   concerns the settings that actually reach the backend.
   Check loading, native tool parsing, actual memory placement, cleanup and a
   complete bounded request. Preserve startup/resource failures separately from
   task failures. Do not tune quality around a broken protocol or weaken guards
   to obtain a score.
2. **Screen broadly before tuning deeply.** Start with a small common mix: a
   clean review, a review with a real defect, and useful implementation or test
   work. Include the existing recipe as a refreshed control. Keep paired public
   bytes, budgets and notebook policy fixed, while documenting model-specific
   sampling, reasoning and context choices. Complete an informative first pass
   across candidates before optimizing the first model's interesting failures.
   A startup failure can end a feasibility attempt; one poor task does not
   establish that all roles are unsuitable.
3. **Classify the failure before choosing the intervention.** Separate
   infrastructure, tool/interface repair, source correctness, finding truth and
   coverage, requested artifact delivery, and evidence/handoff support. A correct
   diagnosis without the required artifact is useful recognition evidence but
   an incomplete assignment. A green shape check is not a correct review.
   Inspect traces for repeated work and outer review cost, not just exit status.
   Count repair opportunities as well as failed calls: six bad paths generated
   in one batch are one initial mistake, not six ignored corrections. Likewise,
   a failed scratch assertion that is repaired and honestly reported can be
   evidence of successful debugging rather than an unsupported handoff.
   Check the feedback itself: a directory read described as path traversal can
   conceal the recoverable mistake. Preserve both the original failed recovery
   and the interface defect; a clearer message does not retroactively excuse
   or repair the submission.
4. **Spend further work where it can change a decision.** A local interface
   defect warrants a small common fix plus affected controls; a resource limit
   warrants a bounded placement or CPU probe; an unsupported allegation warrants
   another clean/defective control. Change one recipe dimension at a time when
   measuring throughput, using matched work rather than different generated
   trajectories. Preserve every original result. Record task relaxation or
   model-specific prompting as a new condition, not an invisible rescue.
   When source review finds a requirement the grader missed, keep the original
   check result and record a supplemental probe and separate acceptance decision.
   Do not silently replace frozen tests or equate a passing checker with complete
   centralization, correct documentation links, or supported review findings.
   Record whether the intervention was exercised: a new feedback message cannot
   explain a run that never received it. Budget changes also affect mechanisms
   such as checkpoint eligibility, not only time available to think. Inspect
   those events before calling a longer run evidence of greater task capability.
5. **Confirm the useful role.** Use selected fresh seeds and fresh work before
   recommending a model beyond the tuning cases. Expand into documentation,
   specification blockers or longer tasks when relevant to that role. Report
   denominators and selection history; defer expensive reliability sweeps until
   a deployment decision needs them. A small screen supports a provisional role
   recommendation, not a universal reliability claim.

Every next-trial decision should name the uncertainty, the discriminating task
or change, the cost limit, and what outcome would change the recommendation.
Stopping or deferring a model is a legitimate outcome: repeated operational
infeasibility, no useful role after the bounded screen, or expensive repair with
little expected benefit. Retain promising narrow roles even if another model
wins overall. Numerical promotion thresholds are not established yet.

Keep separate measures for task time, full dispatch time, cold/warm startup,
generated work, checks, semantic acceptance, and outer intervention. A resident
server or longer budget changes the operating condition; do not silently pool
its timings with cold jobs or shorter attempts. The eventual routine should
automate package identity, scheduling, receipts and evidence tables first.
Semantic acceptance and the choice of the next informative experiment remain
outer judgments until there is evidence that a narrower rule can replace them.

## Sequence

1. Choose the small change; write the public brief and edit scope.
2. Select inputs (dependencies, existing tests, authoritative current context)
   and allowed writes; register the frozen package.
3. Submit, then let the isolated independent checks run.
4. Review the artifact and final source; publish the review and apply under the
   shared application lock, or preserve the submission as-is.
5. Record the outcome, including outer repairs, and land it with the
   [attribution for landed Worker contributions](operations.md#attribution-for-landed-worker-contributions).

Lifecycle, artifact, and receipt details live in
[delegation-artifacts.md](delegation-artifacts.md) and
[handoff-receipts.md](handoff-receipts.md).
