from __future__ import annotations

import json
import re
from typing import Any, Dict

SENSITIVE_KEYS = {
    "apikey",
    "api_key",
    "secret",
    "apisecret",
    "api_secret",
    "passphrase",
    "password",
    "token",
    "masterkey",
    "master_key",
}

_REDACT_RE = re.compile(r"(?i)(api[_-]?key|api[_-]?secret|passphrase|master[_-]?key|token|password)")


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            if _REDACT_RE.search(str(k).replace(" ", "")):
                out[k] = "***REDACTED***"
            else:
                out[k] = redact_value(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redact_value(v) for v in value]
    if isinstance(value, str):
        if _REDACT_RE.search(value):
            return "***REDACTED***"
        return value
    return value


def redact_message(message: str) -> str:
    if not isinstance(message, str):
        return message
    return _REDACT_RE.sub("***REDACTED***", message)


def safe_json(data: Any) -> str:
    return json.dumps(redact_value(data), ensure_ascii=False)
