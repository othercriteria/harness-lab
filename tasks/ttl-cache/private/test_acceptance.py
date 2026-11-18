import unittest

from cache import Cache


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.cache = Cache(clock=lambda: self.now)

    def test_expiration_boundary(self):
        self.cache.set("x", 7, ttl=2)
        self.now = 11.999
        self.assertEqual(self.cache.get("x"), 7)
        self.now = 12.0
        self.assertEqual(self.cache.get("x", "missing"), "missing")

    def test_read_does_not_renew(self):
        self.cache.set("x", 7, ttl=2)
        self.now = 11
        self.cache.get("x")
        self.now = 12
        self.assertIsNone(self.cache.get("x"))

    def test_overwrite_resets(self):
        self.cache.set("x", 1, ttl=2)
        self.now = 11
        self.cache.set("x", 2, ttl=4)
        self.now = 12
        self.assertEqual(self.cache.get("x"), 2)
        self.now = 15
        self.assertIsNone(self.cache.get("x"))

    def test_overwrite_removes_expiration(self):
        self.cache.set("x", 1, ttl=1)
        self.cache.set("x", 2)
        self.now = 1000
        self.assertEqual(self.cache.get("x"), 2)

    def test_nonpositive_removes(self):
        for ttl in (0, -1):
            self.cache.set("x", 1)
            self.cache.set("x", 2, ttl=ttl)
            self.assertEqual(self.cache.get("x", "missing"), "missing")
            self.assertFalse(self.cache.delete("x"))

    def test_falsey_values(self):
        for value in (None, False, 0, "", []):
            self.cache.set("x", value, ttl=5)
            self.assertEqual(self.cache.get("x", "missing"), value)

    def test_delete_expired(self):
        self.cache.set("x", 1, ttl=1)
        self.now = 11
        self.assertFalse(self.cache.delete("x"))

    def test_purge(self):
        self.cache.set("a", 1, ttl=1)
        self.cache.set("b", 2, ttl=1)
        self.cache.set("c", 3, ttl=2)
        self.cache.set("d", 4)
        self.now = 11
        self.assertEqual(self.cache.purge(), 2)
        self.assertEqual(self.cache.purge(), 0)
        self.assertEqual(self.cache.get("c"), 3)
        self.assertEqual(self.cache.get("d"), 4)
