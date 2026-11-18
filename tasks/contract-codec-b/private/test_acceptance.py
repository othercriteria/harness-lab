import itertools, unittest
from codec import pack_flags, unpack_flags
N = 8
class AcceptanceTests(unittest.TestCase):
    def test_all_round_trips(self):
        for v in itertools.product((False, True), repeat=N):
            p = pack_flags(v)
            self.assertIs(type(p), bytes)
            self.assertEqual(len(p), 1)
            self.assertEqual(unpack_flags(p), v)
    def test_all_payloads_have_valid_shape(self):
        for i in range(256):
            v = unpack_flags(bytes([i]))
            self.assertIsInstance(v, tuple)
            self.assertEqual(len(v), N)
            self.assertTrue(all(type(x) is bool for x in v))
    def test_invalid_arguments(self):
        for v in [None, [], [False]*N, (), (False,)*(N+1), (0,)*N, (None,)*N]:
            with self.assertRaises(ValueError): pack_flags(v)
        for p in [None, '', bytearray([0]), b'', b'aa', 0]:
            with self.assertRaises(ValueError): unpack_flags(p)
    def test_bytes_subclass_is_invalid(self):
        class Payload(bytes): pass
        with self.assertRaises(ValueError): unpack_flags(Payload(b"\x00"))
    def test_tuple_subclass(self):
        class Flags(tuple): pass
        v=Flags((False,)*N)
        self.assertEqual(unpack_flags(pack_flags(v)), v)
