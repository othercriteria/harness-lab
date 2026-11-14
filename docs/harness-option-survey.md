# Harness option retirement survey

Survey date: 2026-11-14. The two initial retirements below are implemented in the
live tree following this review. No frozen recipes or trials changed. The seven selected recipes in the
[comparison close-out](../results/model-comparison-conclusions-001.json) are the
reference set, including its qualified Event and failed SQLite results. The new
workflow probes remain experiments.

There is substantial removable surface. At inspection, the live directory held
192 protocol JSON files; the seven selected recipes used 42 distinct top-level
fields, many descriptive or numerical rather than behavioral switches. The loader
and consumers expose 21 top-level boolean switches, plus nested recovery policies.
Most booleans have the same effective value across all seven recipes. Agreement
does not prove each flag independently optimal; it does establish that many are
no longer useful everyday choices.

The highest-value action is **delete unused paths**, not add a new configuration
layer. Historical replay can use an earlier Git tree or exact frozen snapshot.
Keep flattened explicit configurations in new freezes; do not require the live
implementation to interpret every historical experiment.

## First two deletions — implemented

| Path | Why it can leave the live harness | Change boundary and evidence |
|---|---|---|
| `handoff_phase` | None of the seven selected recipes or current workflow probes enables it. Its 186-line module added clock checks, tool restrictions, a changed prefix and execution gates across the main request path. | Deleted `scripts/handoff_phase.py`, its wiring in `coding_agent.py`, `run_trial.py` and `protocol.py`, and feature-only tests. [Freeze 170 result](../results/reliability-120-north-mini-code-handoff-consolidation-001.json): 1/4 full acceptance; a forced handoff could still misstate a failing result. This is retirement for lack of a current use, not proof the idea can never help. |
| `split_finalization` | All seven selected recipes use the combined `finish_attempt`; no active probe needs `submit_attempt`/`report_blocker` normalization. | Deleted the split branch and 225-line `finalization_api.py` adapter; current paths call `finish_attempt` directly. Removed notice/name rewriting and split-only tests. Submitted/blocked semantics, correctable invalid calls, evidence attachment and public-clause blockers remain. [Freeze 234 comparison](../results/diversity-split-finalization-consolidation-001.json) found no acceptance/blocker benefit. |

Activation now fails at protocol loading and direct model/prompt entry points with
a historical-replay explanation. The CLI omits retired configurations; their JSON
files stay untouched as evidence. Explicit `split_finalization: false` is accepted
as inert metadata, preserving existing combined recipes without a split runtime
branch. Historical `public_interface` rendering in the Observatory is retained.

Both implementations and tests are recoverable from Git
`6847e2237b4e77a3ede64e79e889ebb4b7d85968`. For exact experimental bytes, follow
`snapshot` and `runtime_dependencies` in [freeze 170](../results/success-freeze-170.json)
or [freeze 234](../results/success-freeze-234.json). A historical checkout needs its
pinned dependencies/artifacts, not merely old source. Keep observational readers
able to display old artifacts; they need not execute obsolete agent paths.

Feature-only `test_handoff_phase.py` and `test_split_finalization.py` were removed,
not skipped. The common blocker-disposition test remains in `test_prompt_contracts.py`;
`test_retired_options.py` covers clear rejection, inert false metadata and CLI
filtering. Existing malformed-call, terminal-state, deadline, evidence and isolation
tests remain. Before/after rendered prompts/configs/tool schemas were identical
for all 192 supported root protocols. Focused validation passed 68 tests. The full
suite ran 431 tests: 426 passed and the same five intentional host memory-scope
tests were skipped. Lint and whitespace checks passed. The count fell by 18:
21 feature-only tests removed, three retirement-boundary tests added. Frozen
288/289 snapshots already carry their own runtime code and remain unchanged.

## Choices to fix in the current interface

| Family | Current supported choice | Disposition |
|---|---|---|
| `structured_finalization`, `split_finalization`, `concise_finalization` | Structured, combined, concise (`true`, `false`, `true`) in all seven. | Make these the sole live terminal interface. Remove the booleans once old protocols leave the live selector. The older echo/`REPORT_SPEC_BLOCKER` command path is a subsequent deletion; keep shared blocker types/validation in `spec_blocker.py`. |
| `exact_text_edit`, `whole_file_write`, `plain_tool_observations` | All true in all seven. | Treat edit, write and literal bounded output as ordinary supported tools/format, not opt-ins. Tool interfaces can still evolve prospectively. Preserve exact-match checks and command/file limits. |
| `work_policy_feedback`, `time_budget_feedback`, `workspace_persistence_feedback` | All true in all seven. | Always describe the actual work environment and budgets. Derive persistence wording from the scratch policy. There is no useful current need to omit this information. |
| `contract_first_checks`, `evidence_audit_feedback`, `self_test_feedback`, `patch_edit_feedback`, `terminal_semantics_feedback` | Absent/false in all seven. | Retire alternate procedural prompt paragraphs from current code. The [checks-first screen](../results/reliability-120-contract-first-consolidation-001.json), freeze 132, did not establish a benefit. Existing task requirements and ordinary final checks remain. Avoid recreating a switch for every future wording edit. |
| `max_tool_calls_per_response`, `max_command_bytes` | Eight and 32768 in all seven. | Keep named implementation limits, remove routine per-recipe variation unless a concrete model experiment needs it. Eight is a ceiling, not advice to fill every batch. No claim that eight universally beats one. |
| `recover_tool_limit_errors` | True in all seven; structured parsing already rejects oversized/invalid batches with `FormatError`. | Remove this legacy parser choice together with the bash-only terminal path. Correctable errors within the original budget should be invariant. |

