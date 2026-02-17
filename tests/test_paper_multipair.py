import configparser
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from core.monitors import MainMonitor
from core.order_router import OrderRouter
from core.state_store import StateStore


class DummyStrategy:
    def targets_for(self, pair, ref):
        return ref, ref


class FakeAdapters:
    def get_min_qty(self, ex_name, symbol_local):
        return 0.0

    def get_min_notional_usdt(self, ex_name, symbol_local):
        return 0.0

    def get_amount_step(self, ex_name, symbol_local):
        return 0.0

    def round_price(self, ex_name, symbol_local, price):
        return float(price)

    def round_amount(self, ex_name, symbol_local, amount):
        return float(amount)

    def enforce_minima(self, ex_name, symbol_local, amount, price_usdt, router_min_notional_usdt):
        return True, float(amount), ""


class FakeExchange:
    async def create_order(self, symbol_local, typ, side, amount, price):
        return {"id": f"fallback_{symbol_local}_{side}", "info": {"paper": True}}


class FakeHub:
    def __init__(self):
        self.enabled_ids = ["paperx"]
        self.exchanges = {"paperx": FakeExchange()}
        self.usdt_brl = 1.0
        self._counter = 0

    def resolve_symbol_local(self, ex_name, side, global_pair):
        return global_pair

    async def get_orderbook(self, ex_name, symbol_local, limit=1):
        return {"asks": [[100.0, 1.0]], "bids": [[99.0, 1.0]]}

    def to_usdt(self, ex_name, symbol_local, price_local):
        return float(price_local)

    async def get_balance(self, ex_name):
        return {"free": {"USDT": 1000.0, "BTC": 1000.0, "SOL": 1000.0}}

    async def create_limit_order(self, ex_name, global_pair, side, amount, price_usdt, params=None):
        self._counter += 1
        return {
            "id": f"paper_{self._counter}",
            "symbol": global_pair,
            "type": "limit",
            "side": side,
            "amount": amount,
            "price": price_usdt,
            "status": "open",
            "info": {"paper": True},
        }

    async def fetch_open_orders(self, ex_name, global_pair=None):
        return []

    async def cancel_order(self, ex_name, oid, global_pair=None, side_hint=None):
        return {"id": oid, "status": "canceled"}


class PaperMultiPairTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "state.db")

        cfg = configparser.ConfigParser()
        cfg["GLOBAL"] = {
            "SQLITE_PATH": self.db_path,
            "CSV_ENABLE": "false",
            "BOT_CONFIG_CACHE_TTL_SEC": "0",
            "LOOP_INTERVAL_MS": "100",
            "PRINT_EVERY_SEC": "999",
            "PANEL_ENABLED": "false",
        }
        cfg["PAIRS"] = {"LIST": ""}
        cfg["ROUTER"] = {
            "ANCHOR_MODE": "LOCAL",
            "MIN_NOTIONAL_USDT": "0",
            "PLACE_BOTH_SIDES_PER_EXCHANGE": "false",
        }
        cfg["LOG"] = {"VERBOSE_SKIPS": "false", "CONSOLE_EVENTS": "false"}
        cfg["STAKE"] = {
            "SOL/USDT_MODE": "FIXO_USDT",
            "SOL/USDT_VALUE": "1000",
            "BTC/USDT_MODE": "FIXO_USDT",
            "BTC/USDT_VALUE": "1000",
        }
        cfg["SPREAD"] = {"BUY_PCT": "0.0", "SELL_PCT": "0.0"}

        self.cfg = cfg
        self.state = StateStore(cfg)
        self.hub = FakeHub()
        self.router = OrderRouter(cfg, self.hub, portfolio=None, risk=None, state=self.state)
        self.router.adapters = FakeAdapters()

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO config_pairs(symbol, enabled, strategy, risk_percentage, max_daily_loss, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("SOLUSDT", 1, "DummyStrategy", 1.0, 0.0, time.time()),
        )
        conn.execute(
            """
            INSERT INTO config_pairs(symbol, enabled, strategy, risk_percentage, max_daily_loss, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("BTCUSDT", 1, "DummyStrategy", 2.0, 0.0, time.time()),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmpdir.cleanup()

    async def test_paper_two_pairs_should_run_in_parallel_or_interleaved(self):
        await self.router.reprice_pair("SOL/USDT", 100.0, 100.0, 100.0, risk_percentage=1.0)
        await self.router.reprice_pair("BTC/USDT", 100.0, 100.0, 100.0, risk_percentage=2.0)

        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT pair, risk_percentage, qty FROM paper_orders ORDER BY ts").fetchall()
        conn.close()

        pairs = [r[0] for r in rows]
        self.assertIn("SOL/USDT", pairs)
        self.assertIn("BTC/USDT", pairs)

    async def test_risk_percentage_update_should_reflect_next_cycle(self):
        monitor = MainMonitor(
            self.cfg,
            self.hub,
            DummyStrategy(),
            self.router,
            order_manager=None,
            portfolio=None,
            state=self.state,
            risk=None,
        )

        cfg_before = monitor._load_pair_config("SOL/USDT", now=1.0)
        await self.router.reprice_pair("SOL/USDT", 100.0, 100.0, 100.0, risk_percentage=cfg_before["risk_percentage"])

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE config_pairs SET risk_percentage=?, updated_at=? WHERE symbol=?",
            (5.0, time.time(), "SOLUSDT"),
        )
        conn.commit()
        conn.close()

        self.state.bump_config_version("test risk update", updated_by="test")
        monitor._reload_configs_if_needed()

        cfg_after = monitor._load_pair_config("SOL/USDT", now=2.0)
        await self.router.reprice_pair("SOL/USDT", 100.0, 100.0, 100.0, risk_percentage=cfg_after["risk_percentage"])

        conn = sqlite3.connect(self.db_path)
        values = [r[0] for r in conn.execute("SELECT risk_percentage FROM paper_orders WHERE pair='SOL/USDT' ORDER BY ts").fetchall()]
        conn.close()

        self.assertEqual(cfg_before["risk_percentage"], 1.0)
        self.assertEqual(cfg_after["risk_percentage"], 5.0)
        self.assertGreaterEqual(len(values), 2)
        self.assertEqual(values[0], 1.0)
        self.assertEqual(values[-1], 5.0)

    async def test_position_size_should_change_with_risk_percentage(self):
        qty_low = await self.router._calc_amount(
            "paperx", "SOL/USDT", "buy", target_usdt=100.0, pair="SOL/USDT", risk_percentage=1.0
        )
        qty_high = await self.router._calc_amount(
            "paperx", "SOL/USDT", "buy", target_usdt=100.0, pair="SOL/USDT", risk_percentage=5.0
        )

        self.assertGreater(qty_high, qty_low)
        self.assertAlmostEqual(qty_low, 0.1, delta=1e-8)
        self.assertAlmostEqual(qty_high, 0.5, delta=1e-8)


if __name__ == "__main__":
    unittest.main()
