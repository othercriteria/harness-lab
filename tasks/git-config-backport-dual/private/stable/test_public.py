import io
import unittest
import configparser as cp
import service


class WriteContract(unittest.TestCase):
    def test_safe_roundtrip(self):
        p = cp.ConfigParser()
        p.read_dict({'s': {'z': 'last', 'a': 'first'}})
        out = io.StringIO()
        p.write(out)
        q = cp.ConfigParser()
        q.read_string(out.getvalue())
        self.assertEqual(dict(q['s']), dict(p['s']))

    def test_invalid_key_no_partial_output(self):
        p = cp.ConfigParser()
        p.read_dict({'safe': {'ok': '1'}, 'late': {'bad=key': '2'}})
        out = io.StringIO('prefix')
        out.seek(0, 2)
        with self.assertRaises((cp.Error, ValueError)):
            p.write(out)
        self.assertEqual(out.getvalue(), 'prefix')
        self.assertFalse(out.closed)

    def test_service_failure(self):
        p = cp.ConfigParser()
        p.read_dict({'s': {'bad\nkey': 'x'}})
        out = io.StringIO()
        result = service.export(p, out)
        self.assertEqual(result, service.INVALID)
        self.assertEqual(out.getvalue(), '')
        self.assertFalse(out.closed)

    def test_per_parser_delimiters(self):
        p = cp.ConfigParser(delimiters=('=>',))
        p.read_dict({'s': {'safe=key': 'value'}})
        out = io.StringIO()
        p.write(out)
        self.assertIn('safe=key', out.getvalue())


if __name__ == '__main__':
    unittest.main()
