# Progress reports and checkpoint integration

## What a report is, and what it is not

A progress report is a bounded, model-authored set of unverified assertions plus historical citations. It names implemented work, claims about checks, and public requirements still unfinished or unverified. It is never a certification of correctness or a probability of finishing: semantic relevance, truth, and next-action concreteness remain outer review, not mechanical rejection rules. The module is data and validation only — no tool loop, file I/O, scheduling, or termination decisions.

## The seven fields

A report has exactly seven required fields (`additionalProperties: false`):

- **change** — one of `advanced`, `unchanged`, `regressed`, `uncertain`; task-relevant movement since the previous report, or task start for the first.
- **implemented** — 0–2 items: actual implementation changes, not test outcomes.
- **checks** — 0–2 entries of exactly `{result, summary}`: model claims about checks, not independently observed facts. `result` is `passing`, `failing`, `stale`, or `unknown`.
- **remaining** — 0–4 explicit public requirements still unfinished or unverified. Empty is allowed and does not establish completion.
- **obstacle** — a known obstacle; the empty string means none known (other whitespace-only values are invalid).
- **next_action** — one concrete next action; nonempty.
- **evidence** — citations using the existing observation / public-contract interface, the same references as final handoff. This reuses that interface; it is not a new evidence namespace, and a valid reference does not establish entailment, correctness, or freshness.

Implementation claims and check claims are deliberately separate: `implemented` describes what the model changed, while `checks` records how the model believes those changes fared, with `stale` and `unknown` as honest states after edits.

## Enabling `checkpoint_progress`

For an outer-registered delegated task, the job specification accepts one optional boolean, `checkpoint_progress` (default `false`). Setting it to `true` writes the flag into the delegated protocol limits. It requires a recipe whose limits enable shared evidence and a summary checkpoint (elapsed or context-headroom reset with structured tools); `checkpoint_progress` without shared evidence is rejected. Ordinary recipes are unchanged unless the flag is enabled.

In this mode `checkpoint_context` takes `summary` plus a required `progress` report. There is no parallel top-level `evidence` field; citations live in `progress.evidence`.

```json
{
  "summary": "Draft written; verification pending.",
  "progress": {
    "change": "advanced",
    "implemented": ["Added docs/progress-reports.md"],
    "checks": [{"result": "unknown", "summary": "Source cross-check pending"}],
    "remaining": ["Cross-check guide against supplied source"],
    "obstacle": "",
    "next_action": "Compare the guide with the supplied source and record gaps",
    "evidence": []
  }
}
```

Empty lists and `unknown`/`uncertain` values are valid. Cite only observation IDs actually available to a real attempt; an empty `evidence` list is fine.

## When reporting occurs

Reporting happens at the existing checkpoint opportunities — the summary checkpoint offered at the predeclared reset boundary. There is no periodic progress timer. An accepted checkpoint is written to a durable `context-checkpoint-NNN.json` record (sequence-numbered artifact) and preserved across reset: the continuation notice carries the checkpoint as unverified memory, not new task instructions or independent evidence, with rendered historical evidence when shared evidence is enabled.

Bounds: implementation items, check summaries, remaining items, obstacle, and next action are capped at 300 characters and 300 UTF-8 bytes each; evidence entries retain their own shared-interface limits; the whole progress payload is capped at 4096 UTF-8 bytes of serialized JSON, even when every field is within its own cap. The full checkpoint arguments are capped at 8192 bytes, and the summary alone at 4096 UTF-8 bytes.

## Accounting and non-effects

The report's cost is included in the checkpoint request's recorded time and tokens; marginal report cost is not separately measured. Checkpoint-only reports select for context-heavy runs; short runs may never produce one. Missing or malformed reporting is not evidence of stagnation: the normal one-repair/fallback behavior applies, and the existing time, token, and call budgets continue unchanged. Reports do not terminate work, allocate more resources, or implement futility stopping, and there is no calibrated percent-complete or finish-probability score. Nothing here claims measured improvements or runtime reliability from source inspection.
