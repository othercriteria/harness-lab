import unittest

from cache import Cache


class PublicTests(unittest.TestCase):
    def test_basic_store(self):
        cache = Cache()
        cache.set("key", 0)
        self.assertEqual(cache.get("key", 9), 0)
        self.assertEqual(cache.get("absent", 9), 9)

    def test_delete(self):
        cache = Cache()
        cache.set("key", None)
        self.assertTrue(cache.delete("key"))
        self.assertFalse(cache.delete("key"))
