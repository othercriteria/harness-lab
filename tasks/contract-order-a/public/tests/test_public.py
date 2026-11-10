import unittest
from ordering import order_records

class Record:
    pass

class PublicTests(unittest.TestCase):
    def test_order_and_stability(self):
        a, b, c = Record(), Record(), Record()
        rank = {id(a): 2, id(b): 1, id(c): 2}
        compare = lambda x, y: (rank[id(x)] > rank[id(y)]) - (rank[id(x)] < rank[id(y)])
        original = [a, b, c]
        self.assertEqual(order_records(original, compare), [b, a, c])
        self.assertEqual(original, [a, b, c])

    def test_empty(self):
        self.assertEqual(order_records([], lambda a, b: 0), [])
