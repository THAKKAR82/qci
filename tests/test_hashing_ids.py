import math
import re

import pytest

from qci.core.hashing import canonical_json, hash_json
from qci.core.ids import new_run_id
from qci.domain.circuit import CompileConfig

ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def test_canonical_json_ignores_key_order_and_whitespace() -> None:
    a = {"b": 1, "a": {"y": [1, 2], "x": "é"}}
    b = {"a": {"x": "é", "y": [1, 2]}, "b": 1}
    assert canonical_json(a) == canonical_json(b)
    assert canonical_json(a) == '{"a":{"x":"é","y":[1,2]},"b":1}'.encode()


def test_canonical_json_rejects_non_finite_floats() -> None:
    with pytest.raises(ValueError):
        canonical_json({"x": math.nan})


def test_hash_json_is_prefixed_stable_and_accepts_models() -> None:
    config = CompileConfig(optimization_level=1, seed_transpiler=7)
    digest = hash_json(config)
    assert digest.startswith("sha256:") and len(digest) == len("sha256:") + 64
    assert digest == hash_json({"seed_transpiler": 7, "optimization_level": 1})
    assert digest != hash_json(CompileConfig(optimization_level=1, seed_transpiler=8))


def test_run_ids_are_well_formed_unique_and_monotonic() -> None:
    ids = [new_run_id() for _ in range(2000)]
    assert all(ULID_RE.match(i) for i in ids)
    assert len(set(ids)) == len(ids)
    assert ids == sorted(ids)


def test_run_ids_sort_by_time() -> None:
    later = new_run_id(now_ms=4_000_000_000_000)
    much_later = new_run_id(now_ms=4_000_000_000_001)
    assert later < much_later
    assert later[:10] != much_later[:10]


def test_run_id_rejects_out_of_range_time() -> None:
    with pytest.raises(ValueError):
        new_run_id(now_ms=-1)
