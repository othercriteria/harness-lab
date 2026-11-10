import unittest
from frame_decoder import FrameDecoder


def wire(payload):
    return len(payload).to_bytes(4, 'big') + payload


class AcceptanceTests(unittest.TestCase):
    def test_every_single_split(self):
        payloads = [b'', b'abc', bytes(range(256)), b'\0\0\0\0']
        stream = b''.join(map(wire, payloads))
        for cut in range(len(stream) + 1):
            decoder = FrameDecoder(256)
            a = decoder.feed(stream[:cut])
            b = decoder.feed(stream[cut:])
            self.assertIs(type(a), list)
            self.assertIs(type(b), list)
            self.assertEqual(a + b, payloads, f"split at {cut}")
            self.assertTrue(all(type(x) is bytes for x in a + b))
            self.assertIsNone(decoder.finish())

    def test_byte_at_a_time_and_empty_chunks(self):
        payloads = [b'abc', b'', b'\xff\0x', b'']
        decoder = FrameDecoder(3)
        actual = []
        for byte in b''.join(map(wire, payloads)):
            self.assertEqual(decoder.feed(b''), [])
            actual.extend(decoder.feed(bytes([byte])))
        self.assertEqual(actual, payloads)
        self.assertEqual(decoder.feed(b''), [])
        self.assertIsNone(decoder.finish())

    def test_emit_only_completed_frames(self):
        decoder = FrameDecoder(3)
        self.assertEqual(decoder.feed(wire(b'x') + wire(b'abc')[:-1]), [b'x'])
        self.assertEqual(decoder.feed(b''), [])
        self.assertEqual(decoder.feed(b'c'), [b'abc'])
        self.assertIsNone(decoder.finish())

    def test_zero_maximum_empty_frames(self):
        decoder = FrameDecoder(0)
        self.assertEqual(decoder.feed(b'\0' * 12), [b'', b'', b''])
        self.assertIsNone(decoder.finish())

    def test_maximum_boundary_and_immediate_oversize(self):
        decoder = FrameDecoder(3)
        self.assertEqual(decoder.feed(wire(b'abc')), [b'abc'])
        self.assertEqual(decoder.feed(b'\0\0\0'), [])
        with self.assertRaises(ValueError):
            decoder.feed(b'\x04')
        for action in [lambda: decoder.feed(wire(b'a')), lambda: decoder.feed(b''), decoder.finish]:
            with self.assertRaises(ValueError):
                action()

    def test_unsigned_large_header(self):
        decoder = FrameDecoder(1048576)
        with self.assertRaises(ValueError):
            decoder.feed(b'\xff' * 4)
        with self.assertRaises(ValueError):
            decoder.finish()

    def test_oversize_after_valid_frame_fails_whole_call(self):
        decoder = FrameDecoder(2)
        previous = decoder.feed(wire(b'ok'))
        with self.assertRaises(ValueError):
            decoder.feed(wire(b'x') + (3).to_bytes(4, 'big'))
        self.assertEqual(previous, [b'ok'])
        with self.assertRaises(ValueError):
            decoder.feed(b'abc')

    def test_truncated_header_poisoning(self):
        for count in [1, 2, 3]:
            with self.subTest(count=count):
                decoder = FrameDecoder(10)
                self.assertEqual(decoder.feed(b'\0' * count), [])
                with self.assertRaises(ValueError):
                    decoder.finish()
                with self.assertRaises(ValueError):
                    decoder.feed(b'\0' * (4-count))
                with self.assertRaises(ValueError):
                    decoder.finish()

    def test_truncated_payload_poisoning(self):
        decoder = FrameDecoder(10)
        self.assertEqual(decoder.feed(wire(b'ab')[:-1]), [])
        with self.assertRaises(ValueError):
            decoder.finish()
        with self.assertRaises(ValueError):
            decoder.feed(b'b')
        with self.assertRaises(ValueError):
            decoder.finish()

    def test_finished_state(self):
        decoder = FrameDecoder(3)
        self.assertIsNone(decoder.finish())
        self.assertIsNone(decoder.finish())
        for chunk in [b'', wire(b'a')]:
            with self.assertRaises(ValueError):
                decoder.feed(chunk)
        self.assertIsNone(decoder.finish())

    def test_detached_results(self):
        decoder = FrameDecoder(3)
        first = decoder.feed(wire(b'a'))
        second = decoder.feed(b'')
        self.assertIsNot(first, second)
        first.clear()
        second.append(b'bad')
        third = decoder.feed(wire(b'b'))
        self.assertEqual(third, [b'b'])
        self.assertEqual(first, [])
        self.assertEqual(second, [b'bad'])
        self.assertIsNone(decoder.finish())

    def test_independent_instances(self):
        first, second = FrameDecoder(3), FrameDecoder(3)
        self.assertEqual(first.feed(wire(b'ab')[:-1]), [])
        self.assertEqual(second.feed(wire(b'z')), [b'z'])
        self.assertIsNone(second.finish())
        self.assertEqual(first.feed(b'b'), [b'ab'])
        self.assertIsNone(first.finish())
