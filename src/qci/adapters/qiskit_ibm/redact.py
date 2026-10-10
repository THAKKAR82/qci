"""Credential redaction for captured provider payloads (ADR 0005, section 4).

Pure JSON walking; no Qiskit import. A replaced value becomes ``{"$redacted": "<rule>"}`` and
its JSON path is reported. The value itself is never kept. Redaction is idempotent: an existing
tag is left alone and not reported again.

- Rule (a): the value of any mapping key in ``SENSITIVE_KEYS``, matched case-insensitively.
- Rule (b): any string, under any key, that contains ``crn:``, starts with ``Bearer``, has the
  JWT shape, looks like an email address, or is a URL with user-info or a query string.
"""

import re

from pydantic import JsonValue

REDACTION_TAG = "$redacted"

SENSITIVE_KEYS = frozenset(
    {
        "token",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "authorization",
        "password",
        "secret",
        "instance",
        "instance_id",
        "crn",
        "account",
        "account_id",
        "iam_id",
        "user_id",
        "email",
        "hub",
        "group",
        "project",
        "url",
        "endpoint",
        "proxies",
    }
)

KEY_RULE = "key"

_STRING_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("crn", re.compile(r"crn:", re.IGNORECASE)),
    ("bearer", re.compile(r"^\s*bearer\s", re.IGNORECASE)),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")),
    ("url_userinfo", re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^/\s@?#]+@")),
    ("url_query", re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s?#]*\?")),
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_redaction_tag(value: JsonValue) -> bool:
    return isinstance(value, dict) and len(value) == 1 and isinstance(value.get(REDACTION_TAG), str)


def string_rule(value: str) -> str | None:
    """The rule (b) name a string matches, or None."""
    for name, pattern in _STRING_RULES:
        if pattern.search(value):
            return name
    return None


def child_path(path: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]"
    if _IDENTIFIER.match(key):
        return f"{path}.{key}"
    escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    return f'{path}["{escaped}"]'


def _redact(value: JsonValue, path: str, found: list[str]) -> JsonValue:
    if is_redaction_tag(value):
        return value
    if isinstance(value, dict):
        out: dict[str, JsonValue] = {}
        for key, item in value.items():
            item_path = child_path(path, key)
            if key.lower() in SENSITIVE_KEYS and not is_redaction_tag(item):
                out[key] = {REDACTION_TAG: KEY_RULE}
                found.append(item_path)
            else:
                out[key] = _redact(item, item_path, found)
        return out
    if isinstance(value, list):
        return [_redact(item, child_path(path, i), found) for i, item in enumerate(value)]
    if isinstance(value, str) and (rule := string_rule(value)) is not None:
        found.append(path)
        return {REDACTION_TAG: rule}
    return value


def redact_payload(value: JsonValue, path: str = "$") -> tuple[JsonValue, list[str]]:
    """Return the redacted copy of ``value`` and the JSON paths that were replaced."""
    found: list[str] = []
    return _redact(value, path, found), found
