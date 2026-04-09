from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

MEXC_MAX_RECV_WINDOW_MS = 60_000
MEXC_SERVER_TIME_PATH = "/api/v3/time"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def utc_hour_bucket() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00Z")


def is_mexc_exchange(exchange: str) -> bool:
    return str(exchange or "").strip().lower() in {"mexc", "mexc3"}


def configure_mexc_client(client: Any, *, logger: Optional[logging.Logger] = None, context: str = "runtime") -> dict[str, Any]:
    diagnostics = _base_diagnostics(context)
    try:
        options = getattr(client, "options", None) or {}
        current = int(options.get("recvWindow", options.get("recvwindow", 5000)) or 5000)
        options["recvWindow"] = max(current, MEXC_MAX_RECV_WINDOW_MS)
        client.options = options
        diagnostics["recvWindow"] = int(options["recvWindow"])
    except Exception:
        pass
    diagnostics["timeDifferenceMs"] = _extract_time_difference_ms(client, diagnostics["timeDifferenceMs"])
    if logger is not None:
        logger.info(
            "MEXC_TIME_SYNC_APPLIED context=%s recvWindow=%s serverTimeEndpoint=%s timeDifferenceMs=%s clientUtc=%s",
            context,
            diagnostics["recvWindow"],
            diagnostics["serverTimeEndpoint"],
            diagnostics["timeDifferenceMs"],
            diagnostics["clientUtc"],
        )
    return diagnostics


async def configure_mexc_client_async(client: Any, *, logger: Optional[logging.Logger] = None, context: str = "runtime") -> dict[str, Any]:
    diagnostics = configure_mexc_client(client, logger=None, context=context)
    try:
        if hasattr(client, "load_time_difference"):
            maybe = await client.load_time_difference()
            if maybe is not None:
                diagnostics["timeDifferenceMs"] = _coerce_int(maybe)
        elif hasattr(client, "fetch_time"):
            server_time = await client.fetch_time()
            if server_time is not None:
                diagnostics["timeDifferenceMs"] = int(server_time) - int(time.time() * 1000)
    except Exception as exc:
        if logger is not None:
            logger.warning(
                "MEXC_TIME_SYNC_FAILED context=%s recvWindow=%s serverTimeEndpoint=%s error=%s",
                context,
                diagnostics["recvWindow"],
                diagnostics["serverTimeEndpoint"],
                exc,
            )
    diagnostics["timeDifferenceMs"] = _extract_time_difference_ms(client, diagnostics["timeDifferenceMs"])
    if logger is not None:
        logger.info(
            "MEXC_TIME_SYNC_APPLIED context=%s recvWindow=%s serverTimeEndpoint=%s timeDifferenceMs=%s clientUtc=%s",
            context,
            diagnostics["recvWindow"],
            diagnostics["serverTimeEndpoint"],
            diagnostics["timeDifferenceMs"],
            diagnostics["clientUtc"],
        )
    return diagnostics


def _base_diagnostics(context: str) -> dict[str, Any]:
    diagnostics = {
        "exchange": "mexc",
        "context": context,
        "recvWindow": MEXC_MAX_RECV_WINDOW_MS,
        "serverTimeEndpoint": MEXC_SERVER_TIME_PATH,
        "timeDifferenceMs": None,
        "clientUtc": utc_now_iso(),
    }
    return diagnostics


def classify_mexc_error(err: Exception) -> dict[str, Any]:
    msg = str(err or "").strip()
    low = msg.lower()
    category = "UNKNOWN"
    hint = None
    should_pause = False

    if any(key in low for key in ("700003", "recvwindow", "timestamp for this request", "timestamp outside")):
        category = "TIMESTAMP_WINDOW"
        hint = "sync_computer_clock_and_retry_get_api_v3_time"
    elif "permission denied" in low or "no permission" in low or "forbidden" in low:
        category = "PERMISSION_DENIED"
        hint = "enable_spot_read_and_trade_permissions_and_ip_whitelist"
    elif "api key info invalid" in low or "invalid api" in low or "api-key format invalid" in low:
        category = "AUTH_FAILED"
        hint = "verify_api_key_secret_and_signature"
        should_pause = True
    elif "signature" in low:
        category = "AUTH_FAILED"
        hint = "verify_api_key_secret_and_signature"
        should_pause = True
    elif "auth_failed" in low or "authentication" in low:
        category = "AUTH_FAILED"
        hint = "verify_api_key_secret_and_signature"
        should_pause = True
    elif "spot" in low and "futures" in low:
        category = "ACCOUNT_MODE_MISMATCH"
        hint = "use_spot_api_credentials_for_spot_private_endpoints"
    elif "account" in low and "spot" in low:
        category = "ACCOUNT_MODE_MISMATCH"
        hint = "use_spot_api_credentials_for_spot_private_endpoints"
    elif "ip" in low and ("restrict" in low or "whitelist" in low):
        category = "IP_RESTRICTED"
        hint = "add_server_ip_to_api_key_whitelist"

    return {
        "category": category,
        "hint": hint,
        "should_pause": should_pause,
        "message": msg,
    }


def log_mexc_error(
    logger: logging.Logger,
    *,
    context: str,
    operation: str,
    err: Exception,
    diagnostics: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    diagnostics = dict(diagnostics or {})
    classified = classify_mexc_error(err)
    logger.warning(
        "MEXC_DIAGNOSTIC context=%s operation=%s category=%s recvWindow=%s timeDifferenceMs=%s utcHour=%s clientUtc=%s serverTimeEndpoint=%s error=%s",
        context,
        operation,
        classified["category"],
        diagnostics.get("recvWindow", MEXC_MAX_RECV_WINDOW_MS),
        diagnostics.get("timeDifferenceMs"),
        utc_hour_bucket(),
        diagnostics.get("clientUtc", utc_now_iso()),
        diagnostics.get("serverTimeEndpoint", MEXC_SERVER_TIME_PATH),
        classified["message"],
    )
    return classified


def _extract_time_difference_ms(client: Any, fallback: Optional[int]) -> Optional[int]:
    for attr in ("timeDifference", "time_difference", "timeDifferenceMs"):
        value = getattr(client, attr, None)
        coerced = _coerce_int(value)
        if coerced is not None:
            return coerced
    options = getattr(client, "options", None)
    if isinstance(options, dict):
        for key in ("timeDifference", "time_difference", "timeDifferenceMs"):
            coerced = _coerce_int(options.get(key))
            if coerced is not None:
                return coerced
    return fallback


def _coerce_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None
