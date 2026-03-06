from __future__ import annotations

import configparser
import logging
import time
import uuid
from typing import Any, Optional

import ccxt
from flask import Blueprint, jsonify, request, g

from api.auth import extract_auth_context
from api.rate_limit import InMemoryRateLimiter
from core.credentials_service import (
    CredentialsConflictError,
    CredentialsNotFoundError,
    ExchangeCredentialsService,
)
from security.redaction import redact_value

exchange_credentials_bp = Blueprint("exchange_credentials", __name__)

ALLOWED_EXCHANGES = ("mexc", "gateio", "gate", "novadax", "mercadobitcoin", "binance", "bybit", "okx", "kucoin")
ALLOWED_STATUS = {"ACTIVE", "INACTIVE", "REVOKED"}
LABEL_ALLOWED_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ._-")
PROBE_SYMBOLS_BY_EXCHANGE = {
    "novadax": ("BTC/BRL", "ETH/BRL", "USDT/BRL"),
    "mercadobitcoin": ("BTC/BRL", "ETH/BRL", "USDT/BRL"),
    "gateio": ("BTC/USDT", "ETH/USDT"),
    "gate": ("BTC/USDT", "ETH/USDT"),
    "mexc": ("BTC/USDT", "ETH/USDT"),
    "binance": ("BTC/USDT", "ETH/USDT"),
    "bybit": ("BTC/USDT", "ETH/USDT"),
    "okx": ("BTC/USDT", "ETH/USDT"),
    "kucoin": ("BTC/USDT", "ETH/USDT"),
}

rate_limiter = InMemoryRateLimiter()
log = logging.getLogger("exchange_credentials_api")


class ValidationError(RuntimeError):
    def __init__(self, message: str, details: list[dict[str, str]]):
        super().__init__(message)
        self.details = details


def _service() -> ExchangeCredentialsService:
    cfg = configparser.ConfigParser()
    cfg["GLOBAL"] = {"SQLITE_PATH": g.db_path}
    return ExchangeCredentialsService(cfg)


def _error(status: int, error: str, message: str, details: Optional[list[dict[str, str]]] = None):
    return (
        jsonify(
            {
                "error": error,
                "message": message,
                "details": details or [],
                "correlationId": g.correlation_id,
            }
        ),
        status,
    )


def _authorize(tenant_id: str, required_roles: set[str]):
    ctx = extract_auth_context(request)
    if not ctx:
        return None, _error(401, "UNAUTHORIZED", "Authentication required")
    if ctx.tenant_id != tenant_id:
        return None, _error(403, "FORBIDDEN", "Tenant access denied")
    if required_roles and not (ctx.roles & required_roles):
        return None, _error(403, "FORBIDDEN", "Insufficient role")
    return ctx, None


def _apply_rate_limit(route_key: str, limit: int, period_sec: int):
    tenant_id = request.view_args.get("tenantId", "") if request.view_args else ""
    user_id = request.headers.get("X-User-Id", "anonymous")
    ip = request.headers.get("X-Forwarded-For") or request.remote_addr or "unknown"
    key = f"{route_key}:{tenant_id}:{user_id}:{ip}"
    result = rate_limiter.check(key, limit, period_sec)
    if not result.allowed:
        return _error(429, "RATE_LIMIT", "Rate limit exceeded", [{"field": "rateLimit", "issue": "too_many_requests"}])
    return None


def _validate_payload_create(payload: dict[str, Any]):
    details = []
    exchange = str(payload.get("exchange", "")).strip().lower()
    label = str(payload.get("label", "")).strip()
    api_key = str(payload.get("apiKey", "")).strip()
    api_secret = str(payload.get("apiSecret", "")).strip()
    passphrase = payload.get("passphrase")

    if exchange not in ALLOWED_EXCHANGES:
        details.append({"field": "exchange", "issue": "invalid_exchange"})
    if len(label) < 2 or len(label) > 64:
        details.append({"field": "label", "issue": "invalid_length"})
    if any(c not in LABEL_ALLOWED_CHARS for c in label):
        details.append({"field": "label", "issue": "invalid_chars"})
    if len(api_key) < 8 or len(api_key) > 256:
        details.append({"field": "apiKey", "issue": "invalid_length"})
    if len(api_secret) < 8 or len(api_secret) > 512:
        details.append({"field": "apiSecret", "issue": "invalid_length"})
    if passphrase is not None and len(str(passphrase).strip()) > 256:
        details.append({"field": "passphrase", "issue": "invalid_length"})

    if details:
        raise ValidationError("Invalid payload", details)

    return {
        "exchange": exchange,
        "label": label,
        "api_key": api_key,
        "api_secret": api_secret,
        "passphrase": None if passphrase is None else str(passphrase).strip(),
    }


