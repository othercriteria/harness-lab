# Compare two work-log snapshots

`tabreport` is a working standard-library package that reads CSV work logs and
reports time by team. Add a snapshot comparison feature so a user can see which
items were added, removed or changed between two exports. Preserve existing
reporting APIs and command-line behavior; the supplied tests cover those features.

Implement `compare_records`, `render_diff` and `main` in `tabreport.diff` and export
`compare_records` and `render_diff` from the package. You may reorganize code or add
modules. Keep supplied tests unchanged, add focused regression tests for the new
feature, and run `python -m unittest discover -s tests` before submitting.

## Comparison API

`compare_records(before, after)` accepts two finite iterables of existing
`tabreport.model.Record` objects. Each iterable may be consumable only once. Records
already have valid labels, nonnegative integer minutes and `open`/`done` status;
you do not need to validate their types. Do not modify input records or containers.

An item's identity is its exact `(team, item)` pair, case-sensitive. Reject duplicate
identities within either snapshot with `ValueError`, even if their values are equal.
The same identity appearing once in each snapshot is normal. Do not merge differently
cased labels. Changes to a team or item label are a removal and an addition.

Return a new list of dictionaries, one per added, removed or modified identity.
An identity present in both snapshots is unchanged when both minutes and status
are equal; omit it. A change to either field makes it `modified`. Every dictionary
has exactly these eight keys:

* `team`, `item`: the original identity strings.
* `kind`: `added`, `removed` or `modified`.
* `before_minutes`, `after_minutes`: the respective integer minutes, or `None` if
  that side is absent.
* `before_status`, `after_status`: the respective status string, or `None` if that
  side is absent.
* `delta_minutes`: after minus before, treating an absent side as zero.

Sort the result by `(team.casefold(), team, item.casefold(), item)`, ascending.
An empty comparison returns `[]`. Zero minutes is a real value, not an absent side.

## Rendering API

`render_diff(changes, *, format="json")` accepts a finite iterable of dictionaries
with the shape above and returns a string. Preserve the supplied order; do not
mutate the dictionaries. No validation of their contents is needed. Reject formats
other than `json` and `csv` with `ValueError`.

For JSON, return a JSON array containing those dictionaries, followed by exactly
one final newline. Whitespace, key order and Unicode escaping inside the JSON are
unconstrained. Preserve integers and nulls as JSON integers and nulls.

For CSV, use this header order, followed by the corresponding values:
`team,item,kind,before_minutes,after_minutes,before_status,after_status,delta_minutes`.
Represent absent values as empty cells and numbers as decimal integers. Use standard
CSV quoting so commas, quotes and embedded newlines in labels round-trip. Each CSV
record must end in LF (`\n`); embedded newlines in cell values remain part of those
values. An empty comparison still emits the header. No summary or totals row.

## Command line

Add `python -m tabreport.diff BEFORE AFTER [--format json|csv] [--output PATH]`.
The default format is JSON. Each input is a UTF-8 CSV in the existing work-log
format; reuse the existing reader, including its duration parsing and diagnostics.
One input may be `-` to read from stdin. Reject two `-` inputs with a nonempty
stderr diagnostic and exit 2.

Expose `main(argv=None, *, stdin=None, stdout=None, stderr=None) -> int`, following
the existing CLI's optional stream convention. Report data goes to stdout unless
`--output` is supplied, in which case write UTF-8 to that path and leave stdout
empty. Successful runs return/exit 0. Read/parse/comparison errors return/exit 2,
write a nonempty diagnostic to stderr and leave stdout and any existing output
file unchanged. Construct the complete report before opening an output file for
writing. Output-write errors also return/exit 2 with a nonempty diagnostic; atomic
replacement or rollback after a partial write is not required. Caller-supplied
streams stay open. Ordinary argument-syntax errors may use argparse's standard
behavior. No persistent service, new dependencies or network access is needed.

For example, changing `A,task,10,open` to `A,task,10,done` produces one `modified`
row with `delta_minutes` 0; deleting an item with 0 minutes still produces a
`removed` row with `after_minutes`/`after_status` null.
