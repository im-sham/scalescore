from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping

_RAW_PAYLOAD_KEY_TERMS = (
    "payload",
    "raw_payload",
    "source_payload",
    "document_text",
    "claim_text",
    "claim_payload",
    "payment_payload",
    "phi",
    "ssn",
    "dob",
    "member_id",
    "patient_name",
    "authorization",
    "api_key",
    "secret",
)
_CREDENTIAL_TOKEN_PATTERN = r"(?:credential|credentials|access_token|refresh_token|token)"
_RAW_PAYLOAD_KEY_PATTERN = re.compile(
    r"(?i)(?:^|[\s,{\"'])("
    + "|".join(re.escape(term) for term in _RAW_PAYLOAD_KEY_TERMS)
    + r"|"
    + _CREDENTIAL_TOKEN_PATTERN
    + r")\s*[:=]"
)


def summary_only_text_violations(
    fields: Mapping[str, str | Iterable[str] | None],
) -> dict[str, list[str]]:
    """Find obvious raw/sensitive payload markers in summary-only text fields."""

    violations: dict[str, list[str]] = {}
    for field_name, raw_values in fields.items():
        for value in _iter_text_values(raw_values):
            reasons = _summary_only_text_reasons(value)
            if reasons:
                violations.setdefault(field_name, []).extend(reasons)
    return violations


def _iter_text_values(values: str | Iterable[str] | None) -> Iterable[str]:
    if values is None:
        return ()
    if isinstance(values, str):
        return (values,)
    return (value for value in values if value)


def _summary_only_text_reasons(value: str) -> list[str]:
    text = value.strip()
    if not text:
        return []

    reasons: list[str] = []
    if _looks_like_json_payload(text):
        reasons.append("payload_shaped_json")
    if _RAW_PAYLOAD_KEY_PATTERN.search(text):
        reasons.append("raw_payload_key")
    return reasons


def _looks_like_json_payload(text: str) -> bool:
    if not (
        (text.startswith("{") and text.endswith("}"))
        or (text.startswith("[") and text.endswith("]"))
    ):
        return False
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return False
    return True
