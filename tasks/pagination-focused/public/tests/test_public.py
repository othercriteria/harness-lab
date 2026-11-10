import unittest

from api import Page
from records import iter_records


class PublicTests(unittest.TestCase):
    def test_single_page(self):
        self.assertEqual(list(iter_records(lambda cursor: Page([1, 2]))), [1, 2])

    def test_two_pages(self):
        pages = {None: Page([1], "next"), "next": Page([2])}
        self.assertEqual(list(iter_records(pages.__getitem__)), [1, 2])
