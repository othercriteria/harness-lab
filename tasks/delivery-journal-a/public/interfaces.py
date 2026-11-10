"""Production interface shapes; behavior is specified in docs/."""

class DeliveryUncertain(Exception):
    """The remote outcome cannot be determined from this exception."""

class ProcessCrash(BaseException):
    """The process ends; implementation code must not catch this exception."""

class Store:
    def load(self, job_id):
        """Return a detached JSON-compatible record, or None if absent."""
        raise NotImplementedError

    def save(self, job_id, record):
        """Atomically and durably replace one record."""
        raise NotImplementedError

class Remote:
    def apply(self, request_id, payload):
        """Return None on acknowledged application, or raise DeliveryUncertain."""
        raise NotImplementedError
