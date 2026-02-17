import asyncio
import configparser
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.order_router import OrderRouter
from core.state_store import StateStore


class FakeHub:
    def __init__(self):
        self.enabled_ids = ["paperx"]
        self.exchanges = {}
        self.tenant_id = "default"
        self.calls = []
        self.fail_first = False

    async def create_limit_order(self, ex_name, global_pair, side, amount, price_usdt, params=None):
        self.calls.append({"ex": ex_name, "pair": global_pair, "side": side, "params": dict(params or {})})
        if self.fail_first and len(self.calls) == 1:
            raise TimeoutError("simulated timeout")
        return {
            "id": f"ex-{len(self.calls)}",
            "status": "open",
            "side": side,
            "amount": amount,
            "price": price_usdt,
        }


class IdempotencyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "state.db")
        cfg = configparser.ConfigParser()
        cfg["GLOBAL"] = {"SQLITE_PATH": self.db_path, "CSV_ENABLE": "false"}
        cfg["ROUTER"] = {"ORDER_HASH_TTL_SEC": "0"}
        cfg["LOG"] = {}
        self.state = StateStore(cfg)
        self.hub = FakeHub()
        self.router = OrderRouter(cfg, self.hub, portfolio=None, risk=None, state=self.state)

    def tearDown(self):
        self.tmpdir.cleanup()

    async def test_retry_should_reuse_same_client_order_id(self):
        self.hub.fail_first = True
        first = await self.router._create_limit_order_safe(
            ex_name="paperx",
            pair="BTC/USDT",
            symbol_local="BTC/USDT",
            side_l="buy",
            qty_local=1.0,
            price_usdt=100.0,
            price_local=100.0,
            cycle_id="cycle-1",
        )
        self.assertFalse(first)

        second = await self.router._create_limit_order_safe(
            ex_name="paperx",
            pair="BTC/USDT",
            symbol_local="BTC/USDT",
            side_l="buy",
            qty_local=1.0,
            price_usdt=100.0,
            price_local=100.0,
            cycle_id="cycle-1",
        )

        self.assertEqual(len(self.hub.calls), 2)
        coid_first = self.hub.calls[0]["params"].get("clientOrderId")
        coid_second = self.hub.calls[1]["params"].get("clientOrderId")
        self.assertEqual(coid_first, coid_second)
        self.assertTrue(str(second.get("id", "")).startswith("ex-"))

        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT tenant_id, exchange, client_order_id, COUNT(*) FROM orders GROUP BY tenant_id, exchange, client_order_id"
        ).fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], 1)

    async def test_restart_replay_should_not_create_duplicate(self):
        first = await self.router._create_limit_order_safe(
            ex_name="paperx",
            pair="ETH/USDT",
            symbol_local="ETH/USDT",
            side_l="sell",
            qty_local=2.0,
            price_usdt=200.0,
            price_local=200.0,
            cycle_id="cycle-replay",
        )
        self.assertEqual(len(self.hub.calls), 1)

        hub2 = FakeHub()
        router2 = OrderRouter(self.router.cfg, hub2, portfolio=None, risk=None, state=self.state)
        second = await router2._create_limit_order_safe(
            ex_name="paperx",
            pair="ETH/USDT",
            symbol_local="ETH/USDT",
            side_l="sell",
            qty_local=2.0,
            price_usdt=200.0,
            price_local=200.0,
            cycle_id="cycle-replay",
        )

        self.assertEqual(len(hub2.calls), 0)
        self.assertEqual(str(second.get("dedupe_state")), "REUSED")
        self.assertTrue(first.get("clientOrderId"))

    async def test_concurrent_get_or_create_should_create_single_intent(self):
        async def call_once():
            return await self.router._create_limit_order_safe(
                ex_name="paperx",
                pair="SOL/USDT",
                symbol_local="SOL/USDT",
                side_l="buy",
                qty_local=3.0,
                price_usdt=10.0,
                price_local=10.0,
                cycle_id="cycle-concurrent",
            )

        results = await asyncio.gather(call_once(), call_once())
        dedupe_states = {str(r.get("dedupe_state")) for r in results}
        self.assertIn("REUSED", dedupe_states)

        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE tenant_id='default' AND exchange='paperx'"
        ).fetchone()
        conn.close()
        self.assertEqual(int(rows[0]), 1)

    def test_unique_constraint_should_reject_duplicate_client_order_id(self):
        now = 123.0
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO orders (id, ts, ex_name, pair, side, symbol_local, price_local, amount, status,
                                tenant_id, exchange, client_order_id, created_at, updated_at)
            VALUES ('a', ?, 'paperx', 'BTC/USDT', 'buy', 'BTC/USDT', 1, 1, 'pending', 'default', 'paperx', 'coid-1', ?, ?)
            """,
            (now, now, now),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO orders (id, ts, ex_name, pair, side, symbol_local, price_local, amount, status,
                                    tenant_id, exchange, client_order_id, created_at, updated_at)
                VALUES ('b', ?, 'paperx', 'BTC/USDT', 'buy', 'BTC/USDT', 1, 1, 'pending', 'default', 'paperx', 'coid-1', ?, ?)
                """,
                (now, now, now),
            )
        conn.close()


if __name__ == "__main__":
    unittest.main()
