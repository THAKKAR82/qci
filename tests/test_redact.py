"""Credential redaction and error sanitization (ADR 0005, sections 4 and 5)."""

import copy

from pydantic import JsonValue

from qci.adapters.qiskit_ibm.redact import REDACTION_TAG, SENSITIVE_KEYS, redact_payload
from qci.core.hashing import canonical_json
from qci.services.run_service import sanitize_error_message

RULE_B_SENTINELS = {
    "crn": "crn:v1:bluemix:public:quantum-computing:us-east:a/SENTINEL-B-CRN::",
    "bearer": "Bearer SENTINEL-B-BEARER",
    "jwt": "eyJSENTINELBJWThdr.eyJSENTINELBJWTbody.SENTINELBJWTsig",
    "email": "SENTINEL-B-EMAIL@example.invalid",
    "url_userinfo": "https://me:SENTINEL-B-USERINFO@example.invalid/x",
    "url_query": "https://example.invalid/x?key=SENTINEL-B-QUERY",
}

CLEAN_QUBITS: JsonValue = [
    [
        {
            "name": "T1",
            "unit": "us",
            "value": 182.4,
            "date": {"$datetime": "2026-10-08T06:30:00+00:00"},
        }
    ]
]
CLEAN_GATE: JsonValue = {
    "gate": "cz",
    "qubits": [0, 1],
    "name": "cz0_1",
    "parameters": [{"name": "gate_error", "unit": "", "value": 0.003}],
}
CLEAN_GENERAL: JsonValue = [{"name": "jq_01", "unit": "GHz", "value": 0.002}]


def _rule_a_block(tag: str) -> dict[str, JsonValue]:
    # Mixed case proves case-insensitive key matching.
    return {
        key.upper() if i % 2 else key: f"SENTINEL-A-{tag}-{key}"
        for i, key in enumerate(sorted(SENSITIVE_KEYS))
    }


def _payload() -> dict[str, JsonValue]:
    sentinel_parameters: list[JsonValue] = [
        {"name": rule, "unit": "", "value": value} for rule, value in RULE_B_SENTINELS.items()
    ]
    sentinel_parameters.append(_rule_a_block("gateparam"))
    return {
        "properties": {
            "qubits": copy.deepcopy(CLEAN_QUBITS),
            "gates": [
                copy.deepcopy(CLEAN_GATE),
                {
                    "gate": "sx",
                    "qubits": [0],
                    "name": "sx0",
                    "parameters": sentinel_parameters,
                },
            ],
            "general": copy.deepcopy(CLEAN_GENERAL),
        },
        "configuration": {
            **_rule_a_block("top"),
            "nested": {"deeper": [_rule_a_block("list"), list(RULE_B_SENTINELS.values())]},
            "account": {"token": "SENTINEL-A-nested-token"},
            "description": "a 156 qubit device",
        },
    }


def _tag_paths(value: JsonValue, path: str = "$") -> list[str]:
    if isinstance(value, dict):
        if set(value) == {REDACTION_TAG}:
            return [path]
        return [p for k, v in value.items() for p in _tag_paths(v, f"{path}.{k}")]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in _tag_paths(v, f"{path}[{i}]")]
    return []


def test_redaction_removes_sentinels() -> None:
    payload = _payload()
    before = canonical_json(payload)
    redacted, paths = redact_payload(payload)

    assert canonical_json(payload) == before, "input must not be mutated"
    out = canonical_json(redacted)
    assert b"SENTINEL" not in out
    assert sorted(paths) == sorted(_tag_paths(redacted))
    assert len(paths) == len(set(paths))
    # 22 keys x 3 blocks, 6 strings x 2 places, and the nested "account" mapping.
    assert len(paths) == len(SENSITIVE_KEYS) * 3 + len(RULE_B_SENTINELS) * 2 + 1
    assert "$.configuration.account" in paths
    assert "$.properties.gates[1].parameters[0].value" in paths

    assert isinstance(redacted, dict)
    props = redacted["properties"]
    assert isinstance(props, dict)
    assert canonical_json(props["qubits"]) == canonical_json(CLEAN_QUBITS)
    assert canonical_json(props["general"]) == canonical_json(CLEAN_GENERAL)
    gates = props["gates"]
    assert isinstance(gates, list)
    assert canonical_json(gates[0]) == canonical_json(CLEAN_GATE)


def test_redaction_is_idempotent_and_reports_nothing_the_second_time() -> None:
    once, paths = redact_payload(_payload())
    twice, again = redact_payload(once)
    assert twice == once
    assert paths and again == []


def test_redaction_tags_name_the_rule() -> None:
    redacted, _ = redact_payload({"token": "x", "note": RULE_B_SENTINELS["jwt"], "ok": 1.5})
    assert redacted == {"token": {REDACTION_TAG: "key"}, "note": {REDACTION_TAG: "jwt"}, "ok": 1.5}


def test_rule_a_key_with_null_or_number_is_still_redacted() -> None:
    redacted, paths = redact_payload({"url": None, "hub": 3})
    assert redacted == {"url": {REDACTION_TAG: "key"}, "hub": {REDACTION_TAG: "key"}}
    assert paths == ["$.url", "$.hub"]


def test_unusual_keys_get_quoted_paths() -> None:
    _, paths = redact_payload({"a.b": {"token": "x"}})
    assert paths == ['$["a.b"].token']


def test_sanitize_error_message_redacts_crn_bearer_and_jwt() -> None:
    message = (
        f"403 for instance {RULE_B_SENTINELS['crn']} with header "
        f"Authorization: Bearer SENTINEL-TOKEN and jwt {RULE_B_SENTINELS['jwt']} "
        "via https://user:SENTINEL-PW@example.invalid/x"
    )
    cleaned = sanitize_error_message(message)
    assert "SENTINEL" not in cleaned
    assert "[redacted crn]" in cleaned
    assert "Bearer [redacted]" in cleaned
    assert "[redacted jwt]" in cleaned
    assert "https://example.invalid/x" in cleaned
