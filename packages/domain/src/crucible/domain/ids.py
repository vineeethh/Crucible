"""Identifier generation.

UUIDv7 (time-sortable) for database primary keys so that inserts are
index-friendly and rows carry creation order (plan §5.3). Public IDs are
opaque UUID strings, never sequential integers.
"""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7: 48-bit big-endian unix_ts_ms + 74 bits of randomness."""
    ts_ms = int(time.time() * 1000)
    rand = os.urandom(10)
    b = bytearray(16)
    b[0:6] = ts_ms.to_bytes(6, "big")
    b[6:16] = rand
    b[6] = (b[6] & 0x0F) | 0x70  # version 7
    b[8] = (b[8] & 0x3F) | 0x80  # RFC 4122 variant
    return uuid.UUID(bytes=bytes(b))


def new_id() -> uuid.UUID:
    return uuid7()
