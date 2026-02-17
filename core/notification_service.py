from __future__ import annotations

import asyncio
import hashlib
import json
import os
import smtplib
import sqlite3
import ssl
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from email.message import EmailMessage
from enum import Enum
from typing import Any, Dict, Optional

import aiohttp

from security.crypto import decrypt_secret, encrypt_secret
from security.redaction import redact_value
from utils.logger import get_logger

log = get_logger("notification_service")


class NotificationEventType(str, Enum):
    ORDER_EXECUTED = "ORDER_EXECUTED"
    ARBITRAGE_EXECUTED = "ARBITRAGE_EXECUTED"
    AUTH_FAILED = "AUTH_FAILED"
    WS_DEGRADED = "WS_DEGRADED"
    KILL_SWITCH_ACTIVATED = "KILL_SWITCH_ACTIVATED"


class NotificationSeverity(str, Enum):
    INFO = "INFO"
    IMPORTANT = "IMPORTANT"
    ERROR = "ERROR"


_SEVERITY_RANK = {
    NotificationSeverity.INFO: 1,
    NotificationSeverity.IMPORTANT: 2,
    NotificationSeverity.ERROR: 3,
}


@dataclass
class NotificationSettings:
    tenant_id: str
    email_enabled: bool = False
    email_recipients: list[str] | None = None
    webhook_enabled: bool = False
    webhook_url: str = ""
    min_severity: NotificationSeverity = NotificationSeverity.INFO
    enabled_events: list[str] | None = None
    updated_at: str = ""


class NotificationSettingsRepository:
    def __init__(self, sqlite_path: str):
        self.sqlite_path = sqlite_path

    def _conn(self):
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _default(tenant_id: str) -> NotificationSettings:
        return NotificationSettings(
            tenant_id=tenant_id,
            email_enabled=False,
            email_recipients=[],
            webhook_enabled=False,
            webhook_url="",
            min_severity=NotificationSeverity.INFO,
            enabled_events=[e.value for e in NotificationEventType],
            updated_at="",
        )

    def get(self, tenant_id: str) -> NotificationSettings:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT tenant_id, email_enabled, email_recipients, webhook_enabled, webhook_url,
                       min_severity, enabled_events, updated_at
                FROM notification_settings WHERE tenant_id = ?
                """,
                (tenant_id,),
            ).fetchone()
        if not row:
            return self._default(tenant_id)

        webhook_url = ""
        enc = str(row["webhook_url"] or "")
        if enc:
            try:
                webhook_url = decrypt_secret(enc)
            except Exception:
                webhook_url = ""

        return NotificationSettings(
            tenant_id=str(row["tenant_id"]),
            email_enabled=bool(row["email_enabled"]),
            email_recipients=[x for x in json.loads(row["email_recipients"] or "[]") if isinstance(x, str)],
            webhook_enabled=bool(row["webhook_enabled"]),
            webhook_url=webhook_url,
            min_severity=NotificationSeverity(str(row["min_severity"] or "INFO")),
            enabled_events=[x for x in json.loads(row["enabled_events"] or "[]") if isinstance(x, str)],
            updated_at=str(row["updated_at"] or ""),
        )

    def upsert(self, tenant_id: str, payload: dict[str, Any]) -> NotificationSettings:
        current = self.get(tenant_id)
        email_enabled = bool(payload.get("emailEnabled", current.email_enabled))
        email_recipients = payload.get("emailRecipients", current.email_recipients or [])
        webhook_enabled = bool(payload.get("webhookEnabled", current.webhook_enabled))
        webhook_url = str(payload.get("webhookUrl", current.webhook_url) or "").strip()
        min_severity = str(payload.get("minSeverity", current.min_severity.value) or "INFO").upper()
        enabled_events = payload.get("enabledEvents", current.enabled_events or [])

        updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        encrypted_webhook = encrypt_secret(webhook_url) if webhook_url else ""

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO notification_settings(
                    tenant_id, email_enabled, email_recipients, webhook_enabled,
                    webhook_url, min_severity, enabled_events, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET
                    email_enabled=excluded.email_enabled,
                    email_recipients=excluded.email_recipients,
                    webhook_enabled=excluded.webhook_enabled,
                    webhook_url=excluded.webhook_url,
                    min_severity=excluded.min_severity,
                    enabled_events=excluded.enabled_events,
                    updated_at=excluded.updated_at
                """,
                (
                    tenant_id,
                    1 if email_enabled else 0,
                    json.dumps(email_recipients, ensure_ascii=False),
                    1 if webhook_enabled else 0,
                    encrypted_webhook,
                    min_severity,
                    json.dumps(enabled_events, ensure_ascii=False),
                    updated_at,
                ),
            )
            conn.commit()

        return self.get(tenant_id)


