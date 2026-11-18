class FrameDecoder:
    def __init__(self, max_frame_size):
        self.max_frame_size = max_frame_size
        self._buffer = bytearray()
        self._state = 'open'

    def feed(self, chunk):
        if self._state != 'open':
            raise ValueError('decoder is not open')
        self._buffer.extend(chunk)
        frames = []
        offset = 0
        while len(self._buffer) - offset >= 4:
            size = int.from_bytes(self._buffer[offset:offset + 4], 'big')
            if size > self.max_frame_size:
                self._state = 'failed'
                raise ValueError('frame exceeds maximum size')
            end = offset + 4 + size
            if end > len(self._buffer):
                break
            frames.append(bytes(self._buffer[offset + 4:end]))
            offset = end
        del self._buffer[:offset]
        return frames

    def finish(self):
        if self._state == 'failed':
            raise ValueError('decoder has failed')
        if self._state == 'finished':
            return None
        if self._buffer:
            self._state = 'failed'
            raise ValueError('incomplete frame')
        self._state = 'finished'
        return None
