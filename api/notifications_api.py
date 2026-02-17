from __future__ import annotations

import configparser
from typing import Any, Optional

from flask import Blueprint, jsonify, request, g

from api.auth import extract_auth_context
from core.notification_service import NotificationEventType, NotificationService, NotificationSeverity

notifications_bp = Blueprint("notifications", __name__)


class ValidationError(RuntimeError):
    def __init__(self, message: str, details: list[dict[str, str]]):
        super().__init__(message)
        self.details = details


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


def _service() -> NotificationService:
    cfg = configparser.ConfigParser()
    cfg["GLOBAL"] = {"SQLITE_PATH": g.db_path}
    mode = (request.args.get("mode") or "LIVE").upper()
    return NotificationService(sqlite_path=g.db_path, mode=mode)


def _validate_settings_payload(payload: dict[str, Any]) -> dict[str, Any]:
    details = []
    out: dict[str, Any] = {}

    if "emailEnabled" in payload:
        out["emailEnabled"] = bool(payload.get("emailEnabled"))
    if "emailRecipients" in payload:
        recipients = payload.get("emailRecipients") or []
        if not isinstance(recipients, list):
            details.append({"field": "emailRecipients", "issue": "invalid_type"})
        else:
            clean = [str(x).strip() for x in recipients if str(x).strip()]
            out["emailRecipients"] = clean
    if "webhookEnabled" in payload:
        out["webhookEnabled"] = bool(payload.get("webhookEnabled"))
    if "webhookUrl" in payload:
        out["webhookUrl"] = str(payload.get("webhookUrl") or "").strip()
    if "minSeverity" in payload:
        sev = str(payload.get("minSeverity") or "INFO").upper()
        if sev not in {s.value for s in NotificationSeverity}:
            details.append({"field": "minSeverity", "issue": "invalid_value"})
        out["minSeverity"] = sev
    if "enabledEvents" in payload:
        events = payload.get("enabledEvents") or []
        if not isinstance(events, list):
            details.append({"field": "enabledEvents", "issue": "invalid_type"})
        else:
            allowed = {e.value for e in NotificationEventType}
            clean_events = [str(x).strip().upper() for x in events if str(x).strip()]
            invalid = [e for e in clean_events if e not in allowed]
            if invalid:
                details.append({"field": "enabledEvents", "issue": "invalid_values"})
            out["enabledEvents"] = clean_events

    if details:
        raise ValidationError("Invalid payload", details)
    return out


def _settings_to_json(item):
    return {
        "tenantId": item.tenant_id,
        "emailEnabled": bool(item.email_enabled),
        "emailRecipients": item.email_recipients or [],
        "webhookEnabled": bool(item.webhook_enabled),
        "webhookUrl": item.webhook_url,
        "minSeverity": item.min_severity.value,
        "enabledEvents": item.enabled_events or [],
        "updatedAt": item.updated_at,
    }


@notifications_bp.route("/api/tenants/<tenantId>/notifications/settings", methods=["GET"])
def get_settings(tenantId: str):
    _, err = _authorize(tenantId, {"ADMIN", "VIEWER"})
    if err:
        return err
    item = _service().repo.get(tenantId)
    return jsonify(_settings_to_json(item))


@notifications_bp.route("/api/tenants/<tenantId>/notifications/settings", methods=["PUT"])
def put_settings(tenantId: str):
    _, err = _authorize(tenantId, {"ADMIN"})
    if err:
        return err
    payload = request.get_json(force=True, silent=True) or {}
    try:
        valid = _validate_settings_payload(payload)
        item = _service().repo.upsert(tenantId, valid)
    except ValidationError as exc:
        return _error(400, "VALIDATION_ERROR", str(exc), exc.details)
    return jsonify(_settings_to_json(item))


@notifications_bp.route("/api/tenants/<tenantId>/notifications/test", methods=["POST"])
def test_notification(tenantId: str):
    _, err = _authorize(tenantId, {"ADMIN"})
    if err:
        return err

    payload = request.get_json(force=True, silent=True) or {}
    channel = str(payload.get("channel") or "email").lower()
    service = _service()
    event_payload = {
        "symbol": "BTC/USDT",
        "exchange": "simulated",
        "amount": 0.01,
        "price": 50000,
        "reason": f"manual_test_{channel}",
        "timestamp": "now",
    }
    service.notify_nowait(tenantId, NotificationEventType.ORDER_EXECUTED, NotificationSeverity.INFO, event_payload)
    return jsonify({"ok": True, "channel": channel, "simulated": service.mode == "PAPER"})
