# Add expiration to the cache

`cache.Cache` currently stores values indefinitely. Extend `set` to accept an
optional keyword-only `ttl` in seconds. Keep the existing `get(key, default=None)`
and `delete(key)` behavior. `clock` is an injected callable returning monotonic
seconds; use it so tests need no sleeps. TTL is `None` or a finite number.

`ttl=None` means no expiration. An item expires when `clock() >= set_time + ttl`.
A nonpositive TTL immediately removes any existing item at that key. Overwriting
resets expiration, including removing an old expiration when TTL is omitted.
`get` returns its default for absent/expired keys and preserves falsey cached
values. `delete` returns True only if the key was live when deleted, otherwise
False. Add `purge()` to remove expired entries and return the number removed;
repeating it without new expirations returns zero. Reads must not extend TTL.
Do not introduce external dependencies.

Run `python -m unittest discover -s tests` and add focused regressions.
