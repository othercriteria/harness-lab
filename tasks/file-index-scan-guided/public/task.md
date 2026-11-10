# Complete safe incremental scanning for the file index

This repository indexes regular files beneath a directory into a JSON catalog.
Catalog validation, comparison, atomic persistence and the CLI are already
implemented and supplied as working support modules. Complete
`fileindex/scanner.py` for safe incremental scanning. Reuse
`fileindex.catalog.validate` to validate a supplied previous catalog.
Keep these public APIs: `fileindex.scanner.scan_tree(root, previous=None)`,
`fileindex.catalog.load_catalog(path)`, `save_catalog(path, catalog)`,
`diff_catalogs(old, new)`, and `fileindex.cli.main(argv=None)`.

Start by validating the root and previous catalog. Walk the stable tree without
following symlinks, collect metadata for regular files, and reuse a prior digest
only when both metadata fields match. Hash other files in bounded chunks and
return entries in sorted relative-path order. The contract below also describes
the supplied modules, whose behavior must be preserved.

Catalog format is exactly `{"version": 1, "files": {...}}`. File keys are relative
POSIX paths. Each value contains exactly integer `size`, integer `mtime_ns`, and
lowercase hex SHA-256 string `sha256`. Treat stat values as metadata, not content.

Scanner:
- Validate that root exists and is a real directory, rejecting a symlink root.
  Recursively index regular files, including dotfiles and empty files, in sorted
  relative-path order. Skip symlink files AND symlink directories, even when their
  targets are inside the tree. Never follow those entries. Ignore other non-regular
  entries. The root itself means its final path component; symlinks in ancestor
  components outside the supplied root are allowed.
- Hash binary bytes in chunks of at most 64 KiB; never read an entire file at once.
  Reuse a previous digest only when that same relative path has equal size AND
  mtime_ns. Do not open reused files. Changes to either metadata field force a
  new hash; same-size edits must be noticed when mtime changes. Do not mutate
  `previous`. Missing previous paths disappear from the new catalog.
- File I/O errors must propagate; do not silently omit unreadable files. Assume
  the directory tree is stable during each scan; concurrent mutation is out of scope.
- Return a catalog satisfying the schema below. If a regular file has a relative
  path or stat metadata that cannot be represented in that schema (for example a
  backslash-containing name or a negative mtime_ns), raise ValueError for the scan.

Catalogs:
- `load_catalog` returns an empty version-1 catalog for a missing path only.
  Malformed JSON or invalid schema raises ValueError. Reject extra/missing keys,
  bools masquerading as ints, negative sizes/mtimes, unsupported versions, unsafe
  paths (absolute, empty, '.', '..', empty segments, or backslashes), and digests
  other than exactly 64 lowercase hexadecimal characters. Validate previous
  catalogs provided directly to scan_tree and both inputs to diff_catalogs too.
- `diff_catalogs` returns exactly `added`, `removed`, `changed`, each a sorted
  list of paths. Shared paths are changed iff their DIGEST differs; metadata-only
  changes do not count. Do not mutate either input.
- `save_catalog` validates before touching disk and writes UTF-8 JSON atomically
  via a temporary sibling and os.replace. If serialization/write/replace fails,
  preserve the old catalog bytes and remove the temporary file. Parent directories
  must already exist. Callers store the catalog outside the indexed tree.

CLI: `python -m fileindex ROOT CATALOG [--dry-run]`
Load previous, scan, compute diff. On success print the diff as one JSON line and
return 0; persist the new catalog unless --dry-run. Dry-run must not create or
modify the catalog. On OSError/ValueError print one nonempty diagnostic to stderr
(no traceback), leave stdout empty, return 2, and preserve any old catalog bytes.
The CLI must not report success before a required catalog save has succeeded.

Only standard library dependencies. Use the supplied tests as executable contract
examples. One or two focused regressions for valid inputs affected by your repair
are sufficient; derive expected results from the contract. Run
`python -m unittest discover -s tests`. Preserve the package entry point.
