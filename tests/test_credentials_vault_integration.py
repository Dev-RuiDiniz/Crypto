import configparser

from core.credentials_service import ExchangeCredentialsService
from core.state_store import StateStore


def test_insert_encrypted_then_read_decrypted(tmp_path, monkeypatch):
    monkeypatch.setenv("EXCHANGE_CREDENTIALS_MASTER_KEY", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
    cfg = configparser.ConfigParser()
    cfg["GLOBAL"] = {"SQLITE_PATH": str(tmp_path / "state.db")}

    # bootstrap schema
    store = StateStore(cfg)
    store.close()

    service = ExchangeCredentialsService(cfg)
    service.upsert_credentials(
        tenant_id="default",
        exchange="mexc",
        label="primary",
        api_key="k12345",
        api_secret="s12345",
        passphrase="p12345",
        user_id="tester",
    )

    creds = service.get_credentials("default", "mexc")
    assert creds.api_key == "k12345"
    assert creds.api_secret == "s12345"
    assert creds.passphrase == "p12345"
