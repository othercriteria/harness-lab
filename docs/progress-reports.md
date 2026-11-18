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

## Inspecting saved trials

Run `python scripts/progress_inspect.py /path/to/saved/trial` (or supply any trial
folder). The standard-library CLI prints one JSON object to stdout. It reads
only immediate entries named `context-checkpoint-NNN.json`, where NNN is at
least three ASCII digits, and orders them by numeric sequence, then filename.
Request/response/repair metadata and other filenames are ignored. It does not
infer missing sequence numbers. Accepted-record identity comes from the
filename convention; the tool does not independently authenticate acceptance.
Trace strings are parsed as data, never executed or imported. Symlinks and
nonregular checkpoint entries are diagnosed rather than followed.

`counts` separates candidate checkpoint files, usable reports, missing progress
fields, malformed records, malformed reports, and unreadable files. Every
candidate is either a usable report or one of these four diagnostic categories.
`report_files` gives usable reports' filenames in summary order; `diagnostics`
names excluded files and reasons. A present null progress value is malformed,
not absent. An empty folder has zero counts and a `no_checkpoints` diagnostic.
`summary` is the unchanged `progress_summary.summarize` result over usable
reports only. Consequently adjacency and latest refer to usable reports;
missing/bad records can hide intervening changes. Absence is never counted as
`unchanged` or other evidence of no progress.

The inspector checks the seven-field shape, enums, text and list limits, and
4096-byte report bound. Text follows the shared bounded-text contract: LF and
TAB are allowed within nonblank text; other characters below U+0020 are
rejected, while DEL (U+007F) is allowed. Evidence must be an array of objects, but citation
schemas and historical references are **not validated or resolved**: their
supporting modules/history are not part of this standalone inspection interface.
This is not a replacement for the reference validator. Duplicate JSON keys,
nonfinite constants, invalid UTF-8, and non-object records are diagnosed.

Exit status is 0 for complete inspection (including an empty folder), 1 when
any candidate was excluded, and 2 for an inaccessible/invalid directory (a JSON
`error` on stdout). Argument usage errors also exit 2, using argparse's stderr
message. Partial summaries remain available on stdout with status 1.
Counts describe **unverified model claims** and establish neither completion
nor futility. Even zero remaining items and passing check claims require
independent review.

Verify with `python -m unittest discover -s tests -p 'test_progress_*.py'` and
`python scripts/progress_inspect.py /path/to/saved/trial`.
