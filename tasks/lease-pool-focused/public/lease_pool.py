"""Small in-memory leases, using a caller-supplied clock."""


class LeasePool:
    def __init__(self, clock):
        self._clock = clock
        self._leases = {}
        self._next_token = 1

    def acquire(self, key, ttl):
        now = self._clock()
        token = self._next_token
        self._next_token += 1
        if key in self._leases:
            return None
        self._leases[key] = {"token": token, "expires_at": now + ttl}
        return token

    def renew(self, key, token, ttl):
        now = self._clock()
        if key not in self._leases:
            return False
        self._leases[key]["expires_at"] += ttl
        return True

    def release(self, key, token):
        self._clock()
        return self._leases.pop(key, None) is not None

    def snapshot(self):
        now = self._clock()
        return {key: {"token": value["token"], "remaining": value["expires_at"] - now}
                for key, value in self._leases.items()}
