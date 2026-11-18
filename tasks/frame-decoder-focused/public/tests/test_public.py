import unittest

from frame_decoder import FrameDecoder


def frame(payload):
    return len(payload).to_bytes(4, 'big') + payload


class PublicTests(unittest.TestCase):
    def test_single_frame(self):
        decoder = FrameDecoder(10)
        self.assertEqual(decoder.feed(frame(b'hi')), [b'hi'])
        self.assertIsNone(decoder.finish())

    def test_split_payload(self):
        decoder = FrameDecoder(10)
        self.assertEqual(decoder.feed(frame(b'hello')[:6]), [])
        self.assertEqual(decoder.feed(b'llo'), [b'hello'])
        self.assertIsNone(decoder.finish())

    def test_empty_and_consecutive_frames(self):
        decoder = FrameDecoder(10)
        self.assertEqual(decoder.feed(frame(b'') + frame(b'x')), [b'', b'x'])
        self.assertEqual(decoder.feed(b''), [])

    def test_incomplete_input(self):
        decoder = FrameDecoder(10)
        decoder.feed(b'\0\0')
        with self.assertRaises(ValueError):
            decoder.finish()
