from __future__ import annotations

import configparser
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

ALLOWED_EXCHANGES = ("mexc", "binance", "bybit", "okx", "kucoin", "mercadobitcoin")
ALLOWED_STATUS = {"ACTIVE", "INACTIVE", "REVOKED"}
LABEL_ALLOWED_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ._-")

rate_limiter = InMemoryRateLimiter()


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


def _test_exchange_connection(exchange: str, api_key: str, api_secret: str, passphrase: Optional[str]) -> tuple[bool, int, Optional[str], Optional[str]]:
    started = time.time()
    try:
        cls = getattr(ccxt, exchange)
        client = cls(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "password": passphrase,
                "enableRateLimit": True,
                "timeout": 8000,
            }
        )
        if hasattr(client, "fetch_balance"):
            client.fetch_balance()
        else:
            client.fetch_time()
        return True, int((time.time() - started) * 1000), None, None
    except Exception as exc:
        msg = str(exc).lower()
        if "timeout" in msg:
            category = "TIMEOUT"
        elif "auth" in msg or "invalid" in msg or "key" in msg:
            category = "AUTH_FAILED"
        else:
            category = "UNKNOWN"
        return False, int((time.time() - started) * 1000), "EXCHANGE_TEST_FAILED", category


@exchange_credentials_bp.route("/api/tenants/<tenantId>/exchange-credentials", methods=["GET"])
def list_credentials(tenantId: str):
    ctx, err = _authorize(tenantId, {"ADMIN", "VIEWER"})
    if err:
        return err
    service = _service()
    items = service.list_credentials(tenantId)
    return jsonify(
        [
            {
                "id": item.id,
                "exchange": item.exchange,
                "label": item.label,
                "last4": item.last4,
                "status": item.status,
                "updatedAt": item.updated_at,
            }
            for item in items
        ]
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
        ok, latency_ms, error_code, category = _test_exchange_connection(
            creds.exchange,
            creds.api_key,
            creds.api_secret,
            creds.passphrase,
        )
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
        if not ok:
            return _error(400, "EXCHANGE_TEST_FAILED", "Connection test failed")
        return jsonify({"ok": True, "latencyMs": latency_ms})
    except ValidationError as exc:
        return _error(400, "VALIDATION_ERROR", str(exc), exc.details)
    except CredentialsNotFoundError:
        return _error(404, "NOT_FOUND", "Credential not found")
    except Exception:
        return _error(500, "INTERNAL_ERROR", "Unexpected error")


@exchange_credentials_bp.before_app_request
def _capture_request_metadata():
    g.redacted_body = redact_value(request.get_json(silent=True) or {}) if request.is_json else {}
    g.request_id = str(uuid.uuid4())
