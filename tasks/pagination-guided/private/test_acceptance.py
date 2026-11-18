import unittest

from api import Page
from records import iter_records


class AcceptanceTests(unittest.TestCase):
    def test_empty_middle_and_falsey_cursors(self):
        pages = {None: Page([], ""), "": Page(iter([1]), 0), 0: Page([2])}
        self.assertEqual(list(iter_records(pages.__getitem__)), [1, 2])

    def test_no_eager_fetch(self):
        calls = []

        def fetch(cursor):
            calls.append(cursor)
            return Page([1, 2], "next") if cursor is None else Page([3])

        stream = iter_records(fetch)
        self.assertEqual(calls, [])
        self.assertEqual(next(stream), 1)
        self.assertEqual(next(stream), 2)
        self.assertEqual(calls, [None])
        self.assertEqual(next(stream), 3)
        self.assertEqual(calls, [None, "next"])

    def test_items_are_consumed_lazily(self):
        consumed = []

        def items():
            for i in range(3):
                consumed.append(i)
                yield i

        stream = iter_records(lambda cursor: Page(items()))
        self.assertEqual(next(stream), 0)
        self.assertEqual(consumed, [0])

    def test_cursor_cycle(self):
        calls = []

        def fetch(cursor):
            calls.append(cursor)
            if len(calls) > 3:
                raise AssertionError("duplicate cursor was fetched")
            return Page([cursor], "a" if cursor in (None, "b") else "b")

        stream = iter_records(fetch)
        self.assertEqual([next(stream) for _ in range(3)], [None, "a", "b"])
        with self.assertRaises(ValueError):
            next(stream)
        self.assertEqual(calls, [None, "a", "b"])

    def test_error_propagates_once(self):
        calls = []
        failure = RuntimeError("API unavailable")

        def fetch(cursor):
            calls.append(cursor)
            raise failure

        with self.assertRaises(RuntimeError) as caught:
            next(iter_records(fetch))
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, [None])

    def test_empty_terminal(self):
        self.assertEqual(list(iter_records(lambda cursor: Page(iter([])))), [])

    def test_initial_cursor_participates_in_repeat_detection(self):
        class NoneAlias:
            def __hash__(self):
                return hash(None)

            def __eq__(self, other):
                return other is None or isinstance(other, NoneAlias)

        calls = []
        alias = NoneAlias()

        def fetch(cursor):
            calls.append(cursor)
            if len(calls) > 1:
                raise RuntimeError("equal initial cursor fetched again")
            return Page([], alias)

        with self.assertRaises(ValueError):
            list(iter_records(fetch))
        self.assertEqual(calls, [None])

    def test_equal_cursors_of_different_types_repeat(self):
        calls = []

        def fetch(cursor):
            calls.append(cursor)
            if len(calls) > 2:
                raise RuntimeError("equal cursor fetched again")
            return Page([], 0 if cursor is None else False)

        with self.assertRaises(ValueError):
            list(iter_records(fetch))
        self.assertEqual(calls, [None, 0])

    def test_repeat_error_does_not_require_cursor_formatting(self):
        class Cursor:
            def __hash__(self):
                return 123
            def __eq__(self, other):
                return self is other
            def __str__(self):
                raise RuntimeError("string unavailable")
            def __repr__(self):
                raise RuntimeError("representation unavailable")
        cursor = Cursor()
        calls = []
        def fetch(value):
            calls.append(value is None)
            if len(calls) > 2:
                raise AssertionError("repeated cursor fetched")
            return Page([len(calls)], cursor)
        with self.assertRaises(ValueError):
            list(iter_records(fetch))
        self.assertEqual(calls, [True, False])
