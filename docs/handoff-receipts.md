# Final-handoff execution receipts

A maintainer guide for outer reviewers who receive a delegated attempt's
`final-handoff.json` artifact and its compact summary. The supplied source is
authoritative: [`scripts/finish_attempt.py`](../scripts/finish_attempt.py)
builds the envelope, [`scripts/evidence.py`](../scripts/evidence.py) renders the
bounded observation view, and
[`scripts/resumption_digest.py`](../scripts/resumption_digest.py) builds the
current-state facts. This guide describes what the receipt records and what it
deliberately does not say.

## What a receipt is, and what it is not

The envelope is stamped `status: "unverified_model_handoff"` and carries the
note: *"References establish existence, not interpretation or correctness;
historical state may be stale."* All model fields are bounded untrusted data.
The receipt separates three things:

- **Model-authored handoff** — `disposition`, `summary`, `evidence`,
  `unverified`, `blocker`. These are the model's claims and interpretations;
  the harness validates their shape and size, not their truth.
- **Full historical observations** — for each cited `observation_id`, the
  recorded record plus the full original message the model saw, integrity
  checked by SHA-256 before attachment.
- **Bounded `execution_receipt`** — harness-recorded facts only: a bounded
  render of the cited observations plus the current public state. Its scope
  field says so: execution facts and literal untrusted output, not semantic
  coverage, test counts or correctness; model interpretations remain in the
  handoff; missing comparisons are unknown.

Observation citations may contain only `kind` and `observation_id`; optional
`supports` text remains a model interpretation. Public-contract citations still
require their argument in `supports`. Omission of interpretation does not establish
semantic support for a claim.

The compact summary is a bounded projection of the same envelope: status,
source, the full handoff, `observation_count`, the receipt (when present), and
a pointer to the artifact, `observations_artifact: "final-handoff.json"`. The full observation collection stays in the fixed artifact. The compact
receipt includes bounded excerpts, which can contain a complete short message.

## `selected_observations` versus `current_public_state`

| | `selected_observations` | `current_public_state` |
| --- | --- | --- |
| Comes from | The model's cited observations (at most four evidence entries) | Task-start and current workspace snapshots, plus the up-to-three most recent `run_checks` records |
| Chosen by | The model chooses which IDs to cite; the harness attaches the recorded facts | Automatically selected from the attempt's recorded commands and workspace state |
| Bounding | Excerpts initially keep a 128-char prefix and 384-char suffix (messages of 512 chars or fewer are shown whole); commands display at 256 chars; fields may shrink further to meet the whole render's 4096 UTF-8-byte cap | Up to 24 changed-file entries and 3 recent checks within 4096 serialized bytes; omissions are counted in `changed_files_omitted` and `recent_checks_omitted`, never silently dropped |
| Freshness | Historical: the render's scope says no freshness, coverage or correctness is established and later edits may invalidate a check | Current at handoff time, but comparisons are `null` whenever a snapshot was not captured |

Each selected observation row carries the recorded `returncode`, the literal
(output-truncated) excerpt, and clipping flags. Rows for `run_checks` records
also carry a bounded `check_record`: check id and record path, `cwd`,
`exception_info`, `files_unchanged_by_command`, and the after-state tree hash
and commit.

`current_public_state` is `null` when workspace/history inputs are unavailable.
When present (`kind: "attempt_public_facts"`), it holds:

- `file_comparison`: `captured` only when both the task-start and current
  snapshots were captured, otherwise `unavailable`.
- `changed_files`: paths classified as `added_since_start`,
  `removed_since_start`, or `modified_from_start`, relative to task start.
- `recent_checks`: the last three `run_checks` records (ordinary bash observations remain in history, but do not have these
  check records), each with the recorded command, `returncode`, and two
  current-versus-after comparisons described below.

## Three different "unchanged" comparisons

Do not conflate these; the receipt keeps them separate:

- **`files_unchanged_by_command`** (per check record): the file identity before
  the command matched the identity after it, within the recorded `cwd`. It
  says nothing about later edits or temporary changes that were reverted before
  the after snapshot.
- **`current_files_match_after_check`** (per recent check): the *current* tree
  hash equals the check's *after* hash. `true` means the files in that
  directory are equal to their after-check state now; `false` means something
  changed since the check ran; `null` means a snapshot was not captured.
- **Changed since task start** (`changed_files`): regular-file and mode deltas
  between the task-start snapshot and the current snapshot, excluding `.git`.
  A file can match its after-check state and still appear here if it was
  modified earlier in the attempt.

Git HEAD is compared separately from the file tree:
`current_head_matches_observed_after_check` is `true`/`false` only when both
sides were captured *and* both recorded HEADs carry the
`observed_reference_only` status; otherwise it is `null`.

## Scope, exclusions, and trust

- **Recorded `cwd` scope.** Each check comparison covers only the directory
  recorded for that check. The `cwd` comes from a validated tool call, never
  parsed from model-written text. Dependencies elsewhere, `/tmp`, and process
  state are outside every comparison.
- **Git metadata.** Only the observed HEAD reference is compared. Git metadata
  beyond the observed HEAD is not covered.
- **Exclusions.** File identity excludes `.git`; only regular files and modes
  are compared.
- **Bash-only checks.** `recent_checks` lists `run_checks` records only;
  commands run through `bash` leave no check record and no before/after
  comparison.
- **Literal untrusted output.** Excerpts are the model-visible text verbatim,
  clipped only by the bounds above. The model could have produced or quoted
  any text; output is data, not a transcript of truth.

