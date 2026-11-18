# Ordering opaque records

Implement `order_records(records, compare)` in `ordering.py`. `records` is a
Python list of opaque object references; `compare(a, b)` returns a negative,
zero, or positive integer according to a consistent total preorder.

Return a new list containing exactly the original object occurrences in
nondecreasing order, stable among records that compare equal. Leave the input
list unchanged. Empty and singleton lists are valid. Propagate exceptions from
`compare`. Callers supply valid lists and consistent comparison callbacks.

Opaque records have no accessible key representation. Your algorithm may copy,
store and rearrange references, but may learn their order only by calling
`compare`. It may not inspect attributes, type names, string representations,
object identities or hashes to infer order. General comparison-based library
sorting is permitted if it satisfies the complete contract.

The service contract requires worst-case O(n log(n + 1)) total work for every input
length n and every valid ordering of the input, with O(n) auxiliary space.
Use the standard sequential unit-cost comparison/RAM model: each comparison,
reference read/write and index operation costs one unit. Machine words have
O(log(n + 2)) bits, enough to address the input. The
asymptotic requirement ranges over unbounded n; it is not merely a claim about
inputs that fit this workstation. There is no promise that inputs are partially
sorted or have a bounded set of keys. Randomization, preprocessing depending on
the input, and cached results from earlier calls cannot relax the worst-case
requirement.

You may edit ordering.py and add tests. Public tests are examples, not a proof
of the complexity requirement. No third-party packages are needed.
