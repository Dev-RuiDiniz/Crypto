from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, Dict, Optional, Tuple

try:
    from utils.logger import get_logger
except Exception:
    import logging

    def get_logger(name: str):
        return logging.getLogger(name)


log = get_logger("strategy_arbitrage")
from core.risk_policy import RiskPolicy


class StrategyArbitrageSimple:
    _locks: Dict[Tuple[str, str], asyncio.Lock] = {}

    def __init__(self, cfg, ex_hub, state, risk, tenant_id: str = "default", risk_policy=None):
        self.cfg = cfg
        self.ex_hub = ex_hub
        self.state = state
        self.risk = risk
        self.tenant_id = tenant_id
        self.risk_policy = risk_policy or RiskPolicy(cfg, state, ex_hub, risk_manager=risk)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    @classmethod
    def _symbol_lock(cls, tenant_id: str, symbol: str) -> asyncio.Lock:
        key = (str(tenant_id or "default"), str(symbol or "").upper())
        lock = cls._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            cls._locks[key] = lock
        return lock

    def _build_client_order_id(self, exchange: str, symbol: str, side: str, cycle_id: str, leg: str) -> str:
        raw = f"{self.tenant_id}|{exchange}|{symbol}|{side.lower()}|{cycle_id}|{leg}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        ex_tag = str(exchange).lower().replace("_", "")[:6]
        return f"COID-{ex_tag}-{digest}"[:40]

    @staticmethod
    def _best_prices(orderbook: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
        bids = (orderbook or {}).get("bids") or []
        asks = (orderbook or {}).get("asks") or []
        best_bid = float(bids[0][0]) if bids else None
        best_ask = float(asks[0][0]) if asks else None
        return best_bid, best_ask

    def detect_opportunity(self, *, symbol: str, book_a: Dict[str, Any], book_b: Dict[str, Any], threshold_percent: float,
                           threshold_absolute: float, fee_percent: float, slippage_percent: float) -> Optional[Dict[str, Any]]:
        bid_a, ask_a = self._best_prices(book_a)
        bid_b, ask_b = self._best_prices(book_b)
        if bid_a is None or ask_a is None or bid_b is None or ask_b is None:
            return None

        def _eval_direction(exchange_buy: str, buy_ask: float, exchange_sell: str, sell_bid: float) -> Optional[Dict[str, Any]]:
            fees = buy_ask * (fee_percent / 100.0) + sell_bid * (fee_percent / 100.0)
            slippage = buy_ask * (slippage_percent / 100.0)
            estimated_profit = sell_bid - buy_ask - fees - slippage
            estimated_profit_pct = (estimated_profit / buy_ask) * 100.0 if buy_ask > 0 else 0.0
            if estimated_profit <= float(threshold_absolute):
                return None
            if estimated_profit_pct <= float(threshold_percent):
                return None
            return {
                "exchangeBuy": exchange_buy,
                "exchangeSell": exchange_sell,
                "bestAsk": float(buy_ask),
                "bestBid": float(sell_bid),
                "estimatedProfit": float(estimated_profit),
                "estimatedProfitPct": float(estimated_profit_pct),
                "fees": float(fees),
                "slippage": float(slippage),
                "timestamp": time.time(),
            }

        first = _eval_direction("A", ask_a, "B", bid_b)
        second = _eval_direction("B", ask_b, "A", bid_a)
        choices = [x for x in (first, second) if x]
        if not choices:
            return None
        return max(choices, key=lambda x: float(x.get("estimatedProfit") or 0.0))

    async def _get_free_balance(self, exchange: str, asset: str) -> float:
        bal = await self.ex_hub.get_balance(exchange)
        free = (bal.get("free") or {}).get(asset)
        if free is None and isinstance(bal.get(asset), dict):
            free = bal.get(asset, {}).get("free")
        return self._safe_float(free, 0.0)

    async def _submit_leg(self, *, exchange: str, symbol: str, side: str, amount: float, price_usdt: float, cycle_id: str,
                          leg: str) -> Dict[str, Any]:
        symbol_local = self.ex_hub.resolve_symbol_local(exchange, side.upper(), symbol)
        price_local = self.ex_hub.from_usdt(exchange, symbol_local, price_usdt)
        coid = self._build_client_order_id(exchange, symbol, side, cycle_id, leg)

        intent = self.state.get_or_create_order_intent(
            tenant_id=self.tenant_id,
            exchange=exchange,
            client_order_id=coid,
            pair=symbol,
            side=side,
            symbol_local=symbol_local,
            price_local=price_local,
            amount=amount,
            cycle_id=cycle_id,
        )

        dedupe_state = str(intent.get("dedupe_state") or "NEW")
        decision = await self.risk_policy.evaluate({
            "tenant_id": self.tenant_id,
            "exchange": exchange,
            "symbol": symbol,
            "side": side,
            "amount": float(amount),
            "price_usdt": float(price_usdt),
            "symbol_local": symbol_local,
            "client_order_id": coid,
        })
        if not decision.allowed:
            return {"id": "", "status": "blocked", "clientOrderId": coid, "error": decision.reason, "rule_type": decision.rule_type}
        if not bool(intent.get("should_submit", True)):
            return {
                "id": str(intent.get("id") or ""),
                "status": str(intent.get("status") or "pending"),
                "clientOrderId": coid,
                "dedupe_state": dedupe_state,
                "reused": dedupe_state != "NEW",
                "info": {"deduped": True},
            }

        try:
            resp = await self.ex_hub.create_limit_order(
                ex_name=exchange,
                global_pair=symbol,
                side=side,
                amount=float(amount),
                price_usdt=float(price_usdt),
                params={"clientOrderId": coid},
            )
            oid = str((resp or {}).get("id") or (resp or {}).get("orderId") or intent.get("id") or "")
            self.state.mark_order_submitted(
                tenant_id=self.tenant_id,
                exchange=exchange,
                client_order_id=coid,
                exchange_order_id=oid,
                status=str((resp or {}).get("status") or "open"),
            )
            out = dict(resp or {})
            out["clientOrderId"] = coid
            out["dedupe_state"] = dedupe_state
            out["reused"] = dedupe_state != "NEW"
            return out
        except Exception as exc:
            self.state.mark_order_failed(
                tenant_id=self.tenant_id,
                exchange=exchange,
                client_order_id=coid,
                error_code=type(exc).__name__,
                retryable=True,
            )
            raise

    async def run_cycle(self, symbol: str, cfg_row: Dict[str, Any], global_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        global_cfg = global_cfg or {}
        enabled = bool(cfg_row.get("enabled", False))
        if not enabled:
            return {"state": "IDLE", "reason": "disabled"}

        lock = self._symbol_lock(self.tenant_id, symbol)
        if lock.locked():
            self.state.log_event("ARBITRAGE_COOLDOWN_ACTIVE", {"tenantId": self.tenant_id, "symbol": symbol, "reason": "strategy_lock"})
            return {"state": "EXECUTING", "reason": "strategy_lock"}

        async with lock:
            now_ms = int(time.time() * 1000)
            cooldown_ms = int(cfg_row.get("cooldown_ms") or 0)
            state_row = self.state.get_arbitrage_state(self.tenant_id, symbol)
            last_success_ts = int(state_row.get("last_success_ts") or 0)
            if cooldown_ms > 0 and (now_ms - last_success_ts) < cooldown_ms:
                self.state.log_event("ARBITRAGE_COOLDOWN_ACTIVE", {"tenantId": self.tenant_id, "symbol": symbol, "cooldown_ms": cooldown_ms})
                self.state.upsert_arbitrage_state(self.tenant_id, symbol, runtime_state="COOLDOWN")
                return {"state": "COOLDOWN"}

            exchange_a = str(cfg_row.get("exchange_a") or "").lower()
            exchange_b = str(cfg_row.get("exchange_b") or "").lower()
            if not exchange_a or not exchange_b:
                return {"state": "IDLE", "reason": "missing_exchange"}

            sym_a = self.ex_hub.resolve_symbol_local(exchange_a, "BUY", symbol)
            sym_b = self.ex_hub.resolve_symbol_local(exchange_b, "SELL", symbol)
            book_a_meta = await self.ex_hub.get_orderbook_meta(exchange_a, sym_a)
            book_b_meta = await self.ex_hub.get_orderbook_meta(exchange_b, sym_b)
            opp = self.detect_opportunity(
                symbol=symbol,
                book_a=book_a_meta.get("snapshot") or {},
                book_b=book_b_meta.get("snapshot") or {},
                threshold_percent=self._safe_float(cfg_row.get("threshold_percent"), 0.15),
                threshold_absolute=self._safe_float(cfg_row.get("threshold_absolute"), 0.2),
                fee_percent=self._safe_float(cfg_row.get("fee_percent"), 0.1),
                slippage_percent=self._safe_float(cfg_row.get("slippage_percent"), 0.05),
            )
            if not opp:
                self.state.upsert_arbitrage_state(self.tenant_id, symbol, runtime_state="IDLE")
                return {"state": "IDLE", "reason": "no_opportunity"}

            buy_ex = exchange_a if opp["exchangeBuy"] == "A" else exchange_b
            sell_ex = exchange_b if opp["exchangeSell"] == "B" else exchange_a
            opp["exchangeBuy"] = buy_ex
            opp["exchangeSell"] = sell_ex
            self.state.log_event("ARBITRAGE_OPPORTUNITY_DETECTED", {"tenantId": self.tenant_id, "symbol": symbol, **opp})

            base_asset, quote_asset = symbol.split("/")
            max_trade_size = self._safe_float(cfg_row.get("max_trade_size"), 0.0)
            if max_trade_size <= 0:
                return {"state": "IDLE", "reason": "invalid_size"}

            if bool(global_cfg.get("kill_switch_enabled")):
                return {"state": "IDLE", "reason": "kill_switch"}

            open_orders = [o for o in self.state.get_open_orders(limit=1000) if str(o.get("pair") or "").upper() == symbol.upper()]
            open_buy_ex = len([o for o in open_orders if str(o.get("ex_name") or "").lower() == buy_ex])
            if not self.risk.can_open_more_for(symbol, "buy", open_buy_ex):
                return {"state": "IDLE", "reason": "risk_open_limit"}

            buy_price = float(opp.get("bestAsk") or 0.0)
            sell_price = float(opp.get("bestBid") or 0.0)
            buy_notional = max_trade_size * buy_price
            sell_notional = max_trade_size * sell_price
            if not self.risk.exposure_ok_for(symbol, buy_ex, 0.0, buy_notional):
                return {"state": "IDLE", "reason": "risk_exposure_buy"}
            if not self.risk.exposure_ok_for(symbol, sell_ex, 0.0, sell_notional):
                return {"state": "IDLE", "reason": "risk_exposure_sell"}

            mode = str(cfg_row.get("mode") or "TWO_LEG").upper()
            quote_free = await self._get_free_balance(buy_ex, quote_asset)
            base_free = await self._get_free_balance(sell_ex, base_asset)
            required_quote = buy_notional
            required_base = max_trade_size
            if quote_free < required_quote:
                return {"state": "IDLE", "reason": "insufficient_quote"}
            if mode == "TWO_LEG" and base_free < required_base:
                return {"state": "IDLE", "reason": "insufficient_base"}

            cycle_id = f"arbitrage:{symbol}:{int(time.time() // 5)}:{round(opp['estimatedProfit'], 6)}"
            self.state.log_event("ARBITRAGE_EXECUTION_STARTED", {"tenantId": self.tenant_id, "symbol": symbol, "exchangeA": buy_ex, "exchangeB": sell_ex, "estimatedProfit": opp["estimatedProfit"]})
            self.state.upsert_arbitrage_state(self.tenant_id, symbol, runtime_state="EXECUTING", last_opportunity=opp)

            try:
                leg1 = await self._submit_leg(exchange=buy_ex, symbol=symbol, side="buy", amount=max_trade_size, price_usdt=buy_price, cycle_id=cycle_id, leg="BUY")
            except Exception as exc:
                self.state.log_event("ARBITRAGE_EXECUTION_FAILED", {"tenantId": self.tenant_id, "symbol": symbol, "error": str(exc)})
                self.state.upsert_arbitrage_state(self.tenant_id, symbol, runtime_state="IDLE", last_execution={"status": "FAILED", "executedSize": 0.0, "profitEstimate": opp["estimatedProfit"], "timestamp": time.time()})
                return {"state": "FAILED_SAFE"}

            if mode == "ONE_LEG":
                self.state.log_event("ARBITRAGE_EXECUTION_SUCCESS", {"tenantId": self.tenant_id, "symbol": symbol, "exchangeA": buy_ex, "exchangeB": sell_ex, "estimatedProfit": opp["estimatedProfit"], "clientOrderId": leg1.get("clientOrderId", "")})
                self.state.upsert_arbitrage_state(self.tenant_id, symbol, runtime_state="COOLDOWN", last_opportunity=opp, last_execution={"status": "SUCCESS", "executedSize": max_trade_size, "profitEstimate": opp["estimatedProfit"], "timestamp": time.time()}, last_success_ts=now_ms)
                return {"state": "SUCCESS"}

            try:
                leg2 = await self._submit_leg(exchange=sell_ex, symbol=symbol, side="sell", amount=max_trade_size, price_usdt=sell_price, cycle_id=cycle_id, leg="SELL")
                self.state.log_event("ARBITRAGE_EXECUTION_SUCCESS", {"tenantId": self.tenant_id, "symbol": symbol, "exchangeA": buy_ex, "exchangeB": sell_ex, "estimatedProfit": opp["estimatedProfit"], "clientOrderId": leg2.get("clientOrderId", "")})
                self.state.upsert_arbitrage_state(self.tenant_id, symbol, runtime_state="COOLDOWN", last_opportunity=opp, last_execution={"status": "SUCCESS", "executedSize": max_trade_size, "profitEstimate": opp["estimatedProfit"], "timestamp": time.time()}, last_success_ts=now_ms)
                return {"state": "SUCCESS"}
            except Exception as exc:
                self.state.log_event("ARBITRAGE_EXECUTION_PARTIAL", {"tenantId": self.tenant_id, "symbol": symbol, "exchangeA": buy_ex, "exchangeB": sell_ex, "estimatedProfit": opp["estimatedProfit"], "error": str(exc)})
                self.state.upsert_arbitrage_state(self.tenant_id, symbol, runtime_state="IDLE", last_opportunity=opp, last_execution={"status": "PARTIAL", "executedSize": max_trade_size, "profitEstimate": opp["estimatedProfit"], "timestamp": time.time()})
                return {"state": "PARTIAL"}
