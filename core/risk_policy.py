from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    from utils.logger import get_logger
except Exception:
    import logging
    def get_logger(name: str):
        return logging.getLogger(name)

log = get_logger("risk_policy")


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = ""
    rule_type: str = ""
    rule_value: float = 0.0
    attempted_value: float = 0.0


class RiskPolicy:
    def __init__(self, cfg, state, ex_hub, risk_manager=None):
        self.cfg = cfg
        self.state = state
        self.ex_hub = ex_hub
        self.risk_manager = risk_manager

    async def evaluate(self, intent: Dict[str, Any]) -> RiskDecision:
        tenant_id = str(intent.get("tenant_id") or getattr(self.ex_hub, "tenant_id", "default"))
        exchange = str(intent.get("exchange") or "")
        symbol = str(intent.get("symbol") or "")
        side = str(intent.get("side") or "buy").lower()
        amount = float(intent.get("amount") or 0.0)
        price_usdt = float(intent.get("price_usdt") or 0.0)
        trade_value = float(intent.get("trade_value") or (amount * price_usdt))
        client_order_id = str(intent.get("client_order_id") or "")

        pair_cfg = self._pair_cfg(symbol)
        global_cfg = self.state.get_bot_global_config() if hasattr(self.state, "get_bot_global_config") else {}

        if bool(global_cfg.get("kill_switch_enabled")):
            return self._block(tenant_id, exchange, symbol, "KILL_SWITCH", 1, trade_value, "Kill switch global ativo", client_order_id, event="RISK_KILL_SWITCH_ACTIVE")
        if bool(pair_cfg.get("kill_switch_enabled")):
            return self._block(tenant_id, exchange, symbol, "KILL_SWITCH", 1, trade_value, "Kill switch do par ativo", client_order_id, event="RISK_KILL_SWITCH_ACTIVE")

        max_percent = float(pair_cfg.get("max_percent_per_trade") or 0.0)
        if max_percent > 0:
            bal = await self.ex_hub.get_balance(exchange)
            available_usdt = self._available_quote_usdt(bal, symbol)
            limit_value = available_usdt * (max_percent / 100.0)
            if trade_value > limit_value + 1e-12:
                return self._block(tenant_id, exchange, symbol, "MAX_PERCENT", limit_value, trade_value, "Valor por trade acima do % de saldo", client_order_id, event="RISK_MAX_PERCENT_EXCEEDED")

        max_abs = float(pair_cfg.get("max_absolute_per_trade") or 0.0)
        if max_abs > 0 and trade_value > max_abs + 1e-12:
            return self._block(tenant_id, exchange, symbol, "MAX_ABSOLUTE", max_abs, trade_value, "Valor absoluto por trade excedido", client_order_id)

        open_orders = [o for o in self.state.get_open_orders(limit=2000) if str(o.get("pair") or "").upper() == symbol.upper()]
        max_open = int(pair_cfg.get("max_open_orders_per_symbol") or 0)
        if max_open <= 0 and self.risk_manager is not None:
            max_open = int(self.risk_manager.open_limit_for(symbol, side=side))
        if max_open > 0 and len(open_orders) >= max_open:
            return self._block(tenant_id, exchange, symbol, "MAX_OPEN_ORDERS", max_open, len(open_orders), "Quantidade máxima de ordens abertas atingida", client_order_id)

        max_exposure = float(pair_cfg.get("max_exposure_per_symbol") or 0.0)
        if max_exposure <= 0 and self.risk_manager is not None:
            max_exposure = float(self.risk_manager.gross_cap_for(pair=symbol, ex_name=exchange))
        if max_exposure > 0:
            current_exposure = await self._symbol_exposure_usdt(symbol, exchange, open_orders)
            attempted = current_exposure + max(0.0, trade_value)
            if attempted > max_exposure + 1e-12:
                return self._block(tenant_id, exchange, symbol, "MAX_EXPOSURE", max_exposure, attempted, "Exposição máxima excedida", client_order_id, event="RISK_EXPOSURE_EXCEEDED")

        self._record({
            "tenant_id": tenant_id,
            "exchange": exchange,
            "symbol": symbol,
            "rule_type": "ALL",
            "rule_value": 0,
            "attempted_value": trade_value,
            "decision": "ALLOWED",
            "reason": "RISK_CHECK_PASSED",
            "client_order_id": client_order_id,
            "timestamp": time.time(),
        }, "RISK_CHECK_PASSED")
        return RiskDecision(True)

    async def _symbol_exposure_usdt(self, symbol: str, exchange: str, open_orders):
        exposure = 0.0
        for order in open_orders:
            if exchange and str(order.get("ex_name") or "").lower() != exchange.lower():
                continue
            symbol_local = str(order.get("symbol_local") or symbol)
            price_local = float(order.get("price_local") or 0.0)
            amount = float(order.get("amount") or 0.0)
            try:
                p_usdt = float(self.ex_hub.to_usdt(str(order.get("ex_name") or exchange), symbol_local, price_local))
            except Exception:
                p_usdt = 0.0
            exposure += max(0.0, p_usdt * amount)

        base = symbol.split("/")[0] if "/" in symbol else ""
        if base:
            try:
                bal = await self.ex_hub.get_balance(exchange)
                free = float((bal.get("free") or {}).get(base) or 0.0)
                if free > 0:
                    symbol_local = self.ex_hub.resolve_symbol_local(exchange, "SELL", symbol) or symbol
                    bid = await self.ex_hub.get_orderbook(exchange, symbol_local, limit=1)
                    bid_px = float((bid.get("bids") or [[0]])[0][0] or 0.0)
                    bid_usdt = float(self.ex_hub.to_usdt(exchange, symbol_local, bid_px)) if bid_px > 0 else 0.0
                    exposure += free * bid_usdt
            except Exception:
                pass
        return exposure

    def _pair_cfg(self, symbol: str) -> Dict[str, Any]:
        for row in self.state.get_bot_configs(enabled_only=None):
            if str(row.get("pair") or "").upper() == symbol.upper():
                return row
        return {}

    @staticmethod
    def _available_quote_usdt(balance: Dict[str, Any], symbol: str) -> float:
        quote = symbol.split("/")[1] if "/" in symbol else "USDT"
        free = float((balance.get("free") or {}).get(quote) or 0.0)
        if quote.upper() == "USDT":
            return free
        if quote.upper() == "BRL":
            rate = float(balance.get("USDT_BRL_RATE") or 5.0)
            return free / rate if rate > 0 else 0.0
        return free

    def _block(self, tenant_id, exchange, symbol, rule_type, rule_value, attempted_value, reason, client_order_id, event="RISK_CHECK_BLOCKED"):
        self._record(
            {
                "tenant_id": tenant_id,
                "exchange": exchange,
                "symbol": symbol,
                "rule_type": rule_type,
                "rule_value": rule_value,
                "attempted_value": attempted_value,
                "decision": "BLOCKED",
                "reason": reason,
                "client_order_id": client_order_id,
                "timestamp": time.time(),
            },
            event,
        )
        return RiskDecision(False, reason=reason, rule_type=rule_type, rule_value=float(rule_value or 0.0), attempted_value=float(attempted_value or 0.0))

    def _record(self, payload: Dict[str, Any], event_type: str):
        try:
            self.state.record_risk_event(payload)
        except Exception:
            pass
        try:
            self.state.log_event(event_type, payload)
        except Exception:
            pass
        log.info(
            "%s tenantId=%s exchange=%s symbol=%s rule_type=%s attempted_value=%s limit_value=%s clientOrderId=%s",
            event_type,
            payload.get("tenant_id"),
            payload.get("exchange"),
            payload.get("symbol"),
            payload.get("rule_type"),
            payload.get("attempted_value"),
            payload.get("rule_value"),
            payload.get("client_order_id"),
        )
