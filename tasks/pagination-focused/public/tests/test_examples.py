"""Executable examples of successor and repeated-cursor behavior."""
import unittest
from api import Page
from records import iter_records


class ContractExamples(unittest.TestCase):
    def test_empty_pages_can_have_falsey_successors(self):
        pages = {None: Page([], ""), "": Page([1], 0), 0: Page([2])}
        self.assertEqual(list(iter_records(pages.__getitem__)), [1, 2])

    def test_repeated_hashable_cursor_raises_value_error(self):
        class Cursor:
            def __repr__(self):
                raise RuntimeError("cursor representation is unavailable")

            def __str__(self):
                raise RuntimeError("cursor string is unavailable")

        cursor = Cursor()
        calls = []

        def fetch(value):
            calls.append(value)
            return Page([len(calls)], cursor)

        records = iter_records(fetch)
        self.assertEqual(next(records), 1)
        self.assertEqual(next(records), 2)
        with self.assertRaises(ValueError):
            next(records)
        self.assertEqual(len(calls), 2)
        self.assertIsNone(calls[0])
        self.assertIs(calls[1], cursor)
