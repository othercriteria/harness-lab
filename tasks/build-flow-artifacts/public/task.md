# Complete buildflow with generated inputs and verified output artifacts

This rough Python package needs a deterministic incremental build runner. Complete
its validation, planning, execution, cache receipts and CLI, including generated
file dependencies and output-content verification. Keep the existing public
functions/signatures and package entry point. Standard library only. Add focused
public regressions and run `python -m unittest discover -s tests`.

## Specifications

A spec has exactly `version` (integer 1, never bool) and `steps` (list). A step has
required `id`, `command` and optional `deps`, `inputs`, `outputs`; no other keys.
IDs match `[A-Za-z][A-Za-z0-9_-]*` and are unique. Commands are nonempty lists of
nonempty strings, executed without a shell. Dependencies are lists of unique known
IDs. All cycles and self-dependencies are invalid, including unselected graph parts.
Inputs/outputs are lists of unique safe relative POSIX paths: reject absolute
paths, backslashes, NUL, empty names/segments, `.` and `..` segments. Missing lists
default to empty. `parse_spec(data)` returns detached dictionaries keyed by ID,
with exactly id/command/deps/inputs/outputs; sort deps/inputs/outputs. Invalid data
raises ValueError. `load_spec(path)` reads UTF-8 JSON. Never mutate caller objects.

Every output has exactly one producer. Reject duplicate output ownership and
ancestor/descendant output paths (all artifacts are files). An input equal to a
declared output is generated; its producer must be a strict transitive prerequisite
of its consumer. Self/unrelated producers are invalid. Reject prefix conflicts
between ordinary source inputs and outputs (e.g. source `a` and output `a/b`).
Validate these rules globally, even for unselected steps. Dependencies that only
impose ordering are allowed; not every dependency needs to supply an input.

## State and fingerprints

New state is exactly `{"version":2,"completed":{ID:{"fingerprint":SHA256,
"outputs":{PATH:SHA256}}}}`. Versions are integers, never bool. Hashes are exactly
64 lowercase hex characters; IDs and output paths follow the syntax above.
Reject extra/missing fields and invalid types. Unknown-but-valid old IDs and paths
are allowed; state schema validation does not require a current spec or files.
`validate_state` returns a deep copy. Accept valid legacy state exactly
`{"version":1,"completed":{ID:SHA256}}` as a **cold cache**, normalizing it to empty
version 2. Validate legacy entries before discarding them. Missing state loads as
empty v2; malformed JSON/schema raises ValueError. Propagate other I/O errors.
Validate previous state even for an empty selection. None previous means empty v2.

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
with no targets. Filesystem validation is restricted to selected steps.

Before any callback in `run`, validate all selected ordinary source files and their
readability, and all existing path components of selected inputs/outputs. Reject
symlinks anywhere beneath root (even links staying inside root), non-directory
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

`save_state(path, state)` validates/normalizes before touching disk, writes UTF-8
JSON to a sibling temporary file, closes it, and publishes through the supplied
`buildflow.state.replace_file(source, destination)` hook. The hook is required for
auditing/fault injection. On write/publication failure propagate, preserve old
bytes and remove temporary files. Parent directories must already exist.

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
