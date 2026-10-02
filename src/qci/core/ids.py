"""Run identifiers: 26-character, time-sortable, random (ULID layout).

48 bits of millisecond Unix time followed by 80 random bits, Crockford base32 encoded.
Within one process, IDs are strictly increasing even when generated in the same millisecond.
"""

import secrets
import threading
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_RANDOM_BITS = 80
_MAX_RANDOM = (1 << _RANDOM_BITS) - 1

_lock = threading.Lock()
_last_ms = -1
_last_random = 0


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_run_id(now_ms: int | None = None) -> str:
    """Generate a new run ID. ``now_ms`` overrides the clock (for tests)."""
    global _last_ms, _last_random
    ms = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    if not 0 <= ms < (1 << 48):
        raise ValueError("timestamp out of range for a run id")
    with _lock:
        if ms <= _last_ms:
            # Same (or earlier, if the clock went backwards) millisecond: stay monotonic.
            ms = _last_ms
            if _last_random >= _MAX_RANDOM:
                ms += 1
                rand = secrets.randbits(_RANDOM_BITS)
            else:
                rand = _last_random + 1
        else:
            rand = secrets.randbits(_RANDOM_BITS)
        _last_ms, _last_random = ms, rand
    return _encode(ms, 10) + _encode(rand, 16)
