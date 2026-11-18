# Delegation artifact helpers: maintainer guide

`scripts/delegate_artifacts.py` and `scripts/bounded_diff.py` produce bounded,
reviewable artifacts for trusted outer delegation. Nothing in them imports
candidate code, runs a shell, reads Git metadata, or writes to a checkout. The
outer caller selects every input and writable path; a successful export is
data, not approval.

## Workflow

1. **Select inputs and allowed writes.** Both lists are explicit and bounded:
   nonempty, at most 2048 entries, no duplicates, relative paths of at most
   512 characters matching `[a-zA-Z0-9_./-]+` with no `.` or `..` parts.
   Path parts `.git`, `.aws`, `.ssh`, `.codex`, `.agents`, `.venv`,
   `__pycache__`, `private`, `reference`, `evaluation`, `results`, and anything
   starting `.env` are refused. `task.md` is reserved for the public job brief:
   it may never be an input or an allowed-write path.
2. **`create_snapshot(repo, names, writable, destination)`** copies exactly the
   selected files into `destination/public` and writes `snapshot.json`. The
   snapshot identity (`snapshot_id`) is the SHA-256 of the canonical contract,
   which covers per-file SHA-256 digests, executable bits, the base digest of
   every input, and the sorted allowed-write paths. Existing allowed-write
   files must already be selected inputs; a new file may not sit under a
   selected file. The destination must not exist.
3. **`export_candidate(snapshot, workspace, destination, brief=None)`**
   enumerates the finished sandbox workspace (never following symlinks) and
   compares it with the snapshot. It refuses changes to unapproved paths,
   executable-bit changes, and changed content that is non-UTF-8 or contains
   NUL bytes (text patches only; unchanged binary inputs may remain context). With `brief`, the workspace `task.md` must equal it
   byte-for-byte. It writes changed after-files under `files/`, a displayed
   `changes.diff`, and `artifact.json` with per-file before/after digests,
   `diff_sha256`, omission counts, `acceptance: pending_outer_review`, and
   `applied: false`.
4. **`check_application_base(snapshot, repo)`** re-reads every base path in
   the contract (all inputs and pending new files, not just edited files) and
   compares digest and executable bits. On success it returns
   `base_matches: true` plus a note that this is preflight only. It never
   modifies the checkout and is not an atomic application operation.

```python
from delegate_artifacts import create_snapshot, export_candidate, check_application_base

record = create_snapshot(repo, ["src/app.py", "src/lib.py"],
                         ["src/app.py", "tests/test_app.py"], "snapshots/job-1")
artifact = export_candidate("snapshots/job-1", workspace, "artifacts/job-1",
                            brief=b"public job brief\n")
ok = check_application_base("snapshots/job-1", repo)  # preflight only
```

## Identities and limits

Identities are content-based SHA-256 digests: per-file input digests, the
contract-derived `snapshot_id`, and `diff_sha256` over the rendered display
text. `diff_sha256` does **not** cover the complete change set; it covers only
what the display shows. Snapshot reads are bounded (16 MiB per file, 16 MiB
total, 2048 files) and re-stat the file after reading, refusing files that
change mid-read or are not regular single-link files.

## Disposable Python caches

`__pycache__` is a forbidden path part, so caches can never be selected inputs
or write paths. `export_candidate` skips `__pycache__` directories while
enumerating the workspace and refuses a cache symlink. The raw workspace keeps
caches for inspection; they simply never enter the artifact.

## Why the displayed diff is not the authoritative patch

`bounded_diff` uses one linear changed-span hunk per file instead of quadratic
sequence matching, so distant edits can yield larger, non-minimal hunks.
Per-file input (256 KiB combined), LF-count (8192 newline bytes per side), and total display
(1 MiB) limits produce manifest-backed omission notices rather than full hunks.
Complete files, per-file digests, and the `artifact.json` manifest remain the
source of truth.

### Reviewing separated edits in Observatory

Open **Diff & verification** on a delegated job. **Compact review diff** groups
edits with three lines of context and keeps their original file coordinates.
**Recorded diff** shows the stored representation. A mixed view labels the
presence of both kinds of hunk. To inspect the recorded text directly, select
`changes.diff` under **Raw artifacts**. The manifest's `diff_sha256` covers
that recorded artifact.

The trace preview reads up to 64 KiB. Refinement shares a budget of 65,536
old-line/new-line pairs across its files. Truncated previews and unrecognized
records keep their recorded text. The navigation replay fell from 130 lines
to 38, exposing three edits. The test-writing replay fell from 390 to 124.
Applying each displayed diff to its archived starter with Git reproduced the
submitted file byte for byte.

To rehearse the navigation case from this repository with Python 3.13 and Git:

```sh
python3 -S -m unittest tests.test_observe.ObservatoryTests.test_archived_navigation_diff_applies_to_the_same_bytes
```

## Three distinct activities

- **Validation/export** (`create_snapshot`, `export_candidate`): structural
  checks and artifact normalization. No acceptance decision.
- **Correctness review**: the outer reviewer's job, judging the complete
  files and manifest.
- **Applying a change**: a separate outer action. `check_application_base` is
  a preflight check only; nothing here applies, and `applied` stays `false`.
