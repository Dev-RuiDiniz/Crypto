import asyncio
import configparser
import unittest

from core.market_data import BaseWsOrderBookProvider, MarketDataService
from core.order_router import OrderRouter


class FakeExchangeHub:
    def __init__(self):
        self.enabled_ids = ["mexc"]
        self.tenant_id = "default"
        self.usdt_brl = 1.0
        self._poll_count = 0

    def resolve_symbol_local(self, ex_name, side, pair):
        return pair

    async def raw_fetch_orderbook(self, ex_name, symbol, limit=20):
        self._poll_count += 1
        return {"bids": [[99 + self._poll_count, 1]], "asks": [[100 + self._poll_count, 1]]}

    def to_usdt(self, ex_name, symbol_local, price_local):
        return float(price_local)


class FakeWsProvider(BaseWsOrderBookProvider):
    def __init__(self):
        self.counter = 0
        self.fail = False

    async def connect(self, tenant_id, exchange, symbol):
        return None

    async def recv_snapshot(self, tenant_id, exchange, symbol):
        await asyncio.sleep(0.01)
        if self.fail:
            raise RuntimeError("ws_down")
        self.counter += 1
        return {"bids": [[100 + self.counter, 1]], "asks": [[101 + self.counter, 1]]}


class MarketDataTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg = configparser.ConfigParser()
        self.cfg["MARKETDATA"] = {
            "WS_STALE_MS": "40",
            "WS_RECONNECT_MS": "80",
            "POLL_INTERVAL_MS": "20",
            "ORDERBOOK_LIMIT": "5",
        }
        self.cfg["ROUTER"] = {"BALANCE_TTL_SEC": "1", "ANCHOR_MODE": "LOCAL"}
        self.cfg["SPREAD"] = {"BUY_PCT": "0.0", "SELL_PCT": "0.0"}
        self.cfg["STAKE"] = {"SOL/USDT_MODE": "FIXO_USDT", "SOL/USDT_VALUE": "10"}
        self.cfg["LOG"] = {"VERBOSE_SKIPS": "false", "CONSOLE_EVENTS": "false"}

    async def test_ws_poll_recovery_cycle(self):
        hub = FakeExchangeHub()
        ws = FakeWsProvider()
        md = MarketDataService(self.cfg, hub, tenant_id="default", ws_providers={"mexc": ws})
        await md.start(["SOL/USDT"])
        await asyncio.sleep(0.05)
        first = await md.get_order_book("default", "mexc", "SOL/USDT")
        self.assertEqual(first["source"], "WS")

        ws.fail = True
        await asyncio.sleep(0.08)
        degraded = await md.get_order_book("default", "mexc", "SOL/USDT")
        self.assertEqual(degraded["source"], "POLL")
        self.assertIn(degraded["state"], ("DEGRADED", "DISCONNECTED"))

        ws.fail = False
        await asyncio.sleep(0.15)
        recovered = await md.get_order_book("default", "mexc", "SOL/USDT")
        self.assertEqual(recovered["source"], "WS")
        await md.stop()

    async def test_cache_read_and_age(self):
        hub = FakeExchangeHub()
        md = MarketDataService(self.cfg, hub, tenant_id="default", ws_providers={})
        row = await md.get_order_book("default", "mexc", "SOL/USDT")
        self.assertEqual(row["source"], "POLL")
        self.assertIn("ageMs", row)

    async def test_router_blocks_stale_orderbook(self):
        class FakeMD:
            async def get_order_book(self, tenant_id, ex_name, symbol_local):
                return {
                    "snapshot": {"asks": [[100, 1]], "bids": [[99, 1]]},
                    "ageMs": 99999,
                    "source": "POLL",
                    "state": "DEGRADED",
                }

        hub = FakeExchangeHub()
        hub.market_data = FakeMD()

        async def _meta(ex_name, symbol_local):
            return await hub.market_data.get_order_book("default", ex_name, symbol_local)

        hub.get_orderbook_meta = _meta
        router = OrderRouter(self.cfg, hub, portfolio=None, risk=None, state=None)
        ask = await router._best_ask_usdt("mexc", "SOL/USDT")
        self.assertIsNone(ask)


if __name__ == "__main__":
    unittest.main()
