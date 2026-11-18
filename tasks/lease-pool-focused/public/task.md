# Repair the lease pool

`lease_pool.py` implements a small in-memory lease pool for coordinating named jobs.
Repair it while preserving `LeasePool(clock)` and its public methods. The supplied
clock is a callable returning seconds. No real sleeping, threads, persistence or
external dependencies are needed. Edit `lease_pool.py`; you may add tests, but do
not change the supplied tests. Run `python -m unittest discover -s tests` and submit.

The aligned contract is:

- Each call to `acquire`, `renew`, `release` or `snapshot` samples the supplied
  clock exactly once after validating its inputs. Construction does not call it.
  Clock values are finite numbers between 0 and 1 billion, and never decrease.
  A lease is active exactly while `now < expires_at`; equality means expired.
- Keys must have exact type `str` and be nonempty (whitespace is allowed). Invalid keys raise
  `ValueError`. A TTL must have exact type `int` or `float`, be finite, and satisfy
  `0 < ttl <= 86400`. Booleans and all other types are invalid. Invalid TTLs raise
  `ValueError`. Input-validation failures do not call the clock or change state.
- `acquire(key, ttl)` validates key and TTL. If that key is active, return `None`.
  Otherwise grant a lease expiring at `now + ttl` and return a token. Tokens are
  positive integers, numbered 1, 2, 3, ... across successful acquisitions in this
  pool, regardless of key. Denied acquisitions and other operations consume no
  tokens. Each pool starts its own sequence at 1.
- `renew(key, token, ttl)` validates key and TTL first. If the key is active and
  the token matches, set its expiry to `now + ttl` and return `True`. Renewal keeps
  the token and may shorten the lease. Otherwise return `False`; do not grant or
  revive a lease. A matching token must have exact type `int` (so `True` and `1.0`
  do not match token 1). Nonmatching or invalid tokens return `False`.
- `release(key, token)` validates the key. Remove an active matching lease and
  return `True`, using the same exact-integer token rule as `renew`. Otherwise
  return `False`. In particular, an old token must never release a later lease.
- `snapshot()` returns a new dictionary of all active leases, of the form
  `{key: {"token": token, "remaining": expires_at - now}}`. Omit expired leases.
  Mutating the result, including its nested dictionaries, must not affect the pool.

Expired entries may be removed eagerly or lazily; their internal storage is not
part of the interface. Exceptions from the clock, concurrent use, and direct mutation of private
attributes are outside this task.

Use the supplied tests to check the repair. Keep the added suite small: one or two
focused regression tests of valid inputs affected by your repair are sufficient.
Derive their expected results from the contract.