class EmailChannel:
    def __init__(self):
        self.host = os.getenv("SMTP_HOST", "").strip()
        self.port = int(os.getenv("SMTP_PORT", "587").strip() or "587")
        self.user = os.getenv("SMTP_USER", "").strip()
        self.password = os.getenv("SMTP_PASS", "").strip()
        self.from_addr = os.getenv("SMTP_FROM", "").strip() or self.user
        self.timeout_sec = float(os.getenv("SMTP_TIMEOUT_SEC", "8").strip() or "8")

    async def send(self, to: list[str], subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, to, subject, body)

    def _send_sync(self, to: list[str], subject: str, body: str) -> None:
        if not (self.host and self.user and self.password and self.from_addr):
            raise RuntimeError("smtp_not_configured")

        msg = EmailMessage()
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg.set_content(body)

        context = ssl.create_default_context()
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_sec) as client:
            client.starttls(context=context)
            client.login(self.user, self.password)
            client.send_message(msg)


class WebhookChannel:
    def __init__(self):
        self.timeout_sec = float(os.getenv("WEBHOOK_TIMEOUT_SEC", "5").strip() or "5")
        self.max_retries = int(os.getenv("WEBHOOK_MAX_RETRIES", "2").strip() or "2")

    async def send(self, url: str, payload: dict[str, Any]) -> None:
        timeout = aiohttp.ClientTimeout(total=self.timeout_sec)
        attempt = 0
        while True:
            attempt += 1
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, json=payload) as resp:
                        if 200 <= resp.status < 300:
                            return
                        raise RuntimeError(f"webhook_status_{resp.status}")
            except Exception:
                if attempt > self.max_retries:
                    raise
                await asyncio.sleep(0.3 * attempt)


