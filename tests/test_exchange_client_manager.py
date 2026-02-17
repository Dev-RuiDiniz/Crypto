import asyncio

from core.credential_provider import CredentialRecord
from core.exchange_client_manager import ExchangeClientFactory, ExchangeClientManager, AuthErrorClassifier


class FakeCredentialProvider:
    def __init__(self, initial: CredentialRecord):
        self.current = initial

    def get_active_credential(self, tenant_id: str, exchange: str) -> CredentialRecord:
        return self.current


class FakeService:
    def __init__(self):
        self.updates = []

    def update_credentials(self, tenant_id, credential_id, **kwargs):
        self.updates.append((tenant_id, credential_id, kwargs))


class FakeClient:
    def __init__(self, name):
        self.name = name
        self.closed = False

    async def close(self):
        self.closed = True


class FakeFactory(ExchangeClientFactory):
    def __init__(self):
        super().__init__(10)
        self.created = []

    async def create(self, exchange: str, credentials: CredentialRecord):
        client = FakeClient(f"{exchange}:{credentials.version}")
        self.created.append(client)
        return client


def test_cache_keying_and_rotation_on_version_change():
    async def _run():
        provider = FakeCredentialProvider(
            CredentialRecord(credential_id=1, version=1, api_key="k", api_secret="s", passphrase=None, status="ACTIVE", updated_at="t")
        )
        manager = ExchangeClientManager("tenantA", provider, FakeService(), FakeFactory())

        entry1 = await manager.ensure_client("mexc")
        entry2 = await manager.ensure_client("mexc")
        assert entry1.client is entry2.client

        provider.current = CredentialRecord(credential_id=1, version=2, api_key="k2", api_secret="s2", passphrase=None, status="ACTIVE", updated_at="t2")
        entry3 = await manager.ensure_client("mexc")

        assert entry3.version == 2
        assert entry1.client.closed is True

    asyncio.run(_run())


def test_mutex_prevents_concurrent_rotation():
    async def _run():
        provider = FakeCredentialProvider(
            CredentialRecord(credential_id=2, version=1, api_key="k", api_secret="s", passphrase=None, status="ACTIVE", updated_at="t")
        )
        factory = FakeFactory()
        manager = ExchangeClientManager("tenantB", provider, FakeService(), factory)
        await asyncio.gather(manager.ensure_client("binance"), manager.ensure_client("binance"))
        assert len(factory.created) == 1

    asyncio.run(_run())


def test_auth_failure_marks_inactive_and_pauses():
    async def _run():
        provider = FakeCredentialProvider(
            CredentialRecord(credential_id=3, version=1, api_key="k", api_secret="s", passphrase=None, status="ACTIVE", updated_at="t")
        )
        service = FakeService()
        manager = ExchangeClientManager("tenantC", provider, service, FakeFactory())
        await manager.ensure_client("okx")

        await manager.mark_auth_failed_and_pause("okx", RuntimeError("invalid api key"))
        assert service.updates
        _, _, payload = service.updates[0]
        assert payload["status"] == "INACTIVE"

    asyncio.run(_run())


def test_auth_error_classifier():
    ok, category = AuthErrorClassifier.is_auth_error(RuntimeError("signature error"))
    assert ok is True
    assert category == "SIGNATURE_ERROR"


def test_integration_like_hot_reload_flow_without_order_during_rotation():
    async def _run():
        provider = FakeCredentialProvider(
            CredentialRecord(credential_id=7, version=1, api_key="k", api_secret="s", passphrase=None, status="ACTIVE", updated_at="t")
        )
        manager = ExchangeClientManager("tenantZ", provider, FakeService(), FakeFactory())

        await manager.ensure_client("bybit")
        provider.current = CredentialRecord(credential_id=7, version=2, api_key="k2", api_secret="s2", passphrase=None, status="ACTIVE", updated_at="t2")
        await manager.ensure_client("bybit")

        calls = []

        async def _operation(client):
            calls.append(client.name)
            return {"ok": True}

        out = await manager.run_with_operation_lock("bybit", _operation)
        assert out["ok"] is True
        assert calls == ["bybit:2"]

    asyncio.run(_run())
