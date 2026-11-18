# Journal capability

`load(id)` and `save(id, record)` are the only journal operations. `save` replaces
one ID's entire JSON-compatible record atomically and durably. A completed save
survives every later restart. `load` returns a detached value, so modifying it
has no effect until saved. An absent record is represented by None.

A process crash may occur immediately before or after any journal or remote API
operation. The process then ends, with no further cleanup or exception handling;
all local variables and module state are lost. The next invocation receives a
fresh wrapper around the surviving journal and the same remote service. There
are no torn records. The journal and remote service have no shared transaction.

You may call only the documented methods of these objects. Do not inspect or
modify their attributes, inspect test code at runtime, monkeypatch classes,
read remote state through another channel, or use files, environment variables,
clocks, network access, persistent globals, or randomness as extra capabilities.
The journal is the only worker-owned persistent state. You may use local pure
computation and standard-library data structures.
