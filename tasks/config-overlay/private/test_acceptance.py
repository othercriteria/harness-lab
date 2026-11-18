import copy
import unittest

from merge import merge
from settings import DEFAULTS, load_settings


class AcceptanceTests(unittest.TestCase):
    def test_nested_defaults_survive(self):
        self.assertEqual(
            load_settings({"worker": {"retries": 0}}),
            {"worker": {"retries": 0, "labels": ["batch"]}, "enabled": True},
        )

    def test_lists_replace(self):
        self.assertEqual(merge({"x": [1, 2]}, {"x": [3]}), {"x": [3]})

    def test_type_changes_and_falsey(self):
        for value in (None, False, 0, "", [], {}):
            with self.subTest(value=value):
                self.assertEqual(merge({"x": 9}, {"x": value}), {"x": value})
        self.assertEqual(merge({"x": {"a": 1}}, {"x": None}), {"x": None})

    def test_deep_merge(self):
        self.assertEqual(
            merge({"a": {"b": {"c": 1, "d": 2}}}, {"a": {"b": {"c": 4}}}),
            {"a": {"b": {"c": 4, "d": 2}}},
        )

    def test_inputs_and_result_independent(self):
        left = {"a": [{"k": [1]}], "both": {"x": [2]}}
        right = {"b": [{"k": [3]}], "both": {"y": [4]}}
        before = copy.deepcopy((left, right))
        result = merge(left, right)
        self.assertEqual((left, right), before)
        result["a"][0]["k"].append(5)
        result["b"][0]["k"].append(5)
        result["both"]["x"].append(5)
        result["both"]["y"].append(5)
        self.assertEqual((left, right), before)
        left["both"]["x"].append(9)
        self.assertNotIn(9, result["both"]["x"])

    def test_loader_does_not_change_defaults(self):
        before = copy.deepcopy(DEFAULTS)
        loaded = load_settings({})
        loaded["worker"]["labels"].append("changed")
        self.assertEqual(DEFAULTS, before)
