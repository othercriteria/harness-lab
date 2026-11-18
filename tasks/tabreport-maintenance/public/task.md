# Maintain tabreport

`tabreport` is a small, standard-library Python utility for summarizing CSV work
logs. Most of it already works. Implement the six maintenance changes below while
preserving its other documented behavior and public APIs. You may edit or rewrite
modules as needed; correctness is behavioral, not based on diff size or edit style.
Do not add third-party dependencies.

Run the CLI from this directory with `python -m tabreport INPUT.csv`, or use `-`
for stdin. Existing options are `--output PATH`, `--format text|markdown|csv`,
`--team LABEL`, `--status open|done`, `--sort team`, and `--no-total`.
Run public checks with `python -m unittest discover -s tests -v`.

## Requested changes

1. **Whitespace-only data rows** — In `tabreport/csvio.py`, `read_records` must
   skip a parsed CSV data row when every field is empty after `str.strip()`, even
   when its field count is not four. Do this after the header has been read and
   before data-row validation. Ordinary empty physical lines remain ignored.
   Do not extend this rule to selecting the header: the first nonempty parsed
   row must still be a valid header. Partially empty data rows remain errors.

2. **Hours and minutes** — Extend `csvio.parse_minutes` to accept `H:MM` as well
   as its existing ASCII nonnegative integer form. `H` is one or more ASCII digits
   (leading zeros allowed); `MM` is exactly two ASCII digits from `00` through
   `59`. Return `60 * H + MM`. Strip outer whitespace, but reject internal
   whitespace, signs, non-ASCII digits, extra colons and malformed minutes with
   `ValueError`. CSV input must use the same conversion. Examples: `" 2:05 "`
   becomes `125`, `"00:09"` becomes `9`, and `"2:5"` is invalid.

3. **Case-insensitive selection** — In `tabreport/model.py`, `select_records`
   must compare a supplied team filter using `str.casefold()` on both labels.
   Do not strip the filter argument, change the stored labels, combine differently
   spelled groups, reorder records or change status filtering. For example,
   `Straße` matches `STRASSE`; `Ops` and `ops` remain distinct summary groups.
   Update the CLI's team-option help to describe this behavior.

4. **Sort by effort** — Add `summarize(..., sort_by="minutes")` and CLI
   `--sort minutes` in `tabreport/cli.py`. Sort groups by aggregate minutes,
   descending; ties use `(team.casefold(), team)` ascending. The default
   `sort_by="team"` ordering is unchanged. Other sort values remain invalid.
   The total row, when requested, still follows all groups rather than taking
   part in sorting.

5. **Markdown cells** — Implement escaping in `tabreport/render.py`'s
   `_markdown_cell`: double each original backslash, escape each pipe by
   prefixing one backslash, normalize CRLF and lone CR to LF, then replace each
   LF with the literal text `<br>`. Generated escape backslashes must not be
   doubled again. All other characters remain unchanged. Apply this only to
   Markdown cells; preserve the existing header, alignment row and final LF.
   Plain text keeps its existing newline-to-space behavior; CSV does not apply
   Markdown escaping.

6. **CSV report terminators** — In `render.render_csv`, emit LF rather than
   CRLF record terminators, including the header and final record. Use the
   standard `csv.writer` dialect/settings with only `lineterminator="\n"`
   changed; do not normalize cell contents. This also applies with
   `include_total=False`. `csvio.write_records` already uses LF and is unchanged.

## Compatibility to preserve

- Public dataclasses, function names, keyword parameters and imports in
  `tabreport/__init__.py` remain available. Records and summaries are immutable;
  selection/aggregation/rendering accept iterables and do not mutate them.
  Directly constructed records are assumed valid; CSV validation belongs to
  `read_records`.
- Input has exactly the columns `team,item,minutes,status`, in any order. Header
  names and data fields are stripped. Duplicate, missing or unknown columns,
  wrong data-row field counts, empty team/item, CSV syntax errors reported by
  `csv.reader` with its standard dialect and `strict=True`, and statuses other
  than exact `open` or `done` are errors. `RowError` remains a `ValueError` with
  `.line` and `.detail`; its line uses `csv.reader.line_num`, including physical
  lines consumed by quoted multiline fields. Error wording need not be identical.
  Empty input is an error; a header without records is valid. Caller-owned
  streams remain open.
- Group by exact team label and count rows, total minutes, done and open. Default
  group order is `(team.casefold(), team)`. `completion_percent` is whole percent
  rounded down, or zero for an empty summary. Render columns remain Team, Rows,
  Minutes, Done, Open (lowercase in CSV). Renderers preserve supplied group order.
  A separate `TOTAL` row is appended by default, including for an empty report;
  a real team called `TOTAL` remains an ordinary group. `--no-total` omits only
  the appended row.
- Preserve text alignment, Markdown layout, CSV field quoting under the dialect
  specified above, UTF-8 file input/output, stdin/stdout support and CLI options.
  Valid CLI runs return 0. Data/I/O errors return 2 and print an `error:`
  diagnostic to stderr. Finish input validation and report construction before
  writing stdout, so failures in those stages emit no partial report. A failed
  output-stream write may already have emitted a prefix; rollback is not required.
  Invalid CLI arguments retain argparse's ordinary exit behavior. Successful `--output` writes to the file
  instead of stdout.

`tests/test_compatibility.py` checks existing behavior and should pass before
maintenance. `tests/test_requested_changes.py` describes the requested additions
and is expected to fail on the starter. Both must pass when the work is complete.