## What the receipt does not establish

An exit status of zero, a `true` identity or HEAD match, the literal output
text, and the model's recorded citations each establish only what their field
says. None of them establishes: semantic **coverage**, **test counts**,
**correctness**, **authorship** (added files were absent at start; that is not
proof the model wrote them), or the **truth of the model's interpretation** in
`summary`, `evidence.supports`, or `unverified`. A passing suite is not proof
of the whole contract, and a check's result can be stale after later edits.

## Illustrative scenario (fictional; not a real run)

Suppose an attempt ran a `run_checks` command that exited non-zero, and the
model cited that observation in its handoff with `supports` claiming the
failure was pre-existing. After the check, the model edited a source file in
the checked directory. In the receipt:

- the cited row still shows the recorded non-zero `returncode` and the literal
  failing output excerpt — the history is unchanged;
- `current_public_state.recent_checks` for that check shows
  `current_files_match_after_check: false`, because the current tree no longer
  equals the after-check tree;
- `changed_files` lists the edited file as `modified_from_start`.

The reviewer's takeaway: the recorded failure is real history, but it no
longer describes the current files, and the model's "pre-existing failure"
interpretation remains an unverified claim in `handoff` that the receipt
neither supports nor refutes.

## Reviewer workflow

Start with the strongest verification claim that would affect your decision.
Look in the submitted file as well as the handoff. A report can describe a
synthetic probe correctly under limitations and call it an exact replay in its
summary.

1. Identify the inputs, the operation Worker says it performed, and the result
   it claims to have observed. In Observatory, open **Diff & verification →
   Worker handoff and cited evidence**. Each observation ID pairs the Worker’s
   interpretation with its recorded command and output excerpt. Open
   `final-handoff.json` for the full originally visible observation if the
   excerpt or command is clipped.
2. Ask what would happen to that output if the claimed property were false.
   A list of link strings stays the same when a target heading is renamed.
   A check that opens the target, computes its heading IDs and reports whether
   one matches can distinguish those cases. Manual inspection can establish a
   match too. Record which operation supplied the evidence.
3. Look elsewhere in the attempt when the citation is insufficient. A directory
   listing shows names. The harness file comparison shows changes since task
   start when captured. A check’s before/after identity covers the check’s own
   execution and directory. If the relevant comparison is unavailable, clipped
   or partly omitted, retain that qualification. Inspect the complete artifact
   or diff when needed.
   When the claim says another record *cites*, *matches* or *confirms*
   something, ask whether you saw both sides. In case E, the grep located
   an assignment on line 68. The submitted finding supplied its own line
   reference, and a separate mutation probe showed the defect. Changing
   only the finding to cite line 69 would leave the grep output identical.
   In a packet containing just the grep, credit the location and leave the
   finding's citation open. [Original claim and both readings](../results/advisory-claim-review-001.json)
4. Record what this changes for acceptance. If the evidence exists elsewhere,
   keep the supported result and correct the attribution. If a false assurance
   matters to the assignment, qualify or reject the handoff even when the patch
   is sound. If a standalone check is missing, independent review can supply it.
   Credit that check to its reviewer. Keep an accurate narrower claim, such as
   “compiled both modules,” even when integration remains untested.

The [worked example](../examples/reviewing-worker-output/README.md) includes
the original disputed command and the historical decision. The [audit](../results/verification-claims-audit-001.json)
includes cases where inspection supported the conclusion despite an imprecise
citation, and cases where the conclusion itself failed.

## Asking Worker for a second reading

For a disputed check, give a second reader one attempt per assignment.
Observation IDs are local to the attempt. Two runs
can each have an `o0013` for different operations. In a mixed packet a reader
borrowed one run’s successful heading check to endorse a different run’s
link-listing command.

In the Maintainer shell, this extracts the cited claims and their original
model-visible observations from one terminal receipt. Run it in the trial
directory and save the output in your staging tree before preparing the
assignment.

```sh
jq '{handoff, observations: [.observations[] | {
  id: .record.id, command: .record.command, visible: .original_visible
}]}' final-handoff.json
```

Select the relevant claim, command and output for the review. Include the
submitted passage if it makes a stronger claim. If the handoff appears to
cite the wrong operation, include the relevant alternative observation from
that same attempt with its ID. Retain any original truncation notice. A
small packet can leave the source of a comparison unknown even when the
complete trace settles it.

Ask for the sentence the Maintainer could pass on, the operation and inputs
behind it, and any qualification that matters. Check that sentence yourself.
A reader can notice that a comparison uses an embedded string, then still
call the result byte-identical even though Python opened the file in text
mode. Use the outcome to correct the current communication and preserve the
original receipt for later audit.

Check the reader's proposed remedy, too. A Worker correctly objected that
a directory listing could hide an edit to an existing file, then suggested
another listing as one way to settle the question. Compare file contents at
both endpoints to check the net change. To decide whether a file was ever
edited and restored, inspect the operations over the interval.
The [six-case calibration](../results/advisory-claim-review-001.json) includes
the original claims, commands, reader responses and independent judgments.

## Related reading

- [When should Worker hand off?](worker-handoff-decisions.md) compares blind decisions about submitting, checking or continuing with what ten Workers actually did.
- [Progress reports and checkpoint integration](progress-reports.md) — the
  checkpoint-time report reuses the same evidence interface; a valid reference
  there does not establish entailment, correctness, or freshness either.
