from __future__ import annotations

import re
from typing import Any, Dict, Tuple


SECRET_KEYS = {"api_key", "apikey", "token", "password", "authorization", "cookie"}


def redact(data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Simple redaction function:
    - Replaces values for known secret keys with "***REDACTED***"
    - Masks long high-entropy strings.
    Returns (redacted_copy, redaction_report).
    """

    def is_secret_key(key: str) -> bool:
        return key.lower() in SECRET_KEYS

    def mask_string(value: str) -> str:
        if len(value) > 12 and re.search(r"[A-Za-z0-9]{12,}", value):
            return "***REDACTED***"
        return value

    redacted: Dict[str, Any] = {}
    report: Dict[str, Any] = {"fields": []}

    for key, value in data.items():
        if isinstance(value, str):
            if is_secret_key(key):
                redacted[key] = "***REDACTED***"
                report["fields"].append({"key": key, "reason": "secret_key"})
            else:
                masked = mask_string(value)
                if masked != value:
                    redacted[key] = masked
                    report["fields"].append({"key": key, "reason": "high_entropy"})
                else:
                    redacted[key] = value
        else:
            redacted[key] = value

    return redacted, report

