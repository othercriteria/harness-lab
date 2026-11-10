import unittest
from pipeline.planner import plan

class PublicTests(unittest.TestCase):
    def test_source(self):
        self.assertEqual(plan(set(), "decode"), ["decode"])

    def test_basic_storage(self):
        self.assertEqual(plan(set(), "store"), ["decode", "redact", "store"])

    def test_no_input_mutation(self):
        features = {"durable"}
        result = plan(features, "decode")
        self.assertEqual(features, {"durable"})
        self.assertEqual(result, ["decode"])
