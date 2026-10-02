"""Lossless conversion of provider payloads to JSON-compatible values.

Provider payloads contain Python types JSON cannot represent. They are encoded with explicit
tags so that no information is lost and decoding is unambiguous:

- ``datetime``  -> ``{"$datetime": "<ISO-8601 with offset>"}``
- ``complex``   -> ``{"$complex": [real, imag]}``
- non-finite float -> ``{"$float": "nan" | "inf" | "-inf"}``
- tuple         -> list
- numpy scalar  -> the equivalent Python scalar (via ``.item()``)

Any other type raises ``TypeError``: unknown data is never silently dropped or stringified.
"""

import math
from datetime import date, datetime
from typing import Any

from pydantic import JsonValue


def to_jsonable(value: Any) -> JsonValue:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return {"$float": "nan" if math.isnan(value) else ("inf" if value > 0 else "-inf")}
    if isinstance(value, complex):
        return {"$complex": [to_jsonable(value.real), to_jsonable(value.imag)]}
    if isinstance(value, datetime | date):
        return {"$datetime": value.isoformat()}
    if isinstance(value, dict):
        out: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"non-string mapping key {key!r} ({type(key).__name__})")
            out[key] = to_jsonable(item)
        return out
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    item_method = getattr(value, "item", None)
    if callable(item_method) and type(value).__module__ == "numpy":
        return to_jsonable(item_method())
    raise TypeError(f"cannot losslessly convert {type(value).__module__}.{type(value).__name__}")
