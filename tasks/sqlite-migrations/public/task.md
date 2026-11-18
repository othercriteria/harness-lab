# Make the SQLite migration runner safe to plan, resume and roll back

The migrator package discovers versioned SQL files and applies them to SQLite.
It currently has weak history checks and unsafe partial commits. Implement the
following behavior across discovery, planning, execution and CLI. Preserve public
function signatures and the Migration dataclass. Use only the standard library.
Add focused regressions and run `python -m unittest discover -s tests`.

`discover(directory)` returns Migration(version, name, sql, checksum) objects:
- Directory must exist, be a directory, and not itself be a symlink. Invalid
  roots raise ValueError or OSError. Discover only immediate children ending
  in `.sql`; ignore other names and do not recurse.
- Every `.sql` child must be a regular non-symlink file named
  `NNNN_slug.sql`: exactly four ASCII digits, then underscore, then a slug
  matching `[a-z][a-z0-9_]*`. Version is integer 1..9999, never zero. Duplicate
  numeric versions are invalid even with different slugs. Gaps are allowed.
- Read bytes as UTF-8, preserving the exact decoded text (including newlines).
  checksum is lowercase SHA-256 of those original bytes. Empty/whitespace-only
  text and NUL characters are invalid. Propagate I/O failures; invalid naming,
  duplication, content or UTF-8 raises ValueError (UnicodeError is acceptable).
- `validate_migrations(migrations)` requires a list of Migration objects with
  valid matching versions/names, nonempty SQL, no NUL, exact checksum of sql's
  UTF-8 bytes, and no duplicate versions. It returns a new list in numeric order.
  Bool versions are invalid. Neither discovery nor validation executes SQL.

`plan(connection, migrations, target=None)` is read-only:
- Validate the entire supplied list, including future migrations. Do not mutate
  inputs or connection configuration. Missing ledger means nothing is applied;
  do not create tables, commit, roll back or execute migration SQL when planning.
- Ledger table is `schema_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL,
  checksum TEXT NOT NULL)`. Read rows in numeric version order.
- Applied rows must be an exact prefix of the sorted supplied migration list:
  versions, names and checksums must all match. Reject missing files, renamed or
  edited applied files, unknown versions and skipped earlier migrations with
  ValueError. A valid gap in file versions (e.g. 1 then 3) is not a skipped file.
  Assume an existing ledger has the specified schema and no concurrent writer.
- None target means the highest supplied version (0 if empty). An explicit target
  must be integer 0 or an available version; reject bools, negatives and unknowns.
  A target below the highest applied version is an unsupported downgrade: ValueError.
- Return exactly `{"applied": [already applied versions], "pending": [selected
  unapplied versions through target], "target": effective_target}`.

`apply(connection, migrations, target=None)`:
- Reject an already-active caller transaction with ValueError before doing anything.
  Preserve the caller's uncommitted work and keep the connection open/configured.
- Validate/plan first. If nothing is pending, return `{"applied": [], "current":
  effective_target}` without any write or creation of an empty ledger.
- Apply the entire pending batch and ledger inserts in ONE transaction. Any SQL,
  statement-splitting, ledger-insertion or commit failure must roll back the whole
  new batch, including DDL and newly created ledger, while preserving prior commits.
  Propagate the original error and leave the connection out of a transaction.
- On success commit once and return `{"applied": [versions newly applied],
  "current": effective_target}`. Subsequent calls are idempotent.
- The provided `split_sql(sql)` handles complete statements, quoted semicolons,
  comments and trigger bodies. You may reuse it. Pending scripts with incomplete
  SQL or comment-only content raise ValueError. Complete statements must be
  executed without an implicit commit between migrations: Python's executescript
  can commit an already-open transaction, so take care.
- Scripts are trusted schema/data migrations and do not contain transaction-control,
  PRAGMA, ATTACH/DETACH, VACUUM, or direct ledger operations. Concurrent migration
  runners, malicious SQL, rollback/down migrations and schema repair are out of scope.

CLI: `python -m migrator DIRECTORY DATABASE [--target N] [--dry-run]`.
- Dry-run prints one JSON plan and exits 0. It must not execute migration SQL,
  create a missing DATABASE file, or modify an existing database (including ledger).
- Actual run prints one JSON apply result only after commit, exits 0 on success.
- On ValueError, OSError or sqlite3.Error, leave stdout empty, print one nonempty
  stderr diagnostic (no traceback), return 2. On failure, previously committed
  database contents must remain intact. A newly created but empty database file
  after a failed actual run is allowed. Close connections owned by the CLI.
- Do not create parent directories. Preserve the package entry point.
