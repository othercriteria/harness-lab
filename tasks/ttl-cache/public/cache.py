import time


class Cache:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._items = {}

    def set(self, key, value):
        self._items[key] = value

    def get(self, key, default=None):
        return self._items.get(key, default)

    def delete(self, key):
        if key in self._items:
            del self._items[key]
            return True
        return False