def _validate_payload_update(payload: dict[str, Any]):
    details = []
    out: dict[str, Any] = {}
    if "label" in payload:
        label = str(payload.get("label", "")).strip()
        if len(label) < 2 or len(label) > 64:
            details.append({"field": "label", "issue": "invalid_length"})
        if any(c not in LABEL_ALLOWED_CHARS for c in label):
            details.append({"field": "label", "issue": "invalid_chars"})
        out["label"] = label
    if "status" in payload:
        status = str(payload.get("status", "")).strip().upper()
        if status not in ALLOWED_STATUS:
            details.append({"field": "status", "issue": "invalid_status"})
        out["status"] = status
    if "apiKey" in payload:
        api_key = str(payload.get("apiKey", "")).strip()
        if len(api_key) < 8 or len(api_key) > 256:
            details.append({"field": "apiKey", "issue": "invalid_length"})
        out["api_key"] = api_key
    if "apiSecret" in payload:
        api_secret = str(payload.get("apiSecret", "")).strip()
        if len(api_secret) < 8 or len(api_secret) > 512:
            details.append({"field": "apiSecret", "issue": "invalid_length"})
        out["api_secret"] = api_secret
    if "passphrase" in payload:
        passphrase = payload.get("passphrase")
        if passphrase is not None and len(str(passphrase).strip()) > 256:
            details.append({"field": "passphrase", "issue": "invalid_length"})
        out["passphrase"] = None if passphrase is None else str(passphrase).strip()

    if details:
        raise ValidationError("Invalid payload", details)
    return out


def _parse_credential_id(raw_id: str) -> int:
    try:
        return int(raw_id)
    except Exception as exc:
        raise ValidationError("Invalid id", [{"field": "id", "issue": "not_integer"}]) from exc


def _exchange_candidates(exchange: str) -> list[str]:
    low = str(exchange or "").strip().lower()
    if low in {"gateio", "gate"}:
        return ["gateio", "gate"]
    if low in {"mexc", "mexc3"}:
        return ["mexc", "mexc3"]
    if low == "mercadobitcoin":
        return ["mercadobitcoin", "mercado"]
    return [low]


def _classify_exchange_test_error(exc: Exception) -> tuple[str, str, Optional[str]]:
    if isinstance(exc, (ccxt.RequestTimeout, ccxt.NetworkError)):
        return "EXCHANGE_TEST_TIMEOUT", "TIMEOUT", "check_internet_or_exchange_status"
    if isinstance(exc, ccxt.PermissionDenied):
        return "EXCHANGE_PERMISSION_DENIED", "PERMISSION_DENIED", "enable_trade_and_orders_permission"
    if isinstance(exc, ccxt.AuthenticationError):
        return "EXCHANGE_AUTH_FAILED", "AUTH_FAILED", "verify_api_key_secret_and_passphrase"
    if isinstance(exc, ccxt.InvalidNonce):
        return "EXCHANGE_TIMESTAMP_WINDOW", "TIMESTAMP_WINDOW", "sync_computer_clock_and_retry"
    if isinstance(exc, ccxt.NotSupported):
        return "EXCHANGE_TRADE_PROBE_UNAVAILABLE", "TRADE_PROBE_UNAVAILABLE", "exchange_has_no_private_probe_endpoint"

    msg = str(exc).lower()
    if any(k in msg for k in ("timeout", "timed out", "network error", "connection")):
        return "EXCHANGE_TEST_TIMEOUT", "TIMEOUT", "check_internet_or_exchange_status"
    if any(k in msg for k in ("recvwindow", "timestamp", "nonce", "timing")):
        return "EXCHANGE_TIMESTAMP_WINDOW", "TIMESTAMP_WINDOW", "sync_computer_clock_and_retry"
    if any(k in msg for k in ("no permission", "permission", "forbidden", "not allowed")):
        return "EXCHANGE_PERMISSION_DENIED", "PERMISSION_DENIED", "enable_trade_and_orders_permission"
    if any(k in msg for k in ("invalid api", "invalid key", "api-key", "apikey", "auth", "signature", "passphrase")):
        return "EXCHANGE_AUTH_FAILED", "AUTH_FAILED", "verify_api_key_secret_and_passphrase"
    if "unsupported exchange" in msg:
        return "EXCHANGE_UNSUPPORTED", "UNSUPPORTED_EXCHANGE", None
    if "trade_probe_unavailable" in msg:
        return "EXCHANGE_TRADE_PROBE_UNAVAILABLE", "TRADE_PROBE_UNAVAILABLE", "exchange_has_no_private_probe_endpoint"
    return "EXCHANGE_TEST_FAILED", "UNKNOWN", None


