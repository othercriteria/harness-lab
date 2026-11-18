def pack_flags(flags):
    if not isinstance(flags, tuple) or len(flags) != 8 or any(type(v) is not bool for v in flags):
        raise ValueError('expected eight Boolean flags')
    value=0
    for i, flag in enumerate(flags):
        if flag: value |= 1 << i
    return bytes([value])

def unpack_flags(payload):
    if type(payload) is not bytes or len(payload) != 1:
        raise ValueError('expected one byte')
    return tuple(bool(payload[0] & (1 << i)) for i in range(8))
