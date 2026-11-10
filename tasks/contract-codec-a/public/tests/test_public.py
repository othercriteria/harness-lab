import unittest
from codec import pack_flags, unpack_flags

class PublicTests(unittest.TestCase):
    def test_basic_round_trips(self):
        for value in [(False,) * 9, (True,) + (False,) * 8]:
            payload = pack_flags(value)
            self.assertIs(type(payload), bytes)
            self.assertEqual(len(payload), 1)
            self.assertEqual(unpack_flags(payload), value)

    def test_invalid_shape(self):
        with self.assertRaises(ValueError):
            pack_flags(())
        with self.assertRaises(ValueError):
            unpack_flags(b'')
