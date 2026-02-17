import configparser
import sqlite3

from api import handlers
from api.server import app
from core.credentials_service import ExchangeCredentialsService
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
    return str(db_path)


def test_create_list_update_revoke_flow(tmp_path, monkeypatch):
    _bootstrap_db(tmp_path, monkeypatch)
    client = app.test_client()

    created = client.post(
        "/api/tenants/t1/exchange-credentials",
        headers=_auth_headers(),
        json={
            "exchange": "mexc",
            "label": "Conta Principal",
            "apiKey": "abcdefgh12",
            "apiSecret": "12345678secret",
            "passphrase": None,
        },
    )
    assert created.status_code == 201
    created_body = created.get_json()
    assert "apiSecret" not in str(created_body)

    listed = client.get("/api/tenants/t1/exchange-credentials", headers=_auth_headers("VIEWER"))
    assert listed.status_code == 200
    assert len(listed.get_json()) == 1

    cred_id = created_body["id"]
    updated = client.put(
        f"/api/tenants/t1/exchange-credentials/{cred_id}",
        headers=_auth_headers(),
        json={"label": "Conta Rotacionada", "apiSecret": "12345678newsecret"},
    )
    assert updated.status_code == 200

    revoked = client.delete(f"/api/tenants/t1/exchange-credentials/{cred_id}", headers=_auth_headers())
    assert revoked.status_code == 204


def test_rbac_viewer_cannot_mutate(tmp_path, monkeypatch):
    _bootstrap_db(tmp_path, monkeypatch)
    client = app.test_client()
    payload = {
        "exchange": "mexc",
        "label": "Conta Principal",
        "apiKey": "abcdefgh12",
        "apiSecret": "12345678secret",
        "passphrase": None,
    }
    assert client.post("/api/tenants/t1/exchange-credentials", headers=_auth_headers("VIEWER"), json=payload).status_code == 403
    assert client.put("/api/tenants/t1/exchange-credentials/1", headers=_auth_headers("VIEWER"), json={"label": "x"}).status_code == 403
    assert client.delete("/api/tenants/t1/exchange-credentials/1", headers=_auth_headers("VIEWER")).status_code == 403
    assert client.post("/api/tenants/t1/exchange-credentials/1/test", headers=_auth_headers("VIEWER")).status_code == 403


def test_version_increment_rules(tmp_path, monkeypatch):
    db_path = _bootstrap_db(tmp_path, monkeypatch)
    cfg = configparser.ConfigParser()
    cfg["GLOBAL"] = {"SQLITE_PATH": str(db_path)}
    service = ExchangeCredentialsService(cfg)

    created = service.create_credentials("t1", "mexc", "L1", "abcdefgh12", "12345678secret", None, "u1")
    service.update_credentials("t1", created.id, label="L2", status=None, api_key=None, api_secret=None, passphrase=None, user_id="u1")

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT version FROM exchange_credentials WHERE id = ?", (created.id,)).fetchone()
    assert row[0] == 1

    service.update_credentials("t1", created.id, label=None, status=None, api_key=None, api_secret="newsecret1234", passphrase=None, user_id="u1")
    row2 = conn.execute("SELECT version FROM exchange_credentials WHERE id = ?", (created.id,)).fetchone()
    conn.close()
    assert row2[0] == 2


def test_validation_and_redaction(tmp_path, monkeypatch, caplog):
    _bootstrap_db(tmp_path, monkeypatch)
    client = app.test_client()
    bad = client.post(
        "/api/tenants/t1/exchange-credentials",
        headers=_auth_headers(),
        json={"exchange": "INVALID", "label": "a", "apiKey": "1", "apiSecret": "2"},
    )
    body = bad.get_json()
    assert bad.status_code == 400
    assert body["error"] == "VALIDATION_ERROR"
    assert "correlationId" in body

    for rec in caplog.records:
        msg = rec.getMessage()
        assert "apiSecret" not in msg
        assert "passphrase" not in msg


def test_test_endpoint_with_mock(tmp_path, monkeypatch):
    _bootstrap_db(tmp_path, monkeypatch)
    client = app.test_client()
    created = client.post(
        "/api/tenants/t1/exchange-credentials",
        headers=_auth_headers(),
        json={
            "exchange": "mexc",
            "label": "Conta Principal",
            "apiKey": "abcdefgh12",
            "apiSecret": "12345678secret",
            "passphrase": None,
        },
    ).get_json()

    from api import exchange_credentials_api as mod

    monkeypatch.setattr(mod, "_test_exchange_connection", lambda *args, **kwargs: (True, 10, None, None))
    tested = client.post(f"/api/tenants/t1/exchange-credentials/{created['id']}/test", headers=_auth_headers())
    assert tested.status_code == 200
    assert tested.get_json()["ok"] is True
