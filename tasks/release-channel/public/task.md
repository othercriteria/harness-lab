# Select the current release

A release channel's index combines records from several exports. Repair
`currentRelease(records, channel)` in `current-release.cjs` so the result
is independent of input order.

Each record has a string `channel`, a nonnegative safe integer `build`, a
nonnegative safe integer `revision`, and a `state` of `published` or
`withdrawn`. Within a channel and build, the record with the greatest
revision determines its current state. Records tied on channel, build and
revision agree on state. A later publication can reinstate a withdrawn build.

Return the greatest currently published build number in the requested
channel, or `null` when none exists. Leave the input array and its records
unchanged. Inputs satisfy the contract. Keep the existing CommonJS export.
Change only `current-release.cjs`. Run the public tests with
`node tests/public.cjs`.
