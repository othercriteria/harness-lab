import unittest
from placement.allocator import allocate


class PublicTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(allocate(set(), "standard"), {})

    def test_single(self):
        self.assertEqual(allocate({"api"}, "standard"), {"api": "atlas"})

    def test_order_and_inputs(self):
        services = {"audit", "api"}
        self.assertEqual(allocate(services, "reserve"), {"api": "atlas", "audit": "birch"})
        self.assertEqual(services, {"audit", "api"})
