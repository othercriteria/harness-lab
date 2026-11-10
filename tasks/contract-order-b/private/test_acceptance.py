import itertools, unittest
from ordering import order_records
class Record: pass
class AcceptanceTests(unittest.TestCase):
    def check_order(self, ranks):
        records=[Record() for _ in ranks]
        lookup={id(v):r for v,r in zip(records,ranks)}
        compare=lambda a,b:(lookup[id(a)]>lookup[id(b)])-(lookup[id(a)]<lookup[id(b)])
        before=list(records)
        result=order_records(records,compare)
        expected=sorted(records,key=lambda v:lookup[id(v)])
        self.assertIsInstance(result,list)
        self.assertIsNot(result,records)
        self.assertEqual([id(v) for v in result],[id(v) for v in expected])
        self.assertEqual([id(v) for v in records],[id(v) for v in before])
    def test_all_small_permutations(self):
        for p in itertools.permutations(range(5)): self.check_order(p)
    def test_ties_and_stability(self):
        for p in [[],[1],[2,1,2,0,1,2],[0]*30,list(range(80)),list(range(80))[::-1]]:
            self.check_order(p)
    def test_repeated_occurrences(self):
        a,b=Record(),Record(); lookup={id(a):1,id(b):0}
        result=order_records([a,b,a],lambda x,y:lookup[id(x)]-lookup[id(y)])
        self.assertEqual([id(v) for v in result],[id(b),id(a),id(a)])
    def test_comparator_exception(self):
        class Expected(Exception): pass
        def compare(a,b): raise Expected('sentinel')
        with self.assertRaises(Expected): order_records([Record(),Record()],compare)
