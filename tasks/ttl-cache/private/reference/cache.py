import time


class Cache:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._items = {}

    def set(self, key, value, *, ttl=None):
        if ttl is not None and ttl <= 0:
            self._items.pop(key, None)
            return
        expires = None if ttl is None else self.clock() + ttl
        self._items[key] = (value, expires)

    def _live(self, key):
        if key not in self._items:
            return False
        _, expires = self._items[key]
        if expires is not None and self.clock() >= expires:
            del self._items[key]
            return False
        return True

    def get(self, key, default=None):
        return self._items[key][0] if self._live(key) else default

    def delete(self, key):
        if not self._live(key):
            return False
        del self._items[key]
        return True

    def purge(self):
        now = self.clock()
        expired = [
            key
            for key, (_, until) in self._items.items()
            if until is not None and now >= until
        ]
        for key in expired:
            del self._items[key]
        return len(expired)
