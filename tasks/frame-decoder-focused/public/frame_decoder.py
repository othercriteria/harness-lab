class FrameDecoder:
    def __init__(self, max_frame_size):
        self.max_frame_size = max_frame_size

    def feed(self, chunk):
        if not chunk:
            return []
        size = int.from_bytes(chunk[:4], 'big')
        return [chunk[4:4 + size]]

    def finish(self):
        return None