The evidence for the common interface is the selected recipe bundle and its
repeated use, not an isolated causal estimate for each switch. The
[tool-interface review](../results/tool-interface-iteration-review-001.json) also
distinguishes schema correctness fixes from unsupported quality claims.

## Dormant mechanisms that need no live branch

| Mechanism | Suggested disposition | Replay/basis |
|---|---|---|
| `review_reasoning_only`; first-submission reset/review; `announce_review` | Retire from the current runner after the two easy deletions. Preserve ordinary terminal submission and pressure recovery. | [Freeze 129](../results/reliability-120-qwen27-phase-review-consolidation-001.json): 1/2 full, no established review benefit; [130](../results/reliability-120-qwen27-phase-xhigh-consolidation-001.json): 0/2, set aside. `inference_phase.py` and submission-review plumbing are in the Git commit above. |
| Elapsed one-shot reset, `continuation_mode=review`, summary-free reset | Archive implementation choices; current longer recipes use repeated headroom-triggered summaries and `continue`. | No current selected recipe needs these variants. Keep history publication, observation identity and original-budget invariants when simplifying `fresh_context.py`. |
| `progress_reminder` | Archive its 170-line implementation unless a new pacing experiment is actually planned. | [Freeze 87 review](../results/compact-progress-reminder-consolidation-001.json) explicitly did not establish earlier implementation as a benefit. None of the selected recipes enables it. |
| `context_policy.mode=mask/recoverable`; `context_budget_feedback` | Use measured unmasked history plus pressure summaries in the current runner; historical masking can live in Git. | All seven use mode `none` and no one-shot budget notice. Remove masking logic, not `ObservationHistory`, which current finalization/checkpoints need. `keep_recent`/`trigger_tokens` are inert in mode `none`; `safety_tokens` remains live. This does not settle whether masking would help at future scales. |
| `require_tool_call` | Keep false in current recipes; archive forced-decoding experiment rather than advertise a general reliability fix. | This is backend `tool_choice=required`, distinct from the existing rule that valid responses contain tools. [Freeze 159](../results/required-tool-call-analysis-001.json) improved a tiny model-specific screen from 0/4 to 2/4, without promotion. It is not semantically redundant, and could be reinstated for a specific backend/model hypothesis. |

## Keep these real choices

- **Reasoning, context capacity and budgets:** model/task-specific. Freeze 288 is
  actively comparing 4096 versus 2048 reasoning tokens. Preserve native-cap
  presence/absence, deadline-aware allocation, context size, headroom/reset bounds,
  original task/call/token ceilings and backend sampling. Do not infer a universal
  cap from the successful known-seed diagnostic.
- **Initial repository preload:** a real context/cost trade-off. Its all-or-nothing
  max-file/max-byte limits can omit a repository; a cap change is behavioral.
  [Current diagnostics](../results/workflow-efficiency-diagnostics-001.json) retain
  both a faster incorrect preload result and a successful reasoning result.
- **`persistent_scratch` and `shared_evidence`:** keep experimental until their live
  probes establish usefulness and costs. Scratch changes state semantics; shared
  evidence changes checkpoint schema/resumption context. Their unit/isolation tests
  are not model-quality evidence.
- **`spec_blocker_exit`:** do not simply delete it as a duplicate terminal switch.
  It still gates contract-triage admission and outer reporting. Separate the live
  admission/scoring policy from the obsolete bash blocker syntax. Keep
  `open_problem_policy` configurable as the user requested; this is a policy choice,
  not a formatting option.
- **Evaluation/runtime capabilities:** behavioral verification and public test
  libraries remain task/runtime choices. Hypothesis is common to current recipes,
  but need not become mandatory for every future language/task. Isolation, cleanup
  and independent evaluator boundaries are invariants, not convenience flags.
- **Weight checks/warm-up:** metadata versus full hashing expresses an assurance
  trade-off. Prefix warming is the accepted timing convention where supported, but
  actual cache-match/reuse verification and separate cold cost remain necessary.

## Small configuration repairs worth landing with retirement

1. Stop defaulting launch commands to legacy `mvp`; require an explicit current
   recipe, or select a documented task recipe. `protocols()` currently exposes
   every filename as an equally live CLI choice. Cull retired definitions from
   that selector/tree; Git and freeze pointers provide historical access.
2. Reject retired option names in the current loader with a clear historical-replay
   message. Silently ignoring a formerly meaningful key is worse than removing it.
   Validate `time_budget_feedback` and `recover_tool_limit_errors` as booleans while
   they exist; both currently bypass the central boolean-validation loop.
3. Display effective capabilities rather than raw booleans: scratch overrides
   persistence guidance; split mode ignores concise/terminal prose flags;
   `shared_evidence` adds no checkpoint surface on a task without summary recovery.
   These interactions otherwise make configurations look more distinct than they are.
4. Avoid a new inheritance/compatibility framework. After deleting dead branches,
   assess whether remaining repetitive numbers justify a small authoring helper.
   Always freeze the fully materialized configuration and rendered prompt/tools.

This survey recommends current-scope retirement, not destruction of evidence or a
permanent verdict on every research idea. A concrete future hypothesis can recover
an old implementation from Git without carrying its cognitive cost in every run.
