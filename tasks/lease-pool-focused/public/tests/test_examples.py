"""Executable examples of numeric validation and clock sampling."""
import unittest
from lease_pool import LeasePool


class CountingClock:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return 10


class ContractExamples(unittest.TestCase):
    def test_large_integer_ttls_raise_value_error_before_clock(self):
        clock = CountingClock()
        pool = LeasePool(clock)
        for ttl in (10 ** 400, -(10 ** 400)):
            with self.subTest(sign=ttl > 0):
                with self.assertRaises(ValueError):
                    pool.acquire("job", ttl)
                with self.assertRaises(ValueError):
                    pool.renew("job", 1, ttl)
        self.assertEqual(clock.calls, 0)
        self.assertEqual(pool.acquire("job", 5), 1)

    def test_nonmatching_tokens_still_sample_clock_once(self):
        clock = CountingClock()
        pool = LeasePool(clock)
        token = pool.acquire("job", 5)
        for invalid in (True, float(token), None):
            before = clock.calls
            self.assertFalse(pool.renew("job", invalid, 5))
            self.assertEqual(clock.calls, before + 1)
            self.assertFalse(pool.release("job", invalid))
            self.assertEqual(clock.calls, before + 2)
        self.assertTrue(pool.release("job", token))
