# Complete the buildflow incremental execution engine

This Python package already has working specification parsing and state persistence.
Implement the remaining planner, runner and CLI integration for generated files
and content-verified caching. Start with `buildflow/planner.py`, `runner.py` and
`cli.py`; keep existing public signatures and the package entry point. Standard
library only. Add focused public regressions and run
`python -m unittest discover -s tests` before submitting.

## Provided modules and API boundaries

`buildflow/spec.py` and `buildflow/state.py` are complete implementations supplied
as part of this task. Reuse them; you do not need to rewrite their validation or
atomic persistence. The planner/runner scaffolds are incomplete, including their
return shapes. The CLI is wired but still needs correct result/error integration.

* `load_spec(path)` reads UTF-8 JSON and returns the **raw document**, shaped
  `{"version":1,"steps":[...]}`. Both `plan` and `run` accept this raw document.
* `parse_spec(raw_document)` validates the entire graph and returns a detached
  **mapping keyed by step ID**. Every value has exactly `id`, `command`, `deps`,
  `inputs`, `outputs`; the last three lists are sorted and default to empty.
  A normalized mapping is not valid input to `parse_spec` again.
* Parsing already checks exact schemas, ID/path syntax, dependencies/cycles,
  output ownership and prefix conflicts, and generated inputs' strict transitive
  producer dependencies. It does not select targets or inspect the filesystem.
* `validate_state(state)` validates and deep-copies a v2 state, or validates a v1
  state and returns empty v2 (legacy receipts are a cold cache). It does not check
  current graph membership, filesystem contents or cache validity.
* `load_state(path)` returns empty v2 only when the file is missing. It otherwise
  parses and validates the JSON; malformed data, including JSON null, is invalid.
* `save_state(path, state)` validates before touching disk and atomically publishes
  through `buildflow.state.replace_file`, preserving old bytes and cleaning the
  temporary file on failure. The parent directory must already exist.
* `previous=None` is an allowed sentinel **only for `plan` and `run`**, meaning
  empty v2. `validate_state(None)` and `save_state(path, None)` raise ValueError.
  Validate any supplied previous state even when the selected graph is empty.

Raw steps have required `id`/`command` and optional `deps`/`inputs`/`outputs`.
Commands are nonempty lists of nonempty strings, executed without a shell.
IDs match `[A-Za-z][A-Za-z0-9_-]*`. Paths are relative POSIX file paths without
backslashes, NUL, empty segments, `.` or `..`. Spec version is integer 1, not bool.
No extra keys are allowed. An input matching a declared output is generated;
its producer is a strict transitive prerequisite. Ordering-only dependencies are
allowed. Supplied source documents the complete validation contract.

State v2 is exactly `{"version":2,"completed":{ID:{"fingerprint":SHA256,
"outputs":{PATH:SHA256}}}}`. Hashes are 64 lowercase hex characters. Unknown but
syntactically valid old IDs/paths are allowed by state validation. Legacy state is
exactly `{"version":1,"completed":{ID:SHA256}}`. Never mutate caller objects.

## Fingerprints and verified receipts

A recipe fingerprint is SHA-256 of UTF-8 encoding of
`json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`.
Payload is exactly `{"id":ID,"command":COMMAND,"inputs":[[PATH,FILE_SHA],...],
"deps":[[DEP_ID,DEP_FINGERPRINT],...],"outputs":[PATH,...]}`; inputs/deps/outputs
are sorted by name. Hash actual binary source AND generated-input contents in
chunks <=64 KiB. Output content hashes belong in receipts, not recipe fingerprints.
Reuse requires a matching recipe fingerprint, the exact declared output-name set,
and all current output byte hashes matching the receipt. Timestamps are not keys.
An empty output list requires `{}` output evidence. Missing/tampered regular output
means a cache miss; unsafe existing paths are validation errors, not cache misses.

## Preflight and planning

`plan(spec, root, previous=None, targets=None)` is read-only. Root must be an existing
non-symlink directory. None targets selects all; a list selects those IDs plus their
transitive prerequisites; empty selects none; duplicates are allowed. Invalid type
or unknown/invalid IDs raise ValueError. Validate the entire spec and state even
with no targets. Filesystem validation is restricted to selected steps: inspect
the components of their declared input/output paths, not unrelated entries
elsewhere in the tree. Global graph/schema validation still includes unselected
steps.

Before any callback in `run`, validate all selected ordinary source files and their
readability, and all existing path components of selected inputs/outputs. Reject
symlinks in those path components (even links staying inside root), non-directory
intermediate components, and existing non-regular final paths. Missing ordinary
sources fail before any execution. Missing output paths/generated inputs are
allowed at preflight: their producers may create them later. Commands must create
output parent directories. Generated files are required/read only when their
prerequisites have succeeded or been accepted as cached. Propagate preflight file
I/O errors. Planning creates no files/directories.

Return selected steps in deterministic topological order, choosing the smallest
lexicographic ready ID each time. Rows have exactly `id`, `deps`, `command`,
`outputs`, `fingerprint`, `disposition`. If ALL prerequisites are proven cached,
resolve current inputs/fingerprint and use disposition `cached` or `run` according
to the receipt. Otherwise fingerprint is null and disposition is `deferred`;
do not read stale generated bytes to guess it. Thus an initial producer is `run`
and its consumer `deferred`. Deferred does not promise execution: after identical
regeneration the consumer may still reuse its receipt. All returned lists are detached.

## Execution and publication

`run(spec, root, execute, previous=None, targets=None, keep_going=False)` completes
preflight before callbacks. Traverse the same selected topological order. Dependency
statuses failed/blocked/not_run make a step blocked, before cache or stop decisions.
After a failure, unrelated steps are not_run unless keep_going=True. After all
prerequisites succeed or are cached, recompute this step's actual fingerprint and
reevaluate its receipt, even when a preview said deferred. Cached steps do not
execute. Otherwise call execute(ID, fresh_command_list). Integer 0 alone is
insufficient: every declared output must now be a safe readable regular file and
be hashed successfully. Nonzero or noninteger returns (including bool), Exceptions,
or missing/invalid post-command outputs make the step failed with a nonempty
diagnostic. Catch Exception, not BaseException. Input/hash errors encountered after
preflight likewise fail that step. A failed producer blocks its consumers.

Return exactly `order` (all selected IDs), `statuses` (ID to cached/succeeded/failed/
blocked/not_run), `errors` (failed IDs to diagnostics), `state` (v2). Retain receipts
only for known unselected IDs, then add selected receipts that were verified as
successful/cached. Drop removed IDs and stale receipts for failed/blocked/not_run
selected steps. Do not delete obsolete artifact files. Command-created files are
not rolled back on failure. No mutation of callback lists may alter caller inputs.

CLI: `python -m buildflow SPEC ROOT STATE [--target ID ...] [--dry-run] [--keep-going]`.
Run commands without a shell in ROOT; capture stdout/stderr so chatter never
contaminates CLI JSON. Actual runs persist partial state before printing one JSON
report line. Exit 0 if no step failed, 1 if any failed (including missing outputs
from a command exiting 0). Dry-run prints `{"plan":[...]}`, executes nothing and
never creates/modifies STATE. On ValueError/OSError from preflight/state/save emit
a nonempty stderr diagnostic, empty stdout and exit 2.

Assume deterministic commands, no concurrent filesystem changes, and commands do
not mutate sources or other steps' outputs. Incidental logs are not cache keys.
No remote cache, concurrency, artifact directories or arbitrary side-effect rollback.
