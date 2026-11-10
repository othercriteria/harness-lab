# Make buildflow a safe incremental build runner

This small Python package runs named commands with dependencies. Implement deterministic
planning, dependency-aware reuse, failure handling, persisted receipts and CLI behavior.
Keep the existing public functions and signatures. Only the standard library is available.
Add focused public regressions and run `python -m unittest discover -s tests`.

Specification and validation:
- A spec has exactly `version` (integer 1, never bool) and `steps` (list).
- Each step has required `id`, `command`; optional `deps`, `inputs`; no other keys.
  IDs match `[A-Za-z][A-Za-z0-9_-]*` and are unique. Commands are nonempty lists
  of nonempty strings; do not interpret them as shell text.
- Dependencies are lists of unique known IDs; self-dependencies and all cycles
  are invalid, including in unselected parts of the graph. Inputs are lists of
  unique safe relative POSIX paths: reject absolute paths, backslashes, empty
  names/segments, `.` and `..` segments. Missing optional lists default to empty.
- `parse_spec(data)` returns detached step dictionaries keyed by ID, including
  id/command/deps/inputs, with deps and inputs sorted. Invalid data raises ValueError.
  `load_spec(path)` reads UTF-8 JSON. Never mutate caller-owned specs, state or targets.

State format is exactly `{"version": 1, "completed": {ID: SHA256, ...}}`.
Version must be an integer, not bool. Every key is a valid ID and every receipt is
exactly 64 lowercase hex characters. Unknown-but-valid IDs from old specs are allowed.
`validate_state` validates and returns a detached copy. `load_state` returns an empty
state only for a missing file; malformed JSON/schema raises ValueError. Do not swallow
other I/O errors. Validate previous state even for an empty plan.

`plan(spec, root, previous=None, targets=None)`:
- root must exist and be a directory, and must not itself be a symlink. Reject
  invalid roots with ValueError or OSError. None previous means empty state.
- None targets means all steps; a list selects those IDs plus their transitive
  prerequisites. Empty list means no steps. Unknown/invalid targets raise ValueError;
  duplicate target IDs are allowed. Validate the entire graph, even for no targets.
- Return one dictionary per selected step, in topological order. At each position
  choose the lexicographically smallest ID whose dependencies have already appeared.
  Each dictionary has exactly id, deps, command, fingerprint, cached.
- Hash only inputs of selected steps. Each must be a regular file; reject symlinks
  in any component beneath root (even links staying within root), directories and
  missing files. Propagate file I/O failures. Assume files remain stable during planning.
  Hash binary contents in chunks no larger than 64 KiB; the supplied digest_file
  already does this. Timestamps are not cache keys.
- Fingerprint is SHA-256 of UTF-8 encoding of
  `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`.
  payload is exactly `{"id": ID, "command": COMMAND, "inputs": [[PATH, FILE_SHA], ...],
  "deps": [[DEP_ID, DEP_FINGERPRINT], ...]}` with inputs/deps sorted by name.
  Thus changed input bytes, commands and prerequisite fingerprints invalidate dependents.
  `cached` is true exactly when previous.completed[ID] matches this fingerprint.

`run(spec, root, execute, previous=None, targets=None, keep_going=False)`:
- Finish validation and planning before calling execute, so a later bad input cannot
  cause partial execution. Call execute(ID, fresh_command_list) in plan order for
  uncached runnable steps. Cached steps do not execute. The callback returns a process
  exit code: integer 0 means success; nonzero, non-integer (including bool), or an
  Exception means failure. Catch Exception, not BaseException.
- A dependency with status failed, blocked or not_run makes its dependent blocked.
  Otherwise, after a failure with keep_going=False, remaining steps are not_run.
  With keep_going=True, continue independent steps. Apply dependency blocking before
  cache or stop decisions. Do not run or mark a blocked step cached.
- Return exactly `order` (all selected IDs), `statuses` (ID to cached/succeeded/failed/
  blocked/not_run), `errors` (failed IDs to nonempty diagnostic strings), and `state`.
- The new state retains old receipts only for known unselected IDs, then adds receipts
  for selected steps that actually succeeded or were accepted as cached. Drop stale
  selected receipts and unknown old IDs. Persisting this report enables partial-progress
  resume. No mutation of previous state or callback-owned lists may affect the plan.

`save_state(path, state)` validates before touching disk, writes UTF-8 JSON to a
sibling temporary file, closes it, and publishes via the supplied
`buildflow.state.replace_file(source, destination)` hook. This hook is a public
publication boundary and must be called; callers may replace it for auditing/fault
injection. If writing or publication fails, propagate the error, preserve old
file bytes and remove the temporary file. Parent directories must already exist.

CLI: `python -m buildflow SPEC ROOT STATE [--target ID ...] [--dry-run] [--keep-going]`.
Run commands without a shell in ROOT and capture their stdout/stderr so command
chatter never contaminates the CLI's JSON output. Actual runs persist partial state
before printing one JSON report line. Exit 0 if no step failed, 1 if any failed.
Dry-run prints `{"plan": [...]}`, executes nothing, and never creates/modifies STATE.
On ValueError/OSError (including save failure), emit a nonempty stderr diagnostic,
leave stdout empty and return 2. Dry-run and planning never modify ROOT.
Concurrency, environment-dependent command caching and filesystem changes during a
run are out of scope; tests use deterministic commands. Preserve the package entry point.
