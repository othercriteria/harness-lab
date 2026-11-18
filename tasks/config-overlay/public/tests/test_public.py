import unittest

from merge import merge
from settings import load_settings


class PublicTests(unittest.TestCase):
    def test_scalar_override(self):
        self.assertEqual(merge({"a": 1}, {"a": 2}), {"a": 2})

    def test_loader(self):
        self.assertFalse(load_settings({"enabled": False})["enabled"])