class NotificationService:
    def __init__(self, sqlite_path: str, mode: str = "LIVE"):
        self.repo = NotificationSettingsRepository(sqlite_path)
        self.email_channel = EmailChannel()
        self.webhook_channel = WebhookChannel()
        self.mode = str(mode or "LIVE").upper()
        self.rate_window_sec = int(os.getenv("NOTIFICATION_RATE_WINDOW_SEC", "60") or "60")
        self.rate_max = int(os.getenv("NOTIFICATION_RATE_MAX", "5") or "5")
        self._rate_events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._dedupe_cache: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)

    def notify_nowait(
        self,
        tenant_id: str,
        event_type: NotificationEventType,
        severity: NotificationSeverity,
        payload: dict[str, Any],
    ) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.notify(tenant_id, event_type, severity, payload))
        except RuntimeError:
            asyncio.run(self.notify(tenant_id, event_type, severity, payload))

    async def notify(self, tenant_id: str, event_type: NotificationEventType, severity: NotificationSeverity, payload: dict[str, Any]) -> None:
        try:
            settings = self.repo.get(tenant_id)
            if not self._should_send(settings, event_type, severity, payload):
                return

            rendered = self._render_message(event_type, severity, payload)
            channels_sent = 0

            if self.mode == "PAPER":
                log.info(
                    "NOTIFICATION_SENT tenantId=%s eventType=%s channel=%s severity=%s result=SIMULATED",
                    tenant_id,
                    event_type.value,
                    "simulation",
                    severity.value,
                )
                return

            if settings.email_enabled and settings.email_recipients:
                try:
                    await self.email_channel.send(settings.email_recipients, rendered["subject"], rendered["body"])
                    channels_sent += 1
                    self._log_result("NOTIFICATION_SENT", tenant_id, event_type, "email", severity, "ok")
                except Exception as exc:
                    self._log_result("NOTIFICATION_FAILED", tenant_id, event_type, "email", severity, str(exc))

            if settings.webhook_enabled and settings.webhook_url:
                safe_url = str(redact_value(settings.webhook_url))[:16] + "..."
                webhook_payload = {
                    "eventType": event_type.value,
                    "severity": severity.value,
                    "message": rendered["message"],
                    "timestamp": payload.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                try:
                    await self.webhook_channel.send(settings.webhook_url, webhook_payload)
                    channels_sent += 1
                    self._log_result("NOTIFICATION_SENT", tenant_id, event_type, "webhook", severity, "ok")
                except Exception as exc:
                    self._log_result("NOTIFICATION_FAILED", tenant_id, event_type, "webhook", severity, f"{exc}; url={safe_url}")

            if channels_sent == 0 and (settings.email_enabled or settings.webhook_enabled):
                self._log_result("NOTIFICATION_FAILED", tenant_id, event_type, "none", severity, "no_available_channel")
        except Exception as exc:
            self._log_result("NOTIFICATION_FAILED", tenant_id, event_type, "service", severity, str(exc))

    def _should_send(self, settings: NotificationSettings, event_type: NotificationEventType, severity: NotificationSeverity, payload: dict[str, Any]) -> bool:
        if settings.enabled_events and event_type.value not in settings.enabled_events:
            return False
        if _SEVERITY_RANK[severity] < _SEVERITY_RANK[settings.min_severity]:
            return False

        key = (settings.tenant_id, event_type.value)
        now = time.time()
        dq = self._rate_events[key]
        cutoff = now - self.rate_window_sec
        while dq and dq[0] <= cutoff:
            dq.popleft()

        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        dedupe_map = self._dedupe_cache[key]
        for fp, ts in list(dedupe_map.items()):
            if ts <= cutoff:
                dedupe_map.pop(fp, None)
        if fingerprint in dedupe_map:
            self._log_result("NOTIFICATION_RATE_LIMITED", settings.tenant_id, event_type, "all", severity, "deduplicated")
            return False

        if len(dq) >= self.rate_max:
            self._log_result("NOTIFICATION_RATE_LIMITED", settings.tenant_id, event_type, "all", severity, "rate_limit")
            return False

        dq.append(now)
        dedupe_map[fingerprint] = now
        return True

    @staticmethod
    def _render_message(event_type: NotificationEventType, severity: NotificationSeverity, payload: dict[str, Any]) -> dict[str, str]:
        symbol = payload.get("symbol") or "-"
        exchange = payload.get("exchange") or "-"
        amount = payload.get("amount") or "-"
        price = payload.get("price") or "-"
        reason = payload.get("reason") or "-"
        timestamp = payload.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        message = f"[{event_type.value}] {reason} | symbol={symbol} exchange={exchange} amount={amount} price={price} at={timestamp}"
        return {
            "subject": f"TradingBot {severity.value} - {event_type.value}",
            "body": message,
            "message": message,
        }

    @staticmethod
    def _log_result(kind: str, tenant_id: str, event_type: NotificationEventType, channel: str, severity: NotificationSeverity, result: str) -> None:
        log.info(
            "%s tenantId=%s eventType=%s channel=%s severity=%s result=%s",
            kind,
            tenant_id,
            event_type.value,
            channel,
            severity.value,
            result,
        )
