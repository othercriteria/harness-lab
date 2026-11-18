"""Fixed-width feature-vector codec; complete the representation logic."""

_N_FLAGS = 8


def _validate_flags(flags):
    if not isinstance(flags, tuple) or len(flags) != _N_FLAGS:
        raise ValueError("flags must be a tuple of the required length")
    if any(type(flag) is not bool for flag in flags):
        raise ValueError("every flag must have exact type bool")


def _validate_payload(payload):
    if type(payload) is not bytes or len(payload) != 1:
        raise ValueError("payload must have exact type bytes and length 1")
    return payload[0]


def pack_flags(flags):
    _validate_flags(flags)
    raise NotImplementedError


def unpack_flags(payload):
    octet = _validate_payload(payload)
    raise NotImplementedError
