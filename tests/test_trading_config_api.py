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


def test_pairs_spread_risk_arbitrage_runtime_flow(tmp_path, monkeypatch):
    _bootstrap_db(tmp_path, monkeypatch)
    client = app.test_client()

    created = client.post("/api/tenants/t1/pairs", headers=_auth_headers("ADMIN"), json={"exchange": "binance", "symbol": "BTC/USDT", "enabled": True})
    assert created.status_code == 201
    pair_id = created.get_json()["id"]

    assert client.put(f"/api/tenants/t1/pairs/{pair_id}/spread", headers=_auth_headers("ADMIN"), json={"enabled": True, "percent": 1.25, "sidePolicy": "BOTH"}).status_code == 200
    assert client.put(f"/api/tenants/t1/pairs/{pair_id}/risk", headers=_auth_headers("ADMIN"), json={"maxOpenOrdersPerSymbol": 3, "killSwitchEnabled": True}).status_code == 200
    assert client.put(f"/api/tenants/t1/pairs/{pair_id}/arbitrage", headers=_auth_headers("ADMIN"), json={"enabled": True, "exchangeA": "binance", "exchangeB": "bybit", "thresholdPercent": 0.3}).status_code == 200
    assert client.put("/api/tenants/t1/risk", headers=_auth_headers("ADMIN"), json={"maxPercentPerTrade": 1.5, "killSwitchEnabled": False}).status_code == 200

    runtime = client.get(f"/api/tenants/t1/pairs/{pair_id}/runtime-status", headers=_auth_headers("VIEWER"))
    assert runtime.status_code == 200
    assert "botState" in runtime.get_json()


def test_trading_config_rbac(tmp_path, monkeypatch):
    _bootstrap_db(tmp_path, monkeypatch)
    client = app.test_client()

    assert client.post("/api/tenants/t1/pairs", headers=_auth_headers("VIEWER"), json={"exchange": "binance", "symbol": "ETH/USDT"}).status_code == 403
