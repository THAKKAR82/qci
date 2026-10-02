"""Canonical JSON and SHA-256 helpers.

Hashes produced here are *convenience* hashes for quickly spotting identical configurations.
They are not canonical identities (see docs/data-model.md).
"""

import hashlib
import json
from typing import Any

from pydantic import BaseModel

HASH_PREFIX = "sha256:"


def canonical_json(value: Any) -> bytes:
    """Serialize to canonical JSON bytes: sorted keys, compact, UTF-8, no NaN/Infinity.

    Pydantic models are dumped in JSON mode first.
    """
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_json(value: Any) -> str:
    """Return ``sha256:<hex>`` over the canonical JSON of ``value``."""
    return HASH_PREFIX + sha256_hex(canonical_json(value))
