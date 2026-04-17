import asyncio
import configparser
from datetime import date

from exchanges.adapters import MBV4Adapter


class FakeMBV4Adapter(MBV4Adapter):
    def __init__(self):
        cfg = configparser.ConfigParser()
        cfg["GLOBAL"] = {"HTTP_TIMEOUT_SEC": "15"}
        cfg["EXCHANGES.mercadobitcoin"] = {
            "ENABLED": "true",
            "MBV4_BEARER_TOKEN": "token",
            "MBV4_LOGIN": "",
            "MBV4_PASSWORD": "",
        }
        super().__init__(cfg)
        self.calls = []
        self.travel_rule_effective_date = date(2026, 5, 1)

    async def _get_default_account_id(self) -> str:
        return "acc-123"

    async def _req(self, method, path, params=None, body=None, private=True):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "params": params or {},
                "body": body,
                "private": private,
            }
        )
        if method.upper() == "GET":
            return 200, {"items": [{"id": "dep-1"}]}
        if method.upper() == "PATCH":
            return 200, {"status": "released"}
        return 200, {"withdrawId": "wd-1"}


def test_list_deposits_supports_pending_travel_rule_filter():
    async def _run():
        adapter = FakeMBV4Adapter()
        rows = await adapter.list_deposits("BTC/BRL", status=0, pending_travel_rule=True)
        assert rows == [{"id": "dep-1"}]
        assert adapter.calls[0]["path"] == "/accounts/acc-123/wallet/BTC/deposits"
        assert adapter.calls[0]["params"]["pending_travel_rule"] is True
        assert adapter.calls[0]["params"]["status"] == 0

    asyncio.run(_run())


def test_release_pending_deposit_normalizes_travel_rule_payload():
    async def _run():
        adapter = FakeMBV4Adapter()
        out = await adapter.release_pending_deposit(
            "BTC",
            "dep-1",
            {
                "custody_type": "international_transfer",
                "counterparty_name": "Company A",
                "counterparty_country": "us",
                "counterparty_vasp": "VASP_A",
                "purpose_code": "67995",
                "declared_client_name": "Client Name",
            },
        )
        assert out["status"] == "released"
        assert adapter.calls[0]["method"] == "PATCH"
        assert adapter.calls[0]["path"] == "/accounts/acc-123/wallet/BTC/deposits/dep-1"
        assert adapter.calls[0]["body"]["custody_type"] == "INTERNATIONAL_TRANSFER"
        assert adapter.calls[0]["body"]["counterparty_country"] == "US"

    asyncio.run(_run())


def test_crypto_withdraw_requires_travel_rule_after_effective_date():
    async def _run():
        adapter = FakeMBV4Adapter()
        adapter.travel_rule_effective_date = date(2000, 1, 1)
        try:
            await adapter.withdraw("BTC", quantity="0.1", address="wallet")
        except RuntimeError as exc:
            assert "travel_rule" in str(exc)
            return
        raise AssertionError("expected RuntimeError")

    asyncio.run(_run())


def test_crypto_withdraw_sends_travel_rule_payload():
    async def _run():
        adapter = FakeMBV4Adapter()
        out = await adapter.withdraw(
            "BTC-BRL",
            quantity="0.1",
            address="wallet",
            network="bitcoin",
            tx_fee="0.0001",
            travel_rule={
                "custody_type": "self_custody",
                "counterparty_name": "Cliente Final",
            },
        )
        assert out["withdrawId"] == "wd-1"
        assert adapter.calls[0]["path"] == "/accounts/acc-123/wallet/BTC/withdraw"
        assert adapter.calls[0]["body"]["travel_rule"]["custody_type"] == "SELF_CUSTODY"
        assert adapter.calls[0]["body"]["address"] == "wallet"

    asyncio.run(_run())


def test_wallet_symbol_normalization_uses_asset_for_wallet_routes():
    assert MBV4Adapter.to_wallet_symbol("BTC/BRL") == "BTC"
    assert MBV4Adapter.to_wallet_symbol("ETH-BRL") == "ETH"
    assert MBV4Adapter.to_wallet_symbol("BRL") == "BRL"
