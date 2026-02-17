import asyncio
import configparser

from core.risk_policy import RiskPolicy


class DummyHub:
    tenant_id = "default"

    async def get_balance(self, _exchange):
        return {"free": {"USDT": 1000.0, "BTC": 1.0}}

    def to_usdt(self, _exchange, _symbol_local, price_local):
        return float(price_local)

    def resolve_symbol_local(self, _exchange, _side, symbol):
        return symbol

    async def get_orderbook(self, _exchange, _symbol_local, limit=1):
        return {"bids": [[100.0, 1.0]], "asks": [[101.0, 1.0]]}


class DummyState:
    def __init__(self, cfg):
        self.cfg = cfg
        self.events = []

    def get_bot_global_config(self):
        return {"kill_switch_enabled": False}

    def get_bot_configs(self, enabled_only=None):
        return [self.cfg]

    def get_open_orders(self, limit=2000):
        return self.cfg.get("open_orders", [])

    def record_risk_event(self, payload):
        self.events.append(payload)

    def log_event(self, _typ, _payload):
        pass


def _policy(row):
    cfg = configparser.ConfigParser()
    return RiskPolicy(cfg, DummyState(row), DummyHub())


def test_block_max_percent():
    policy = _policy({"pair": "BTC/USDT", "max_percent_per_trade": 1})
    out = asyncio.run(policy.evaluate({"exchange": "x", "symbol": "BTC/USDT", "side": "buy", "amount": 1, "price_usdt": 100}))
    assert not out.allowed
    assert out.rule_type == "MAX_PERCENT"


def test_block_max_absolute():
    policy = _policy({"pair": "BTC/USDT", "max_absolute_per_trade": 50})
    out = asyncio.run(policy.evaluate({"exchange": "x", "symbol": "BTC/USDT", "side": "buy", "amount": 1, "price_usdt": 100}))
    assert not out.allowed
    assert out.rule_type == "MAX_ABSOLUTE"


def test_block_max_open_orders():
    policy = _policy({"pair": "BTC/USDT", "max_open_orders_per_symbol": 1, "open_orders": [{"pair": "BTC/USDT"}]})
    out = asyncio.run(policy.evaluate({"exchange": "x", "symbol": "BTC/USDT", "side": "buy", "amount": 0.1, "price_usdt": 100}))
    assert not out.allowed
    assert out.rule_type == "MAX_OPEN_ORDERS"


def test_block_max_exposure():
    policy = _policy({"pair": "BTC/USDT", "max_exposure_per_symbol": 50})
    out = asyncio.run(policy.evaluate({"exchange": "x", "symbol": "BTC/USDT", "side": "buy", "amount": 1, "price_usdt": 100}))
    assert not out.allowed
    assert out.rule_type == "MAX_EXPOSURE"


def test_block_kill_switch_pair():
    policy = _policy({"pair": "BTC/USDT", "kill_switch_enabled": True})
    out = asyncio.run(policy.evaluate({"exchange": "x", "symbol": "BTC/USDT", "side": "buy", "amount": 0.1, "price_usdt": 100}))
    assert not out.allowed
    assert out.rule_type == "KILL_SWITCH"