def _short_error_message(exc: Exception) -> str:
    msg = str(exc or "").replace("\n", " ").replace("\r", " ").strip()
    if not msg:
        return "unexpected_error"
    if len(msg) > 240:
        return msg[:237] + "..."
    return msg


def _pick_probe_symbol(exchange_low: str, markets: dict[str, Any]) -> Optional[str]:
    if not isinstance(markets, dict) or not markets:
        return None

    preferred = PROBE_SYMBOLS_BY_EXCHANGE.get(exchange_low, ())
    for symbol in preferred:
        m = markets.get(symbol)
        if isinstance(m, dict) and m.get("active", True):
            return symbol

    for symbol, meta in markets.items():
        if not isinstance(meta, dict):
            continue
        if meta.get("active", True) is False:
            continue
        if meta.get("spot", True) is False:
            continue
        upper_symbol = str(symbol or "").upper()
        if upper_symbol.endswith("/USDT") or upper_symbol.endswith("/BRL") or upper_symbol.endswith("/USD"):
            return str(symbol)

    for symbol in markets.keys():
        return str(symbol)
    return None


def _probe_private_method(client: Any, method_name: str, probe_symbol: Optional[str]) -> tuple[bool, Optional[str]]:
    fn = getattr(client, method_name, None)
    if not callable(fn):
        return False, None

    if probe_symbol:
        try:
            fn(probe_symbol)
            return True, f"{method_name}(symbol)"
        except ccxt.BadSymbol:
            pass
        except ccxt.NotSupported:
            return False, None
        except TypeError:
            try:
                fn(probe_symbol, None, 1)
                return True, f"{method_name}(symbol,limit)"
            except ccxt.BadSymbol:
                pass
            except ccxt.NotSupported:
                return False, None
            except TypeError:
                pass
            except Exception:
                raise
        except Exception:
            raise

    try:
        fn()
        return True, f"{method_name}()"
    except ccxt.NotSupported:
        return False, None
    except TypeError:
        try:
            fn(None, None, 1)
            return True, f"{method_name}(none,limit)"
        except ccxt.NotSupported:
            return False, None
        except TypeError:
            return False, None
        except Exception:
            raise
    except Exception:
        raise


def _run_trade_probe(client: Any, probe_symbol: Optional[str]) -> tuple[bool, Optional[str]]:
    for method_name in ("fetch_open_orders", "fetch_orders", "fetch_my_trades"):
        ok, probe_method = _probe_private_method(client, method_name, probe_symbol)
        if ok:
            return True, probe_method
    return False, None


def _build_failure_message(category: Optional[str], hint: Optional[str]) -> str:
    base_map = {
        "AUTH_FAILED": "Credencial rejeitada pela exchange (API key/secret/passphrase invalidos).",
        "PERMISSION_DENIED": "Credencial sem permissao para endpoints privados de ordens.",
        "TIMESTAMP_WINDOW": "Falha de timestamp (hora local fora da janela da exchange).",
        "TIMEOUT": "Timeout de comunicacao com a exchange durante validacao.",
        "TRADE_PROBE_UNAVAILABLE": "Nao foi possivel validar endpoint privado de ordens nesta exchange.",
        "UNSUPPORTED_EXCHANGE": "Exchange nao suportada para validacao automatica.",
    }
    msg = base_map.get(str(category or "").upper(), "Falha ao validar credencial na exchange.")
    if hint:
        return f"{msg} Hint: {hint}."
    return msg


