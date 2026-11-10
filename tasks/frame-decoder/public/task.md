# Repair the incremental frame decoder

Repair `FrameDecoder` in `frame_decoder.py`. It decodes a binary stream whose frames
are a four-byte unsigned big-endian payload length followed by that many payload
bytes. Payload bytes are arbitrary, including zero bytes. A zero-length frame is
valid. Preserve `FrameDecoder(max_frame_size)`, `feed(chunk)` and `finish()`;
use only the Python standard library. Do not change the supplied tests. Add focused
regressions and run `python -m unittest discover -s tests`.

The aligned contract is:

- Callers supply an exact `int` max_frame_size between 0 and 1048576 inclusive and
  exact `bytes` chunks. Other argument types and constructor values are outside
  this task. Each decoder starts open with an empty input stream; instances are
  independent.
- While open, `feed(chunk)` appends the chunk to that decoder's input. Chunks may
  be empty and may split headers or payloads at any byte. Return a new list of
  all frames completed by this call, in stream order, as immutable `bytes` payloads.
  Retain an incomplete trailing header or payload for later calls. Do not emit
  a frame twice. Mutating a returned list must not affect subsequent results.
- As soon as four bytes of the next header are available, a declared length above
  max_frame_size raises `ValueError`, even if that payload has not arrived. This
  permanently fails the decoder. A failing feed returns no list, including when
  valid frames preceded the bad header within that call. Previously returned
  results remain unchanged. There is no recovery or reset API.
- `finish()` marks the end of input. If open with no partial frame, return `None`
  and mark the decoder finished. If any partial header or payload remains, raise
  `ValueError` and permanently fail the decoder. A zero-length payload following
  a complete header is a complete frame and must already have been returned by
  feed, not held until finish.
- On a finished decoder, repeated `finish()` calls return `None`, but every
  `feed` (including an empty chunk) raises `ValueError`. On a failed decoder,
  every `feed` and `finish` raises `ValueError`. Do not silently resume parsing.

Exception messages, private representation and performance tuning are not part
of the contract. Streams fit in memory; concurrency and direct access to private
attributes are out of scope. Return values, ordering, chunk-boundary behavior and
terminal states are the requirements.
