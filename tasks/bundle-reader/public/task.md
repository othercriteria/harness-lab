# Inspect and extract a bounded ZIP bundle

Implement `bundle_reader.py` using only the Python standard library. This is a
small archive-ingestion component: inspect a ZIP supplied as bytes, then optionally
extract the same contents into a new destination directory. Preserve the public
functions, immutable result classes, and exception class in the starter.

`inspect_bundle(data, *, max_files=128, max_file_bytes=1048576,
max_total_bytes=4194304)` returns a `BundleInfo`.
`extract_bundle(data, destination, *, ...)` accepts the same three limits, writes
the validated contents, and returns the identical `BundleInfo` value.

The contract is:

1. `data` is exactly `bytes`. Each limit is a strictly positive `int`, excluding
   `bool`. Reject invalid argument types or limits with `BundleError`. Accept ZIP
   archives with stored or deflated entries, including empty archives. Reject
   other compression methods, encryption, malformed ZIPs, and unreadable/corrupt
   entry contents with `BundleError`. An archive comment is allowed. Structural
   acceptance follows Python 3.13 `zipfile.ZipFile` parsing and entry-header checks;
   prefix/trailing archive bytes and ZIP64 forms that it accepts are permitted.
   For each stored/deflated payload, require that its complete decoded byte length
   and CRC-32 match the central-directory metadata. A deflated payload must finish
   its stream and have no bytes left over within its declared compressed span.
   Independent validation of other redundant ZIP metadata is not required.
2. Names are case-sensitive POSIX relative paths. A file name has no trailing `/`;
   a directory name has exactly one trailing `/`. Remove that directory suffix
   only when producing the canonical path. Reject empty paths, a leading `/`,
   backslashes, NUL characters, empty components, `.` or `..` components, and a
   colon in any component. Do not trim whitespace, case-fold, or otherwise
   normalize names; Unicode and spaces are valid. Apply these rules to the ZIP
   entry's `ZipInfo.orig_filename`, before NUL truncation or other sanitization.
   Alternative Unicode-path extra fields do not override that name.
3. Reject duplicate explicit canonical paths, even if two directory entries are
   otherwise identical. Also reject any file/directory collision, including a
   file that would have to be a parent of another entry. An implicit parent
   directory may also appear once as an explicit directory. Every entry whose
   name ends in `/` must have empty uncompressed contents.
4. Interpret Unix type bits as `stat.S_IFMT(info.external_attr >> 16)`. Zero type
   bits mean unspecified and are allowed. Otherwise only regular files and
   directories are allowed, and their type must agree with the trailing-slash
   convention. In particular, reject symlinks and special files. Permission bits,
   timestamps, and archive entry order do not affect the result or extraction.
5. Count regular file entries against `max_files`. Check each uncompressed file's
   actual bytes against `max_file_bytes`, and their sum against `max_total_bytes`.
   Limits are inclusive. Directories do not consume those limits. Validate and
   read every entry, including directories, before extraction creates anything.
   This component need not implement compression-ratio or CPU-time limits.
6. `BundleInfo.files` is a tuple of `FileRecord(path, size, sha256)` sorted by
   canonical path using Python string order. Each record contains byte length and
   lowercase SHA-256 hex digest of the exact uncompressed file bytes.
   `BundleInfo.directories` is a sorted tuple of all explicit and implicit
   directory paths, without trailing slashes. Include empty explicit directories.
   `total_bytes` is the sum of regular file sizes. The destination root itself is
   not listed. An empty archive returns empty tuples and total zero.
7. For extraction, `destination` is a `pathlib.Path` or `str`. Its parent already
   exists and is a trusted directory. Correctly typed path values are nonempty,
   contain no NUL, and are usable host filesystem paths; violations of these path-
   value preconditions are outside scope. Reject an already existing destination,
   including an empty directory or dangling symlink, with `BundleError` and leave
   it untouched. Invalid archives, limits, or destination argument types must
   leave an initially absent destination absent. On success create the root and
   all directories, and write exactly the file bytes; create no links and do not
   restore archive permissions. There are no concurrent filesystem changes and
   no symlink ancestors in the trusted parent path. Filesystem I/O failures such
   as permission errors or disk exhaustion may propagate as `OSError`; rollback
   after such failures is outside scope. This is validation-before-write, not a
   crash-atomic filesystem transaction.

Do not change the supplied public tests. Add focused regression tests and run
`python -m unittest discover -s tests`. No third-party packages or command-line
archive programs are available. Exception text is not part of the API. Unsupported
input types and archive features are rejected as stated above; nested archive
contents are ordinary opaque file bytes.
