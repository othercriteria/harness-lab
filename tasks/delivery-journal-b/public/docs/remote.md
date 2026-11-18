# Remote capability

`apply(request_id, payload)` is the only remote operation. Both arguments are
strings; use the job ID as request_id and its exact payload as payload. There is
no read, query, undo, enumeration, or acknowledgement-recovery operation.

On an acknowledged invocation, the service returns None after the operation.
An invocation may instead raise DeliveryUncertain either before the service
receives it, or after it has performed the operation but the reply is lost. These
cases have the same exception type and message and expose no other information.
The worker must support any finite sequence of such uncertainties and crashes,
followed by a failure-free suffix of caller retries. Calls terminate; no waits,
timeouts, or network implementation are part of this exercise.

The service maintains a durable deduplication table keyed by request_id. Its
first received invocation for an ID atomically applies the payload and stores
that ID/payload pair. Later invocations with the same ID/payload do not apply it
again and return None when acknowledged. This table survives process restarts
and has no expiry. The worker must not reuse an ID with a different payload.
