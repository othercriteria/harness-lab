import unittest

from lease_pool import LeasePool


class Clock:
    def __init__(self):
        self.now = 10

    def __call__(self):
        return self.now


class PublicTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.pool = LeasePool(self.clock)

    def test_acquire_conflict_and_sequence(self):
        self.assertEqual(self.pool.acquire("mail", 5), 1)
        self.assertIsNone(self.pool.acquire("mail", 5))
        self.assertEqual(self.pool.acquire("index", 5), 2)

    def test_expiry_and_stale_release(self):
        old = self.pool.acquire("mail", 2)
        self.clock.now = 12
        new = self.pool.acquire("mail", 5)
        self.assertEqual(new, 2)
        self.assertFalse(self.pool.release("mail", old))
        self.assertTrue(self.pool.release("mail", new))

    def test_renew_from_now_and_detached_snapshot(self):
        token = self.pool.acquire("mail", 10)
        self.clock.now = 12
        self.assertTrue(self.pool.renew("mail", token, 1))
        snapshot = self.pool.snapshot()
        self.assertEqual(snapshot, {"mail": {"token": token, "remaining": 1}})
        snapshot["mail"]["token"] = 999
        self.assertTrue(self.pool.release("mail", token))

    def test_invalid_ttl_and_exact_token_type(self):
        with self.assertRaises(ValueError):
            self.pool.acquire("mail", True)
        token = self.pool.acquire("mail", 5)
        self.assertFalse(self.pool.release("mail", float(token)))
        self.assertTrue(self.pool.release("mail", token))
