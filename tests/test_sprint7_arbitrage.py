import configparser
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.state_store import StateStore
from core.risk_manager import RiskManager
from core.strategy_arbitrage_simple import StrategyArbitrageSimple


class FakeHub:
    def __init__(self):
        self.tenant_id = "default"
        self.mode = "PAPER"
        self.enabled_ids = ["aex", "bex"]
        self.orders = []
        self.fail_second_leg = False
        self._books = {
            ("aex", "BTC/USDT"): {"bids": [[9.9, 5]], "asks": [[10.0, 5]]},
            ("bex", "BTC/USDT"): {"bids": [[10.3, 5]], "asks": [[10.4, 5]]},
        }

    def resolve_symbol_local(self, ex_name, side, global_pair):
        return global_pair

    def from_usdt(self, ex_name, symbol_local, price_usdt):
        return float(price_usdt)

    async def get_orderbook_meta(self, ex_name, symbol_local):
        return {"snapshot": self._books[(ex_name, symbol_local)]}

    async def get_balance(self, ex_name):
        return {"free": {"USDT": 100000, "BTC": 100000}}

    async def create_limit_order(self, ex_name, global_pair, side, amount, price_usdt, params=None):
        if self.fail_second_leg and len(self.orders) == 1:
            raise RuntimeError("second_leg_failed")
        self.orders.append({"ex_name": ex_name, "side": side, "params": dict(params or {})})
        return {"id": f"oid-{len(self.orders)}", "status": "open", "info": {"paper": True}}


class Sprint7ArbitrageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "state.db")
        cfg = configparser.ConfigParser()
        cfg["GLOBAL"] = {"SQLITE_PATH": self.db_path, "CSV_ENABLE": "false"}
        cfg["RISK"] = {"MAX_OPEN_ORDERS_PER_PAIR_PER_EXCHANGE": "5", "MAX_GROSS_EXPOSURE_USDT": "1000000"}
        self.state = StateStore(cfg)
        self.risk = RiskManager(cfg)
        self.hub = FakeHub()
        self.strategy = StrategyArbitrageSimple(cfg, self.hub, self.state, self.risk, tenant_id="default")

    def tearDown(self):
        self.tmpdir.cleanup()

    async def test_detect_and_execute_two_legs_with_idempotency(self):
        cfg_row = {
            "enabled": True,
            "exchange_a": "aex",
            "exchange_b": "bex",
            "threshold_percent": 0.1,
            "threshold_absolute": 0.1,
            "max_trade_size": 1.0,
            "cooldown_ms": 0,
            "mode": "TWO_LEG",
            "fee_percent": 0.0,
            "slippage_percent": 0.0,
        }
        first = await self.strategy.run_cycle("BTC/USDT", cfg_row)
        second = await self.strategy.run_cycle("BTC/USDT", cfg_row)

        self.assertEqual(first["state"], "SUCCESS")
        self.assertEqual(second["state"], "SUCCESS")

        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT tenant_id, exchange, client_order_id, COUNT(*) FROM orders GROUP BY tenant_id, exchange, client_order_id"
        ).fetchall()
        conn.close()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r[3] == 1 for r in rows))

    async def test_second_leg_failure_should_mark_partial(self):
        self.hub.fail_second_leg = True
        cfg_row = {
            "enabled": True,
            "exchange_a": "aex",
            "exchange_b": "bex",
            "threshold_percent": 0.1,
            "threshold_absolute": 0.1,
            "max_trade_size": 1.0,
            "cooldown_ms": 0,
            "mode": "TWO_LEG",
            "fee_percent": 0.0,
            "slippage_percent": 0.0,
        }
        out = await self.strategy.run_cycle("BTC/USDT", cfg_row)
        self.assertEqual(out["state"], "PARTIAL")
        st = self.state.get_arbitrage_state("default", "BTC/USDT")
        self.assertEqual(st.get("last_execution", {}).get("status"), "PARTIAL")

    async def test_cooldown_should_block_new_execution(self):
        cfg_row = {
            "enabled": True,
            "exchange_a": "aex",
            "exchange_b": "bex",
            "threshold_percent": 0.1,
            "threshold_absolute": 0.1,
            "max_trade_size": 1.0,
            "cooldown_ms": 60000,
            "mode": "TWO_LEG",
            "fee_percent": 0.0,
            "slippage_percent": 0.0,
        }
        first = await self.strategy.run_cycle("BTC/USDT", cfg_row)
        second = await self.strategy.run_cycle("BTC/USDT", cfg_row)
        self.assertEqual(first["state"], "SUCCESS")
        self.assertEqual(second["state"], "COOLDOWN")


if __name__ == "__main__":
    unittest.main()
