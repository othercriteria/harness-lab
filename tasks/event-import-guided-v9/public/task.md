# Make the event importer safe for repeated streaming imports

This small package records JSONL events in SQLite. Extend the existing public
`eventlog.importer.import_events(lines, store, *, strict=False)` API and CLI.
Keep the existing `EventStore(path)`, `.get(id)`, `.count()`, and `.close()` API.
Keep `.insert(event)` as the storage insertion boundary used by the importer;
it must return True for a new row and False for a duplicate. The current code
works only for a clean first import; it is the starting point.

Use a single transaction boundary for each import: protect iteration, storage
inserts and the final commit together, and roll back before propagating an
unexpected failure at any of those stages. A commit can fail even after all
inserts succeeded; the supplied example exercises this with a SQLite reader lock.
Keep SQLite journal_mode=DELETE, the starter default, for this task; alternative
journaling policies are outside scope. The supported transaction boundary is an
import call: caller-initiated transactions and pending direct .insert calls are
outside scope. `.insert` participates in the import transaction rather than
committing individual rows.
One straightforward Python implementation puts the final commit at the end of
the `try` body, directly after the loop, followed by the `except BaseException`
rollback handler. This makes a commit exception follow the same cleanup path as
an iteration or insert exception. Equivalent transaction structures are acceptable
when they protect the same failure paths and preserve the original exception.
When storage fails, preserve the original exception while restoring a clean
transaction boundary. SQLite may already have rolled back the transaction, for
example after SQLITE_FULL; cleanup should also handle that state. The supplied
bounded-page example exercises this with valid events and checks that previously
committed events survive and the store can accept another import.
Treat source interruption as a failed import too: when iteration raises
`KeyboardInterrupt` or `SystemExit`, unwind the transaction, propagate the original
exception, and leave the store ready for the next import. The supplied interruption
example raises these exceptions after yielding one valid event; it uses ordinary
Python exception propagation, not external process termination.

Required behavior:

- Read `lines` once as an iterable of text lines, without materializing it or
  seeking. Blank/whitespace lines are ignored but still count toward physical
  1-based line numbers. A nonblank line must decode to a JSON object with `id`
  a nonempty string after trimming. Store that trimmed id. `kind` is a required
  string; trim and lowercase it, rejecting empty results. `value` is a required
  integer (reject booleans); other input fields must be discarded. Stored `.get`
  values are dictionaries containing exactly `id`, `kind`, `value`, or None
  for a missing id. Normalization must not mutate the caller's dictionary.
- The first valid event with an id wins, across this call and previous imports.
  Even a later valid event with different contents is a duplicate, not an update.
  Validate all fields BEFORE duplicate classification. Persist successful imports
  across closing/reopening the database.
- Return a JSON-serializable dictionary with exactly `inserted`, `duplicates`,
  `invalid` integer counters and `errors`, an ordered list of dictionaries with
  integer `line` and nonempty string `message`. Counts concern this call only.
  Lenient mode skips malformed JSON/invalid events and continues, recording one
  error per invalid nonblank line. Do not treat unexpected iterator or storage
  failures as invalid data: roll back this call's inserts and propagate them.
- Strict mode raises `ImportFailure` on the first invalid nonblank line. Expose
  it from `eventlog.importer`, with `.line` and `.message` attributes matching
  the same error convention. Roll back ALL inserts from this call, preserving
  events committed by earlier calls. Success commits once for the whole call.
  A store must remain usable after either kind of failed call.
- CLI: `python -m eventlog DATABASE SOURCE [--strict]`. SOURCE `-` reads stdin;
  other sources are UTF-8 text files. Successful lenient/strict imports print
  the returned report as one JSON line to stdout and exit 0. Strict invalid input
  prints exactly one JSON object with `line` and `message` to stderr, leaves
  stdout empty and exits 2. A source that cannot be opened or raises OSError while being read exits 2
  with a nonempty stderr diagnostic, no traceback, and empty stdout. Close owned files and the store.
  The import API must not close its caller-owned iterable or store.
  Keep owned resources in cleanup scopes covering acquisition, the whole import,
  and reporting. Close each acquired resource on success, early returns, and
  unexpected exceptions, including a storage/commit failure during import.
  For example, a `finally` block or `contextlib.ExitStack` can arrange cleanup
  immediately after acquisition; keep borrowed stdin outside owned-file cleanup.
  Equivalent resource-management structures are acceptable. The supplied ownership
  examples cover acquisition failure and a SQLite reader lock that prevents commit.
  Database-open and storage-error exit status and diagnostic text remain
  unspecified; these examples check cleanup, not a new CLI error-reporting policy.

No external dependencies. Coordinate the parser, store, importer, and CLI rather
than bypassing the persistent store. Run
`python -m unittest discover -s tests`. Existing callers importing
`normalize_event` from `eventlog.model` must keep working.

Use the supplied tests as executable contract examples and the regression
deliverable for this task. Run the full supplied suite after your final edits.
Additional regression tests are optional; when a specific uncovered risk warrants
one, reuse the supplied fixtures and derive expectations from the contract.
