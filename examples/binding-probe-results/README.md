# Which patch did the browser check?

A Footsteps user wanted to step through a transcript with the arrow keys. Worker
produced a patch. The Maintainer then preserved modified browser shortcuts and
tightened the tests before submitting the PR. Would a reader who had the browser
output be able to tell which patch was tested? [Footsteps PR #33](https://github.com/othercriteria/footsteps/pull/33)

Run this from the root of a clone with Python 3.13. It reads the packet and the
published review offline. It takes no GPU and executes no candidate code.

```sh
python3 -S examples/binding-probe-results/replay.py
```

| What the reader checks | Recovered Worker patch | Integrated PR patch |
| --- | --- | --- |
| First 12 digits of the artifact manifest's SHA-256 | `8154ea6783de` | `2d5b845e13f0` |
| Matches the manifest digest in the original Worker review | Yes | No |
| First 12 digits of the browser stdout's SHA-256 | `d2cd1aa23daf` | `d2cd1aa23daf` |
| Its own Lab receipt and Statement both match | Yes | Yes |
| Its receipts match the other candidate's manifest and patch | No | No |

The original review already identified the exact Worker artifact and browser
driver. It also named the two replays and recorded six observations from each.
Both the selected observations and the full archived stdout were identical.
The missing link was a record made at execution time naming the tested candidate
and the resulting output together. [Original review](../../results/footsteps-transfer-001.json)

## Browser observation v1

The subject is the exact bytes of `artifact.json`. Its `diff_sha256` identifies
the display patch, and the manifest also records the shared source snapshot and
the before and after file hashes. Both candidates were exported using the same
procedure. The integrated manifest is a fresh description of the PR changes.
The `pending_outer_review` field is an exporter default. The historical
Maintainer decision on the recovered Worker artifact lives in the original review.

For each invocation the Maintainer's capture records a producer label, finish
time, checkout revision, launcher arguments, verifier descriptor digest, process
exit code and SHA-256 of raw stdout. For Worker, the tested tree starts at the
checkout revision and includes the recovered edits. For the integrated candidate,
the checkout revision is the PR tip. [Worker receipt](packet/worker/receipt.json) · [Integrated receipt](packet/integrated/receipt.json)

The compact receipt records these observations beside the artifact digest.
The unsigned in-toto Statement v1 puts that same digest in a standard
`subject` descriptor and those same observations in a project-defined
`predicate`. A consumer that understands Statement v1 can match the subject
without knowing Footsteps. Interpreting a zero exit, the driver's assertions,
or the scope of the claim still requires the predicate and verifier. [Worker statement](packet/worker/statement.json) · [Verifier command](packet/verifier.json) · [Browser driver](packet/browser.cjs) · [Statement v1 specification](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md)

The replay substitutes the other manifest and its matching patch, then the other
patch alone. It also changes the stdout, the verifier descriptor and the driver
separately. Both formats detect all five substitutions in each direction.
Exchanging the two genuine stdout files passes because every byte is identical.
A producer could also rewrite a receipt and its digests together. These unsigned
records depend on trust in the capture and its publisher. The historical review
remains the source for acceptance, authorship and which obligations were tested.

**Decision.** For the next independent probe whose result will travel with a
patch, record the candidate, verifier, invocation, producer and result digest
together while running it. The compact receipt suffices for a Lab reader.
Emit the Statement form when a consumer can use standard subject matching.
This comparison gave the two formats equal ability to detect substitutions.

## Repeating the capture

The packet contains fresh runs of the original isolated headless Chrome keyboard
probe. The capture rebuilt both trees from the archived Git objects, overlaid
the recovered files on the Worker base, checked the scope of the changes, and
reproduced the reviewed Worker manifest byte for byte. Each run got a read-only
checkout, a private temporary directory and no network. Both exited successfully,
and each stdout matched its historical log byte for byte.

On the archive workstation, from the project dev shell, the following command
uses the retained Footsteps checkout, job artifact, launcher, driver and Nix
runtime to write a new packet. Choose a new output directory for each capture.
A portable clone has everything needed for the offline replay above. Repeating
the browser executions additionally requires those workstation inputs.

```sh
python examples/binding-probe-results/capture.py /bulk/dlk/local-harness /tmp/footsteps-probe-new
python3 -S examples/binding-probe-results/replay.py /tmp/footsteps-probe-new
```

Footsteps source excerpts in the display patches are distributed under the
[Footsteps MIT license](packet/FOOTSTEPS-LICENSE.txt).
