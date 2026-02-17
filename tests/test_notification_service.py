import configparser
import os
import sqlite3

from core.notification_service import (
    NotificationEventType,
    NotificationService,
    NotificationSeverity,
)
from core.state_store import StateStore


class _DummyEmail:
    def __init__(self):
        self.calls = []

    async def send(self, to, subject, body):
        self.calls.append((to, subject, body))


class _DummyWebhook:
    def __init__(self):
        self.calls = []

    async def send(self, url, payload):
        self.calls.append((url, payload))


def _bootstrap(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "EXCHANGE_CREDENTIALS_MASTER_KEY",
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )
    cfg = configparser.ConfigParser()
    db_path = tmp_path / "state.db"
    cfg["GLOBAL"] = {"SQLITE_PATH": str(db_path)}
    store = StateStore(cfg)
    store.close()
    return str(db_path)


def test_rate_limit_and_dedupe(tmp_path, monkeypatch):
    db_path = _bootstrap(tmp_path, monkeypatch)
    service = NotificationService(db_path, mode="LIVE")
    service.rate_max = 2
    service.rate_window_sec = 60
    email = _DummyEmail()
    service.email_channel = email

    service.repo.upsert("t1", {
        "emailEnabled": True,
        "emailRecipients": ["ops@example.com"],
        "enabledEvents": [NotificationEventType.ORDER_EXECUTED.value],
        "minSeverity": "INFO",
    })

    payload = {"symbol": "BTC/USDT", "exchange": "mexc", "amount": 1, "price": 100, "reason": "x", "timestamp": "1"}

    import asyncio
    asyncio.run(service.notify("t1", NotificationEventType.ORDER_EXECUTED, NotificationSeverity.INFO, payload))
    asyncio.run(service.notify("t1", NotificationEventType.ORDER_EXECUTED, NotificationSeverity.INFO, payload))
    asyncio.run(service.notify("t1", NotificationEventType.ORDER_EXECUTED, NotificationSeverity.INFO, {**payload, "timestamp": "2"}))

    assert len(email.calls) == 2


def test_severity_and_event_filter(tmp_path, monkeypatch):
    db_path = _bootstrap(tmp_path, monkeypatch)
    service = NotificationService(db_path, mode="LIVE")
    email = _DummyEmail()
    service.email_channel = email

    service.repo.upsert("t1", {
        "emailEnabled": True,
        "emailRecipients": ["ops@example.com"],
        "enabledEvents": [NotificationEventType.AUTH_FAILED.value],
        "minSeverity": "ERROR",
    })

    import asyncio
    asyncio.run(service.notify("t1", NotificationEventType.ORDER_EXECUTED, NotificationSeverity.ERROR, {"timestamp": "1"}))
    asyncio.run(service.notify("t1", NotificationEventType.AUTH_FAILED, NotificationSeverity.INFO, {"timestamp": "1"}))
    asyncio.run(service.notify("t1", NotificationEventType.AUTH_FAILED, NotificationSeverity.ERROR, {"timestamp": "1"}))

    assert len(email.calls) == 1


def test_webhook_url_encrypted(tmp_path, monkeypatch):
    db_path = _bootstrap(tmp_path, monkeypatch)
    service = NotificationService(db_path, mode="LIVE")
    service.repo.upsert("t1", {
        "webhookEnabled": True,
        "webhookUrl": "https://example.com/hook/secret",
        "enabledEvents": [NotificationEventType.ORDER_EXECUTED.value],
    })

    conn = sqlite3.connect(db_path)
    raw = conn.execute("SELECT webhook_url FROM notification_settings WHERE tenant_id='t1'").fetchone()[0]
    conn.close()

    assert "https://" not in raw
    settings = service.repo.get("t1")
    assert settings.webhook_url == "https://example.com/hook/secret"


def test_paper_mode_simulated(tmp_path, monkeypatch):
    db_path = _bootstrap(tmp_path, monkeypatch)
    service = NotificationService(db_path, mode="PAPER")
    email = _DummyEmail()
    service.email_channel = email
    service.repo.upsert("t1", {"emailEnabled": True, "emailRecipients": ["ops@example.com"]})

    import asyncio
    asyncio.run(service.notify("t1", NotificationEventType.ORDER_EXECUTED, NotificationSeverity.INFO, {"timestamp": "1"}))

    assert len(email.calls) == 0