def _test_exchange_connection(exchange: str, api_key: str, api_secret: str, passphrase: Optional[str]) -> dict[str, Any]:
    started = time.time()
    client = None
    low = str(exchange or "").strip().lower()
    result: dict[str, Any] = {
        "ok": False,
        "latency_ms": 0,
        "error_code": None,
        "category": None,
        "hint": None,
        "probe_symbol": None,
        "probe_method": None,
        "error_message": None,
    }
    try:
        candidates = _exchange_candidates(low)

        for candidate in candidates:
            if hasattr(ccxt, candidate):
                cls = getattr(ccxt, candidate)
                client = cls(
                    {
                        "apiKey": api_key,
                        "secret": api_secret,
                        "password": passphrase,
                        "enableRateLimit": True,
                        "timeout": 10_000,
                        "options": {"defaultType": "spot", "recvWindow": 60_000},
                    }
                )
                break

        if client is None:
            raise RuntimeError(f"unsupported exchange: {exchange}")

        markets: dict[str, Any] = {}
        if hasattr(client, "load_markets"):
            loaded = client.load_markets()
            if isinstance(loaded, dict):
                markets = loaded
            elif isinstance(getattr(client, "markets", None), dict):
                markets = getattr(client, "markets")

        if low in {"mexc", "mexc3"} and hasattr(client, "load_time_difference"):
            try:
                client.load_time_difference()
            except Exception:
                pass

        if hasattr(client, "fetch_balance"):
            client.fetch_balance()
        elif hasattr(client, "fetch_time"):
            client.fetch_time()

        probe_symbol = _pick_probe_symbol(low, markets)
        result["probe_symbol"] = probe_symbol

        trade_ready, probe_method = _run_trade_probe(client, probe_symbol)
        result["probe_method"] = probe_method
        if not trade_ready:
            raise RuntimeError("trade_probe_unavailable")

        result["ok"] = True
        return result
    except Exception as exc:
        error_code, category, hint = _classify_exchange_test_error(exc)
        result["ok"] = False
        result["error_code"] = error_code
        result["category"] = category
        result["hint"] = hint
        result["error_message"] = _short_error_message(exc)
        return result
    finally:
        result["latency_ms"] = int((time.time() - started) * 1000)
        if client is not None:
            try:
                if hasattr(client, "close"):
                    client.close()
            except Exception:
                pass


@exchange_credentials_bp.route("/api/tenants/<tenantId>/exchange-credentials", methods=["GET"])
def list_credentials(tenantId: str):
    ctx, err = _authorize(tenantId, {"ADMIN", "VIEWER"})
    if err:
        return err
    service = _service()
    items = service.list_credentials(tenantId)
    return jsonify(
        {
            "items": [
                {
                    "id": item.id,
                    "exchange": item.exchange,
                    "label": item.label,
                    "last4": item.last4,
                    "status": item.status,
                    "updatedAt": item.updated_at,
                }
                for item in items
            ],
            "count": len(items),
        }
    )


@exchange_credentials_bp.route("/api/tenants/<tenantId>/exchanges/status", methods=["GET"])
def list_exchange_status(tenantId: str):
    ctx, err = _authorize(tenantId, {"ADMIN", "VIEWER"})
    if err:
        return err
    service = _service()
    items = service.list_exchange_status(tenantId)
    return jsonify(
        {
            "items": [
                {
                    "tenantId": item.tenant_id,
                    "exchange": item.exchange,
                    "label": item.label,
                    "status": item.status,
                    "credentialId": item.credential_id,
                    "credentialVersion": item.credential_version,
                    "lastTestOk": item.last_test_ok,
                    "lastTestAt": item.last_test_at,
                    "lastTestLatencyMs": item.last_test_latency_ms,
                    "lastErrorCode": item.last_error_code,
                    "lastErrorCategory": item.last_error_category,
                    "updatedAt": item.updated_at,
                }
                for item in items
            ],
            "count": len(items),
        }
    )


@exchange_credentials_bp.route("/api/tenants/<tenantId>/exchange-credentials", methods=["POST"])
def create_credentials(tenantId: str):
    rl = _apply_rate_limit("create_credentials", 5, 60)
    if rl:
        return rl
    ctx, err = _authorize(tenantId, {"ADMIN"})
    if err:
        return err
    payload = request.get_json(force=True, silent=True) or {}
    try:
        valid = _validate_payload_create(payload)
        created = _service().create_credentials(
            tenant_id=tenantId,
            exchange=valid["exchange"],
            label=valid["label"],
            api_key=valid["api_key"],
            api_secret=valid["api_secret"],
            passphrase=valid["passphrase"],
            user_id=ctx.user_id,
        )
    except ValidationError as exc:
        return _error(400, "VALIDATION_ERROR", str(exc), exc.details)
    except CredentialsConflictError:
        return _error(409, "CONFLICT", "Credential already exists")

    return (
        jsonify(
            {
                "id": created.id,
                "exchange": created.exchange,
                "label": created.label,
                "last4": created.last4,
                "status": created.status,
                "updatedAt": created.updated_at,
            }
        ),
        201,
    )


