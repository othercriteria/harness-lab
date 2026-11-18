"""Small in-memory leases, using a caller-supplied clock."""


class LeasePool:
    def __init__(self, clock):
        self._clock = clock
        self._leases = {}
        self._next_token = 1

    @staticmethod
    def _validate_key(key):
        if type(key) is not str or not key:
            raise ValueError("key must be a nonempty str")

    @staticmethod
    def _validate_ttl(ttl):
        # Bounds also reject NaN and infinities without converting large ints.
        if type(ttl) not in (int, float) or not (0 < ttl <= 86400):
            raise ValueError("ttl must be an int or float in (0, 86400]")

    def acquire(self, key, ttl):
        self._validate_key(key)
        self._validate_ttl(ttl)
        now = self._clock()
        current = self._leases.get(key)
        if current is not None and now < current["expires_at"]:
            return None
        token = self._next_token
        self._next_token += 1
        self._leases[key] = {"token": token, "expires_at": now + ttl}
        return token

    def renew(self, key, token, ttl):
        self._validate_key(key)
        self._validate_ttl(ttl)
        now = self._clock()
        current = self._leases.get(key)
        if (current is None or not now < current["expires_at"]
                or type(token) is not int or token != current["token"]):
            return False
        current["expires_at"] = now + ttl
        return True

    def release(self, key, token):
        self._validate_key(key)
        now = self._clock()
        current = self._leases.get(key)
        if (current is None or not now < current["expires_at"]
                or type(token) is not int or token != current["token"]):
            return False
        del self._leases[key]
        return True

    def snapshot(self):
        now = self._clock()
        return {
            key: {"token": value["token"], "remaining": value["expires_at"] - now}
            for key, value in self._leases.items()
            if now < value["expires_at"]
        }
