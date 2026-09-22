from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

MASK = "***REDACTED***"

SECRET_KEY_PARTS = (
    "api_key", "apikey", "token", "password", "passwd", "secret",
    "authorization", "cookie", "private_key", "credential",
)

# Known credential shapes: OpenAI/Anthropic sk-, Slack xox?-, GitHub ghp_/gho_,
# AWS AKIA, JWT header.payload.
_KNOWN_SECRET = re.compile(
    r"sk-[A-Za-z0-9_\-]{16,}"
    r"|xox[abpr]-[A-Za-z0-9\-]{10,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|AKIA[A-Z0-9]{16}"
    r"|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"
)
# Generic high-entropy run: 20+ token chars mixing letters and digits.
# ponytail: heuristic, not entropy math. Ordinary prose never matches (words
# have no digits); hashes, container ids and API keys do. Date-stamped file
# names may get masked — safe direction. Tighten with a real entropy score
# if false positives bite.
_TOKEN_RUN = re.compile(r"[A-Za-z0-9_\-]{20,}")


def is_secret_key(key: str) -> bool:
    k = key.lower()
    return any(part in k for part in SECRET_KEY_PARTS)


def _looks_secret(run: str) -> bool:
    digits = sum(c.isdigit() for c in run)
    letters = sum(c.isalpha() for c in run)
    return digits >= 3 and letters >= 3


def mask_string(value: str) -> str:
    """Mask only the secret-looking spans, keep surrounding prose readable."""
    value = _KNOWN_SECRET.sub(MASK, value)
    return _TOKEN_RUN.sub(lambda m: MASK if _looks_secret(m.group()) else m.group(), value)


def redact(data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return (redacted_copy, report). Walks nested dicts and lists.

    - Values under secret-looking keys are fully masked.
    - Secret-looking spans inside other strings are masked in place.
    """
    report: Dict[str, List[Dict[str, str]]] = {"fields": []}

    def walk(value: Any, path: str) -> Any:
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                child = f"{path}.{k}" if path else str(k)
                if is_secret_key(str(k)) and v not in (None, ""):
                    out[k] = MASK
                    report["fields"].append({"key": child, "reason": "secret_key"})
                else:
                    out[k] = walk(v, child)
            return out
        if isinstance(value, list):
            return [walk(v, f"{path}[{i}]") for i, v in enumerate(value)]
        if isinstance(value, str):
            masked = mask_string(value)
            if masked != value:
                report["fields"].append({"key": path, "reason": "high_entropy"})
            return masked
        return value

    return walk(data, ""), report
