import configparser

from api import handlers
from api.server import app
from core.state_store import StateStore


def _auth_headers(role="ADMIN", tenant="t1", user="u1"):
    return {"X-User-Id": user, "X-Tenant-Id": tenant, "X-Roles": role}


def _bootstrap_db(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "EXCHANGE_CREDENTIALS_MASTER_KEY",
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )
    cfg = configparser.ConfigParser()
    db_path = tmp_path / "state.db"
    cfg["GLOBAL"] = {"SQLITE_PATH": str(db_path)}
    store = StateStore(cfg)
    store.close()
    handlers.set_db_path_override(str(db_path))


def test_notifications_settings_flow(tmp_path, monkeypatch):
    _bootstrap_db(tmp_path, monkeypatch)
    client = app.test_client()

    got = client.get("/api/tenants/t1/notifications/settings", headers=_auth_headers("VIEWER"))
    assert got.status_code == 200

    saved = client.put(
        "/api/tenants/t1/notifications/settings",
        headers=_auth_headers("ADMIN"),
        json={
            "emailEnabled": True,
            "emailRecipients": ["ops@example.com"],
            "webhookEnabled": True,
            "webhookUrl": "https://example.com/hook",
            "minSeverity": "IMPORTANT",
            "enabledEvents": ["ORDER_EXECUTED", "AUTH_FAILED"],
        },
    )
    assert saved.status_code == 200
    data = saved.get_json()
    assert data["emailEnabled"] is True
    assert data["minSeverity"] == "IMPORTANT"


def test_notifications_rbac(tmp_path, monkeypatch):
    _bootstrap_db(tmp_path, monkeypatch)
    client = app.test_client()

    assert client.get("/api/tenants/t1/notifications/settings", headers=_auth_headers("VIEWER")).status_code == 200
    assert client.put("/api/tenants/t1/notifications/settings", headers=_auth_headers("VIEWER"), json={}).status_code == 403
    assert client.post("/api/tenants/t1/notifications/test", headers=_auth_headers("VIEWER"), json={}).status_code == 403


def test_notifications_test_endpoint(tmp_path, monkeypatch):
    _bootstrap_db(tmp_path, monkeypatch)
    client = app.test_client()
    res = client.post("/api/tenants/t1/notifications/test", headers=_auth_headers("ADMIN"), json={"channel": "email"})
    assert res.status_code == 200
    assert res.get_json()["ok"] is True
