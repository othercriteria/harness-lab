# Preparing and reviewing small apprentice assignments

A practical guide for the outer maintainer running apprentice jobs through the
delegated-work mechanics in the [README](../README.md#delegated-work-mvp).
This adds no approval layer; existing admission, isolation, GPU ownership,
review, and application requirements still govern the work.

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
everything the worker may read, including files that must not change.
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

## Sequence

1. Choose the small change; write the public brief and edit scope.
2. Select inputs (dependencies, existing tests, authoritative current context)
   and allowed writes; register the frozen package.
3. Submit, then let the isolated independent checks run.
4. Review the artifact and final source; publish the review and apply under the
   shared application lock, or preserve the submission as-is.
5. Record the outcome, including outer repairs, with the normal attribution.

Lifecycle, artifact, and receipt details live in
[delegation-artifacts.md](delegation-artifacts.md) and
[handoff-receipts.md](handoff-receipts.md).
