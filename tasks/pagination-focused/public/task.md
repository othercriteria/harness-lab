# Make record pagination work with generators

`records.iter_records(fetch_page)` yields records from a paginated API. The
callback takes a cursor (initially `None`) and returns `Page(items, next_cursor)`.
Items can be any finite iterable, including a generator.

Preserve page and item order. An empty page can still have a successor. Only
`next_cursor is None` means completion; empty strings and zero are valid cursors.
Detect repeated request cursors and raise `ValueError` before fetching a cursor
for the second time. Cursors are hashable. Propagate callback exceptions without
retrying. Be lazy: constructing the iterator must not fetch anything, and the
next page must not be fetched until the current page's items have been consumed.
Consume each page's items lazily as records are requested, too.
Do not introduce external dependencies or change the public API.

Run `python -m unittest discover -s tests` after changes.

Use the supplied tests to check the repair. Keep the added suite small: one or two
focused regression tests of valid inputs affected by your repair are sufficient.
Derive their expected results from the contract.
