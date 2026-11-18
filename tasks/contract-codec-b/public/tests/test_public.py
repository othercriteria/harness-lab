import itertools
import unittest
from codec import pack_flags, unpack_flags

N_FLAGS = 8

class PublicTests(unittest.TestCase):
    def test_all_vectors_round_trip(self):
        for vector in itertools.product((False, True), repeat=N_FLAGS):
            payload = pack_flags(vector)
            self.assertIs(type(payload), bytes)
            self.assertEqual(len(payload), 1)
            self.assertEqual(unpack_flags(payload), vector)

    def test_all_payloads_have_valid_shape(self):
        for number in range(256):
            vector = unpack_flags(bytes((number,)))
            self.assertIsInstance(vector, tuple)
            self.assertEqual(len(vector), N_FLAGS)
            self.assertTrue(all(type(value) is bool for value in vector))

    def test_tuple_subclass(self):
        class Flags(tuple):
            pass
        vector = Flags(bool(index % 2) for index in range(N_FLAGS))
        self.assertEqual(unpack_flags(pack_flags(vector)), vector)

    def test_invalid_flags(self):
        for value in (None, 0, [False] * N_FLAGS, (),
                      (False,) * (N_FLAGS - 1), (False,) * (N_FLAGS + 1),
                      (1,) + (False,) * (N_FLAGS - 1)):
            with self.assertRaises(ValueError):
                pack_flags(value)

    def test_invalid_payloads(self):
        class Payload(bytes):
            pass
        for value in (None, 0, "x", b"", b"\x00\x01",
                      bytearray(b"\x00"), Payload(b"\x00")):
            with self.assertRaises(ValueError):
                unpack_flags(value)
