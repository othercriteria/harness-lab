import unittest

from lease_pool import LeasePool


class CounterClock:
    def __init__(self):
        self.now = 20.0
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.now


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.clock = CounterClock()
        self.pool = LeasePool(self.clock)

    def test_global_sequence_only_successful_acquisitions(self):
        self.assertEqual(self.pool.acquire('a', 1), 1)
        self.assertIsNone(self.pool.acquire('a', 2))
        self.assertFalse(self.pool.release('missing', 2))
        self.assertFalse(self.pool.renew('a', 99, 2))
        self.assertTrue(self.pool.renew('a', 1, 1))
        self.assertEqual(self.pool.acquire('b', 1), 2)
        self.clock.now = 21
        self.assertEqual(self.pool.acquire('a', 3), 3)
        self.assertEqual(self.pool.acquire('b', 3), 4)

    def test_independent_pools(self):
        self.pool.acquire('a', 10)
        self.assertEqual(LeasePool(self.clock).acquire('a', 10), 1)

    def test_exact_expiry_for_all_operations(self):
        for operation in ('renew', 'release', 'snapshot'):
            with self.subTest(operation=operation):
                pool = LeasePool(self.clock)
                token = pool.acquire('k', 1)
                self.clock.now += 1
                result = (pool.snapshot() if operation == 'snapshot' else
                          pool.renew('k', token, 2) if operation == 'renew' else
                          pool.release('k', token))
                self.assertEqual(result, {} if operation == 'snapshot' else False)

    def test_fractional_ttl_and_remaining(self):
        token = self.pool.acquire('x', 0.5)
        self.clock.now = 20.25
        self.assertEqual(self.pool.snapshot(), {'x': {'token': token, 'remaining': 0.25}})
        self.clock.now = 20.5
        self.assertEqual(self.pool.snapshot(), {})

    def test_stale_tokens_cannot_change_replacement(self):
        old = self.pool.acquire('x', 1)
        self.clock.now = 21
        new = self.pool.acquire('x', 10)
        self.assertFalse(self.pool.renew('x', old, 1))
        self.assertFalse(self.pool.release('x', old))
        self.assertEqual(self.pool.snapshot(), {'x': {'token': new, 'remaining': 10}})

    def test_renew_extends_from_current_time(self):
        token = self.pool.acquire('x', 2)
        self.clock.now = 21
        self.assertTrue(self.pool.renew('x', token, 3))
        self.clock.now = 23
        self.assertEqual(self.pool.snapshot(), {'x': {'token': token, 'remaining': 1}})

    def test_renew_can_shorten(self):
        token = self.pool.acquire('x', 100)
        self.clock.now = 21
        self.assertTrue(self.pool.renew('x', token, 1))
        self.clock.now = 22
        self.assertEqual(self.pool.snapshot(), {})

    def test_snapshot_detached_at_both_levels(self):
        token = self.pool.acquire('x', 5)
        result = self.pool.snapshot()
        result['x']['token'] = 999
        result['x']['remaining'] = 999
        result['other'] = result['x']
        self.assertEqual(self.pool.snapshot(), {'x': {'token': token, 'remaining': 5}})
        result.clear()
        self.assertTrue(self.pool.release('x', token))

    def test_valid_calls_sample_clock_once(self):
        self.assertEqual(self.clock.calls, 0)
        operations = [lambda: self.pool.acquire('x', 1), lambda: self.pool.acquire('x', 1),
                      lambda: self.pool.renew('x', 1, 1), lambda: self.pool.release('x', 99),
                      lambda: self.pool.release('x', 1), lambda: self.pool.snapshot(),
                      lambda: self.pool.renew('absent', None, 1)]
        for operation in operations:
            before = self.clock.calls
            operation()
            self.assertEqual(self.clock.calls, before + 1)

    def test_invalid_keys_raise_without_clock_calls(self):
        class StringSubclass(str):
            pass
        for key in ('', None, 1, True, [], {}, b'x', StringSubclass('x')):
            for operation in (lambda: self.pool.acquire(key, 1),
                              lambda: self.pool.renew(key, 1, 1),
                              lambda: self.pool.release(key, 1)):
                with self.subTest(key=repr(key)):
                    before = self.clock.calls
                    with self.assertRaises(ValueError):
                        operation()
                    self.assertEqual(self.clock.calls, before)
        self.assertEqual(self.pool.acquire(' ', 1), 1)

    def test_invalid_ttl_does_not_mutate_or_call_clock(self):
        token = self.pool.acquire('x', 10)
        class IntSubclass(int):
            pass
        for ttl in (0, -1, 86401, 10**500, float('inf'), float('-inf'), float('nan'),
                    True, False, '1', None, [], IntSubclass(1)):
            for key in ('x', 'absent'):
                for operation in (lambda: self.pool.acquire(key, ttl),
                                  lambda: self.pool.renew(key, 999, ttl)):
                    before = self.clock.calls
                    with self.assertRaises(ValueError):
                        operation()
                    self.assertEqual(self.clock.calls, before)
        self.assertEqual(self.pool.snapshot(), {'x': {'token': token, 'remaining': 10}})
        self.assertEqual(self.pool.acquire('other', 86400), 2)

    def test_exact_integer_tokens(self):
        class IntSubclass(int):
            pass
        token = self.pool.acquire('x', 5)
        for wrong in (True, 1.0, '1', None, [], {}, IntSubclass(1), 0, -1, 99):
            self.assertFalse(self.pool.renew('x', wrong, 1))
            self.assertFalse(self.pool.release('x', wrong))
        self.assertEqual(self.pool.snapshot(), {'x': {'token': token, 'remaining': 5}})

    def test_snapshot_omits_expired_without_renewing(self):
        self.pool.acquire('early', 1)
        token = self.pool.acquire('late', 3)
        self.clock.now = 21
        self.assertEqual(self.pool.snapshot(), {'late': {'token': token, 'remaining': 2}})
        self.clock.now = 23
        self.assertEqual(self.pool.snapshot(), {})

    def test_release_and_reacquire_keep_sequence(self):
        first = self.pool.acquire('x', 5)
        self.assertTrue(self.pool.release('x', first))
        self.assertFalse(self.pool.release('x', first))
        self.assertEqual(self.pool.acquire('x', 5), 2)