@exchange_credentials_bp.route("/api/tenants/<tenantId>/exchange-credentials/<id>", methods=["PUT"])
def update_credentials(tenantId: str, id: str):
    rl = _apply_rate_limit("update_credentials", 10, 60)
    if rl:
        return rl
    ctx, err = _authorize(tenantId, {"ADMIN"})
    if err:
        return err
    payload = request.get_json(force=True, silent=True) or {}
    try:
        credential_id = _parse_credential_id(id)
        valid = _validate_payload_update(payload)
        updated = _service().update_credentials(
            tenant_id=tenantId,
            credential_id=credential_id,
            label=valid.get("label"),
            status=valid.get("status"),
            api_key=valid.get("api_key"),
            api_secret=valid.get("api_secret"),
            passphrase=valid.get("passphrase"),
            user_id=ctx.user_id,
        )
    except ValidationError as exc:
        return _error(400, "VALIDATION_ERROR", str(exc), exc.details)
    except CredentialsNotFoundError:
        return _error(404, "NOT_FOUND", "Credential not found")

    return jsonify(
        {
            "id": updated.id,
            "exchange": updated.exchange,
            "label": updated.label,
            "last4": updated.last4,
            "status": updated.status,
            "updatedAt": updated.updated_at,
        }
    )


@exchange_credentials_bp.route("/api/tenants/<tenantId>/exchange-credentials/<id>", methods=["DELETE"])
def revoke_credentials(tenantId: str, id: str):
    ctx, err = _authorize(tenantId, {"ADMIN"})
    if err:
        return err
    try:
        credential_id = _parse_credential_id(id)
        _service().revoke_credentials(tenantId, credential_id, ctx.user_id)
    except ValidationError as exc:
        return _error(400, "VALIDATION_ERROR", str(exc), exc.details)
    except CredentialsNotFoundError:
        return _error(404, "NOT_FOUND", "Credential not found")
    return ("", 204)


@exchange_credentials_bp.route("/api/tenants/<tenantId>/exchange-credentials/<id>/test", methods=["POST"])
def test_credentials(tenantId: str, id: str):
    rl = _apply_rate_limit("test_credentials", 10, 60)
    if rl:
        return rl

    ctx, err = _authorize(tenantId, {"ADMIN"})
    if err:
        return err

    try:
        credential_id = _parse_credential_id(id)
        cooldown_key = f"credential-test:{tenantId}:{credential_id}"
        cooldown = rate_limiter.check_cooldown(cooldown_key, 10)
        if not cooldown.allowed:
            return _error(429, "RATE_LIMIT", "Credential test cooldown", [{"field": "id", "issue": "cooldown"}])

        service = _service()
        meta = service.get_metadata_by_id(tenantId, credential_id)
        creds = service.get_credentials_by_id(tenantId, credential_id)
        test_result = _test_exchange_connection(
            creds.exchange,
            creds.api_key,
            creds.api_secret,
            creds.passphrase,
        )
        ok = bool(test_result.get("ok"))
        latency_ms = int(test_result.get("latency_ms") or 0)
        error_code = test_result.get("error_code")
        category = test_result.get("category")
        try:
            service.write_test_audit(
                tenant_id=tenantId,
                credential_id=credential_id,
                user_id=ctx.user_id,
                ok=ok,
                latency_ms=latency_ms,
                error_code=error_code,
                category=category,
                exchange=meta.exchange,
                label=meta.label,
            )
        except Exception as audit_exc:
            log.warning(
                "write_test_audit failed tenantId=%s credentialId=%s err=%s",
                tenantId,
                credential_id,
                audit_exc,
            )
        if not ok:
            hint = str(test_result.get("hint") or "").strip()
            details = [{"field": "exchange", "issue": str(category or "unknown").lower()}]
            if hint:
                details.append({"field": "action", "issue": hint})
            return _error(
                400,
                "EXCHANGE_TEST_FAILED",
                _build_failure_message(category, hint),
                details,
            )
        return jsonify(
            {
                "ok": True,
                "latencyMs": latency_ms,
                "probeMethod": test_result.get("probe_method"),
                "probeSymbol": test_result.get("probe_symbol"),
            }
        )
    except ValidationError as exc:
        return _error(400, "VALIDATION_ERROR", str(exc), exc.details)
    except CredentialsNotFoundError:
        return _error(404, "NOT_FOUND", "Credential not found")
    except Exception:
        log.exception("test_credentials failed tenantId=%s credentialId=%s", tenantId, id)
        return _error(500, "INTERNAL_ERROR", "Unexpected error")


@exchange_credentials_bp.before_app_request
def _capture_request_metadata():
    g.redacted_body = redact_value(request.get_json(silent=True) or {}) if request.is_json else {}
    g.request_id = str(uuid.uuid4())
