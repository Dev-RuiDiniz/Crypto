from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Optional, Tuple, List, Dict, Any, Set
import configparser

try:
    from utils.logger import get_logger, get_user_logger
except Exception:
    import logging
    def get_logger(name: str): return logging.getLogger(name)
    def get_user_logger(name: str): return logging.getLogger(name)

log = get_logger("router")          # tÃ©cnico -> arquivo detalhado
ulog = get_user_logger("router")    # humano -> console (opcional)

from exchanges.adapters import Adapters, ceil_step
from core.risk_policy import RiskPolicy


class OrderRouter:
    """
    Modo novo (padrÃ£o): ANCHOR_MODE=LOCAL
    - Para CADA exchange habilitada:
      * BUY: ancora no best ask LOCAL e lanÃ§a ordem limit em ask * (1 - buy_spread)
      * SELL: ancora no best bid LOCAL e lanÃ§a ordem limit em bid * (1 + sell_spread)
    - ManutenÃ§Ã£o por exchange/lado (banda em bps + cooldown)
    - PÃ³s-fill: abre automaticamente o lado oposto na MESMA exchange (se configurado)
    - Alerta de reabastecimento **apÃ³s fills**

    Compat legacy (ANCHOR_MODE=REF):
    - MantÃ©m roteamento por alvos em USDT (modo antigo)
    """

    def __init__(self, cfg: configparser.ConfigParser, ex_hub, portfolio, risk, state, risk_policy=None):
        self.cfg = cfg
        self.ex_hub = ex_hub
        self.portfolio = portfolio
        self.risk = risk
        self.state = state
        self.risk_policy = risk_policy or RiskPolicy(cfg, state, ex_hub, risk_manager=risk)

        self.adapters = Adapters(cfg, ex_hub)

        # Legados (mantidos para compat no modo REF)
        self.buy_cheaper = self.cfg.getboolean("ROUTER", "PLACE_BUY_WHERE_CHEAPER", fallback=True)
        self.sell_higher = self.cfg.getboolean("ROUTER", "PLACE_SELL_WHERE_HIGHER", fallback=True)
        self.stake_section = "STAKE"

        # Novos controles
        self.anchor_mode = self.cfg.get("ROUTER", "ANCHOR_MODE", fallback="LOCAL").strip().upper()
        self.min_router_notional = float(self.cfg.get("ROUTER", "MIN_NOTIONAL_USDT", fallback="1"))
        self.track_bps = int(self.cfg.get("ROUTER", "TRACK_LOCAL_BPS", fallback="0"))
        self.cooldown_sec = float(self.cfg.get("ROUTER", "REPRICE_COOLDOWN_SEC", fallback="0"))
        self.one_cycle_exit = self.cfg.getboolean("ROUTER", "ONE_CYCLE_AND_EXIT", fallback=False)

        # â€œgrudar na exchangeâ€ (compat legado)
        self.sticky_per_side = self.cfg.getboolean("ROUTER", "STICKY_PER_SIDE", fallback=True)

        # Logs de â€œskip por saldoâ€ somente no arquivo detalhado (console nÃ£o recebe)
        self.verbose_skips = self.cfg.getboolean("LOG", "VERBOSE_SKIPS", fallback=False)

        # Eventos no console e sink opcional para painel
        self.console_events = self.cfg.getboolean("LOG", "CONSOLE_EVENTS", fallback=False)
        self._event_sink = None  # callable opcional para enviar eventos ao painel

        # >>> NOVOS flags
        self.place_both_sides_per_ex = self.cfg.getboolean("ROUTER", "PLACE_BOTH_SIDES_PER_EXCHANGE", fallback=True)
        self.alert_cooldown_sec = float(self.cfg.get("ROUTER", "ALERT_COOLDOWN_SEC", fallback="120"))
        self.auto_post_fill_opposite = self.cfg.getboolean("ROUTER", "AUTO_POST_FILL_OPPOSITE", fallback=True)
        self.post_fill_use_filled_qty = self.cfg.getboolean("ROUTER", "POST_FILL_USE_FILLED_QTY", fallback=True)
        self.recreate_after_external_cancel = self.cfg.getboolean(
            "ROUTER",
            "RECREATE_AFTER_EXTERNAL_CANCEL",
            fallback=True,
        )

        # DeduplicaÃ§Ã£o de eventos (reduzir flood visual)
        self.event_dedup_sec = float(self.cfg.get("LOG", "EVENT_DEDUP_SEC", fallback="90"))
        self._event_last_ts: Dict[str, float] = {}

        # Cache de saldos
        self.balance_ttl = float(self.cfg.get("ROUTER", "BALANCE_TTL_SEC", fallback="8"))
        self.marketdata_stale_ms = int(self.cfg.get("MARKETDATA", "WS_STALE_MS", fallback="3000"))
        self._balance_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

        # Estrutura: orders[pair][ex_name][side] = {...}
        self.orders: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}

        # Cooldown para alertas de reabastecimento (apÃ³s fill)
        self._alert_last_ts: Dict[Tuple[str, str, str], float] = {}

        self._should_exit = False
        self._recent_order_hashes: Dict[str, float] = {}
        self._order_hash_ttl_sec = float(self.cfg.get("ROUTER", "ORDER_HASH_TTL_SEC", fallback="8"))
        self._expected_cancel_oids: Set[str] = set()
        self._manual_cancel_blocks: Dict[Tuple[str, str, str], float] = {}


    # ------------------------- eventos / integraÃ§Ã£o com painel -------------------------

    def set_event_sink(self, sink):
        """Define um callback opcional para receber eventos humanos (painel)."""
        self._event_sink = sink

    def _emit_event(self, msg: str, level: str = "info"):
        """Envia evento para painel (se houver) ou console (se habilitado), com deduplicaÃ§Ã£o por tempo."""
        try:
            now = time.time()
            last = self._event_last_ts.get(msg, 0.0)
            if now - last < self.event_dedup_sec:
                return
            self._event_last_ts[msg] = now

            if self._event_sink is not None:
                self._event_sink(msg)
            elif self.console_events:
                if level == "warn":
                    ulog.warning(msg)
                elif level == "error":
                    ulog.error(msg)
                else:
                    ulog.info(msg)
        except Exception:
            pass

    # ------------------------- helpers -------------------------

    @staticmethod
    def _quote_ccy(symbol_local: str) -> str:
        return symbol_local.split("/")[1].strip().upper() if "/" in symbol_local else "USDT"

    def _usdt_to_local_price(self, ex_name: str, symbol_local: str, price_usdt: float) -> float:
        quote = self._quote_ccy(symbol_local)
        if quote == "BRL":
            return float(price_usdt) * float(self.ex_hub.usdt_brl)
        return float(price_usdt)

    def _parse_pct(self, val: Any, default: float = 0.10) -> float:
        try:
            if val is None:
                return float(default)
            s = str(val).split(";")[0].split("#")[0].strip()
            v = float(s)
            return max(0.0, v)
        except Exception:
            return float(default)

    def _pair_spreads(self, pair: str) -> Tuple[float, float]:
        """
        Retorna (buy_spread, sell_spread) como fraÃ§Ãµes.
        Prioridade:
          1) [SPREAD] <PAIR>_BUY_PCT / <PAIR>_SELL_PCT
          2) [SPREAD] <PAIR>
          3) [SPREAD] BUY_PCT / SELL_PCT
          4) fallback 0.10 / 0.10
        """
        sect = "SPREAD"
        p = pair.strip().upper()

        buy_raw = self.cfg.get(sect, f"{p}_BUY_PCT", fallback=None)
        sell_raw = self.cfg.get(sect, f"{p}_SELL_PCT", fallback=None)
        if buy_raw is not None or sell_raw is not None:
            buy = self._parse_pct(buy_raw, default=0.10)
            sell = self._parse_pct(sell_raw, default=buy)
            return buy, sell

        single = self.cfg.get(sect, p, fallback=None)
        if single is not None:
            v = self._parse_pct(single, default=0.10)
            return v, v

        glob_buy = self.cfg.get(sect, "BUY_PCT", fallback=None)
        glob_sell = self.cfg.get(sect, "SELL_PCT", fallback=None)
        if glob_buy is not None or glob_sell is not None:
            b = self._parse_pct(glob_buy, default=0.10)
            s = self._parse_pct(glob_sell, default=b)
            return b, s

        return 0.10, 0.10  # fallback final

    async def _best_from_poll_usdt(self, ex_name: str, symbol_local: str, side: str) -> Optional[float]:
        try:
            if hasattr(self.ex_hub, "raw_fetch_orderbook"):
                ob = await self.ex_hub.raw_fetch_orderbook(ex_name, symbol_local, limit=1)
            else:
                ob = await self.ex_hub.get_orderbook(ex_name, symbol_local, limit=1)
            if not isinstance(ob, dict):
                return None
            levels = ob.get("asks") if str(side).lower() == "ask" else ob.get("bids")
            if levels:
                px_local = float(levels[0][0])
                return self.ex_hub.to_usdt(ex_name, symbol_local, px_local)
        except Exception as e:
            log.warning(f"[{ex_name}] poll fallback {side} falhou em {symbol_local}: {e}")
        return None

    async def _best_ask_usdt(self, ex_name: str, symbol_local: str) -> Optional[float]:
        try:
            if hasattr(self.ex_hub, "get_orderbook_meta"):
                meta = await self.ex_hub.get_orderbook_meta(ex_name, symbol_local)
            else:
                ob = await self.ex_hub.get_orderbook(ex_name, symbol_local, limit=1)
                meta = {"snapshot": ob, "ageMs": 0, "source": "POLL", "state": "DEGRADED"}
            age_ms = int(meta.get("ageMs") or 0)
            if age_ms > int(self.marketdata_stale_ms):
                ask_fallback = await self._best_from_poll_usdt(ex_name, symbol_local, "ask")
                if ask_fallback and ask_fallback > 0:
                    log.info(
                        "MARKETDATA_STALE_FALLBACK tenantId=%s exchange=%s symbol=%s ageMs=%s source=%s state=%s",
                        getattr(self.ex_hub, "tenant_id", "default"),
                        ex_name,
                        symbol_local,
                        age_ms,
                        meta.get("source"),
                        meta.get("state"),
                    )
                    return float(ask_fallback)
                log.warning(
                    "MARKETDATA_STALE_BLOCK tenantId=%s exchange=%s symbol=%s ageMs=%s source=%s state=%s",
                    getattr(self.ex_hub, "tenant_id", "default"),
                    ex_name,
                    symbol_local,
                    age_ms,
                    meta.get("source"),
                    meta.get("state"),
                )
                return None
            ob = meta.get("snapshot") or {}
            if ob and ob.get("asks"):
                ask_local = float(ob["asks"][0][0])
                return self.ex_hub.to_usdt(ex_name, symbol_local, ask_local)
        except Exception as e:
            log.warning(f"[{ex_name}] best_ask falhou em {symbol_local}: {e}")
        return None

    async def _best_bid_usdt(self, ex_name: str, symbol_local: str) -> Optional[float]:
        try:
            if hasattr(self.ex_hub, "get_orderbook_meta"):
                meta = await self.ex_hub.get_orderbook_meta(ex_name, symbol_local)
            else:
                ob = await self.ex_hub.get_orderbook(ex_name, symbol_local, limit=1)
                meta = {"snapshot": ob, "ageMs": 0, "source": "POLL", "state": "DEGRADED"}
            age_ms = int(meta.get("ageMs") or 0)
            if age_ms > int(self.marketdata_stale_ms):
                bid_fallback = await self._best_from_poll_usdt(ex_name, symbol_local, "bid")
                if bid_fallback and bid_fallback > 0:
                    log.info(
                        "MARKETDATA_STALE_FALLBACK tenantId=%s exchange=%s symbol=%s ageMs=%s source=%s state=%s",
                        getattr(self.ex_hub, "tenant_id", "default"),
                        ex_name,
                        symbol_local,
                        age_ms,
                        meta.get("source"),
                        meta.get("state"),
                    )
                    return float(bid_fallback)
                log.warning(
                    "MARKETDATA_STALE_BLOCK tenantId=%s exchange=%s symbol=%s ageMs=%s source=%s state=%s",
                    getattr(self.ex_hub, "tenant_id", "default"),
                    ex_name,
                    symbol_local,
                    age_ms,
                    meta.get("source"),
                    meta.get("state"),
                )
                return None
            ob = meta.get("snapshot") or {}
            if ob and ob.get("bids"):
                bid_local = float(ob["bids"][0][0])
                return self.ex_hub.to_usdt(ex_name, symbol_local, bid_local)
        except Exception as e:
            log.warning(f"[{ex_name}] best_bid falhou em {symbol_local}: {e}")
        return None

    def _stake_for(self, pair: str) -> Tuple[str, float]:
        mode = self.cfg.get(self.stake_section, f"{pair}_MODE", fallback="FIXO_USDT").strip().upper()
        val_raw = self.cfg.get(self.stake_section, f"{pair}_VALUE", fallback="0.0")
        try:
            val = float(str(val_raw).split(";")[0].strip())
        except Exception:
            val = 0.0
        return mode, float(val)

    # ----------- Cache de saldos -----------

    async def _get_balance_cached(self, ex_name: str) -> Dict[str, Any]:
        now = time.time()
        ts, bal = self._balance_cache.get(ex_name, (0.0, {}))
        if now - ts < self.balance_ttl and bal:
            return bal
        fresh = await self.ex_hub.get_balance(ex_name)
        self._balance_cache[ex_name] = (now, fresh or {})
        return fresh or {}

    async def _quote_free(self, ex, quote: str, ex_name: Optional[str] = None) -> float:
        try:
            if ex_name:
                bal = await self._get_balance_cached(ex_name)
            else:
                bal = await ex.fetch_balance()
            if quote in bal.get("free", {}):
                return float(bal["free"][quote] or 0.0)
            if quote in bal:
                sub = bal.get(quote) or {}
                return float(sub.get("free") or 0.0)
        except Exception:
            pass
        return 0.0

    async def _base_free(self, ex, base: str, ex_name: Optional[str] = None) -> float:
        try:
            if ex_name:
                bal = await self._get_balance_cached(ex_name)
            else:
                bal = await ex.fetch_balance()
            if base in bal.get("free", {}):
                return float(bal["free"][base] or 0.0)
            if base in bal:
                sub = bal.get(base) or {}
                return float(sub.get("free") or 0.0)
        except Exception:
            pass
        return 0.0

    # ------------------------- estrutura e alertas -------------------------

    def _ensure_slot(self, pair: str, ex_name: str):
        self.orders.setdefault(pair, {})
        self.orders[pair].setdefault(ex_name, {})

    @staticmethod
    def _manual_block_key(pair: str, ex_name: str, side: str) -> Tuple[str, str, str]:
        return (str(pair).upper(), str(ex_name).lower(), str(side).lower())

    def _is_manual_cancel_blocked(self, pair: str, ex_name: str, side: str) -> bool:
        if self.recreate_after_external_cancel:
            return False
        return self._manual_block_key(pair, ex_name, side) in self._manual_cancel_blocks

    def _clear_manual_cancel_block(self, pair: str, ex_name: str, side: str) -> None:
        key = self._manual_block_key(pair, ex_name, side)
        self._manual_cancel_blocks.pop(key, None)

    def _block_side_after_manual_cancel(self, pair: str, ex_name: str, side: str, oid: str, reason: str) -> None:
        key = self._manual_block_key(pair, ex_name, side)
        self._manual_cancel_blocks[key] = time.time()
        self._emit_event(
            f"[{pair}] {ex_name} {str(side).upper()} cancelada manualmente; nao sera recriada automaticamente.",
            level="warn",
        )
        log.info(
            "[%s] %s %s cancelada manualmente (%s, oid=%s). Recriacao automatica bloqueada para esse lado.",
            pair,
            ex_name,
            str(side).upper(),
            reason,
            oid,
        )

    def _alert_need_balance(self, ex_name: str, symbol_local: str, asset: str, reason: str):
        key = (ex_name, symbol_local, asset.upper())
        now = time.time()
        last = self._alert_last_ts.get(key, 0.0)
        if now - last < self.alert_cooldown_sec:
            return
        self._alert_last_ts[key] = now
        self._emit_event(f"[ABASTECER] {ex_name} {symbol_local}: reabastecer {asset.upper()} â€” {reason}.", level="warn")
        log.info(f"[ALERTA] {ex_name} {symbol_local}: reabastecer {asset.upper()} â€” {reason}.")

    # --------- checagem de capacidade por saldo + mÃ­nimos ----------

    async def _has_buy_capacity(self, ex_name: str, symbol_local: str, price_usdt: float) -> Tuple[bool, str]:
        ex = self.ex_hub.exchanges.get(ex_name)
        if not ex:
            return False, "ex"

        min_qty = float(self.adapters.get_min_qty(ex_name, symbol_local) or 0.0)
        min_notional_ex = float(self.adapters.get_min_notional_usdt(ex_name, symbol_local) or 0.0)
        min_notional = max(min_notional_ex, self.min_router_notional)

        amt_needed = max(min_qty, (min_notional / price_usdt) if price_usdt > 0 else 0.0)
        step = self.adapters.get_amount_step(ex_name, symbol_local)
        if step and step > 0:
            amt_needed = ceil_step(amt_needed, step)
        notional_needed = amt_needed * price_usdt

        quote = self._quote_ccy(symbol_local)
        q_free_local = await self._quote_free(ex, quote, ex_name=ex_name)
        q_free_usdt = (float(q_free_local) / float(self.ex_hub.usdt_brl)) if quote == "BRL" else float(q_free_local)

        if notional_needed <= 0.0:
            return True, ""
        if q_free_usdt + 1e-12 >= notional_needed:
            return True, ""
        return False, (
            f"saldo_quote<{notional_needed:.8f}USDT (tem {q_free_usdt:.8f}USDT) "
            f"| mins: qty>={min_qty} notional>={min_notional}"
        )

    async def _has_sell_capacity(self, ex_name: str, symbol_local: str, price_usdt: float) -> Tuple[bool, str]:
        ex = self.ex_hub.exchanges.get(ex_name)
        if not ex:
            return False, "ex"

        min_qty = float(self.adapters.get_min_qty(ex_name, symbol_local) or 0.0)
        min_notional_ex = float(self.adapters.get_min_notional_usdt(ex_name, symbol_local) or 0.0)
        min_notional = max(min_notional_ex, self.min_router_notional)

        amt_needed = max(min_qty, (min_notional / price_usdt) if price_usdt > 0 else 0.0)
        step = self.adapters.get_amount_step(ex_name, symbol_local)
        if step and step > 0:
            amt_needed = ceil_step(amt_needed, step)

        base = symbol_local.split("/")[0].upper()
        b_free = await self._base_free(ex, base, ex_name=ex_name)

        if amt_needed <= 0.0:
            return True, ""
        if float(b_free) + 1e-12 >= float(amt_needed):
            return True, ""
        return False, (
            f"saldo_base<{amt_needed:.8f} (tem {b_free:.8f}) "
            f"| mins: qty>={min_qty} notional>={min_notional}"
        )

    # ------------------------- cÃ¡lculo de quantidade (stake) -------------------------

    async def _calc_amount(
        self,
        ex_name: str,
        symbol_local: str,
        side: str,
        target_usdt: float,
        pair: str,
        risk_percentage: float = 0.0,
        max_daily_loss: float = 0.0,
    ) -> float:
        side_l = str(side).lower()
        mode, value = self._stake_for(pair)
        amount = 0.0
        price_usdt = float(target_usdt)

        ex = self.ex_hub.exchanges.get(ex_name)
        if not ex:
            return 0.0

        base, quote = symbol_local.split("/")

        balance_used_usdt = 0.0

        if mode == "FIXO_USDT":
            notional_usdt = max(0.0, float(value))
            # bot_config.risk_percentage: limite adicional por operaÃ§Ã£o.
            risk_frac = max(0.0, min(1.0, float(risk_percentage) / 100.0)) if risk_percentage > 0 else 0.0
            if side_l == "buy":
                q_free = await self._quote_free(ex, quote, ex_name=ex_name)
                q_usdt = (float(q_free) / float(self.ex_hub.usdt_brl)) if quote == "BRL" else float(q_free)
                balance_used_usdt = float(q_usdt)
                if notional_usdt <= 0.0 and risk_frac > 0.0:
                    # Fallback seguro: quando stake FIXO_USDT nao foi configurado para o par,
                    # usa o risco percentual sobre o saldo disponivel.
                    notional_usdt = float(q_usdt) * float(risk_frac)
                    log.info(
                        "[position_sizing] pair=%s ex=%s side=%s stake_fallback=risk_balance_pct pct=%.4f",
                        pair,
                        ex_name,
                        side_l,
                        float(risk_frac),
                    )
                notional_usdt = min(notional_usdt, q_usdt)
                if risk_frac > 0 and float(value) > 0:
                    notional_usdt = min(notional_usdt, q_usdt * risk_frac)
                if max_daily_loss > 0:
                    notional_usdt = min(notional_usdt, float(max_daily_loss))
                if price_usdt > 0:
                    amount = notional_usdt / price_usdt
            else:
                b_free = await self._base_free(ex, base, ex_name=ex_name)
                balance_used_usdt = float(b_free) * float(price_usdt)
                if notional_usdt <= 0.0 and risk_frac > 0.0:
                    amount = float(b_free) * float(risk_frac)
                    log.info(
                        "[position_sizing] pair=%s ex=%s side=%s stake_fallback=risk_base_pct pct=%.4f",
                        pair,
                        ex_name,
                        side_l,
                        float(risk_frac),
                    )
                elif price_usdt > 0:
                    amount = notional_usdt / price_usdt
                amount = min(float(amount), float(b_free))
                if risk_frac > 0 and float(value) > 0:
                    amount = min(amount, float(b_free) * risk_frac)
        else:
            pct = max(0.0, min(1.0, float(value)))
            if risk_percentage > 0:
                pct = min(pct, max(0.0, min(1.0, float(risk_percentage) / 100.0)))
            if side_l == "buy":
                q_free = await self._quote_free(ex, quote, ex_name=ex_name)
                q_usdt = (float(q_free) / float(self.ex_hub.usdt_brl)) if quote == "BRL" else float(q_free)
                balance_used_usdt = float(q_usdt)
                notional_usdt = q_usdt * pct
                if max_daily_loss > 0:
                    notional_usdt = min(notional_usdt, float(max_daily_loss))
                if price_usdt > 0:
                    amount = notional_usdt / price_usdt
            else:
                b_free = await self._base_free(ex, base, ex_name=ex_name)
                balance_used_usdt = float(b_free) * float(price_usdt)
                amount = float(b_free) * pct

        computed_notional = float(amount) * float(price_usdt)
        log.info(
            "[position_sizing] pair=%s ex=%s side=%s risk_percentage=%.4f balance_used_usdt=%.8f qty=%.8f notional_usdt=%.8f",
            pair,
            ex_name,
            side_l,
            float(risk_percentage or 0.0),
            float(balance_used_usdt),
            float(amount),
            float(computed_notional),
        )

        return float(amount)


    def _record_paper_execution(
        self,
        *,
        pair: str,
        side: str,
        qty: float,
        price_usdt: float,
        risk_percentage: float,
        strategy: str = "",
    ) -> None:
        cycle_id = f"{pair}:{int(time.time() * 1000)}"
        payload = {
            "id": f"paper_{cycle_id}_{side}",
            "timestamp": time.time(),
            "pair": pair,
            "strategy": strategy,
            "side": side,
            "risk_percentage": float(risk_percentage or 0.0),
            "qty": float(qty or 0.0),
            "computed_notional": float(qty or 0.0) * float(price_usdt or 0.0),
            "cycle_id": cycle_id,
        }
        log.info(
            "[paper_exec] pair=%s strategy=%s side=%s risk_percentage=%.4f qty=%.8f notional=%.8f cycle_id=%s",
            payload["pair"],
            payload["strategy"] or "n/a",
            payload["side"],
            payload["risk_percentage"],
            payload["qty"],
            payload["computed_notional"],
            payload["cycle_id"],
        )
        try:
            if hasattr(self.state, "record_paper_order"):
                self.state.record_paper_order(payload)
            if hasattr(self.state, "log_event"):
                self.state.log_event("paper_exec", payload)
        except Exception:
            pass

    # ------------------------- nÃºcleo: reprecificaÃ§Ã£o por exchange -------------------------

    def _band_hit(self, pair: str, ex_name: str, side: str, new_price_local: float) -> bool:
        if self.track_bps <= 0:
            return True
        rec = self.orders.get(pair, {}).get(ex_name, {}).get(str(side).lower())
        if not rec:
            return True
        last_p = float(rec.get("price_local") or 0.0)
        if last_p <= 0:
            return True
        drift = abs(new_price_local - last_p) / last_p
        if drift < (self.track_bps / 10000.0):
            return False
        if self.cooldown_sec > 0:
            now = time.time()
            if now - float(rec.get("ts", 0.0)) < self.cooldown_sec:
                return False
        return True

    # --------- helpers p/ normalizaÃ§Ã£o de sÃ­mbolo ao filtrar ---------
    @staticmethod
    def _same_symbol(sym_from_order: str, symbol_local: str) -> bool:
        s = (sym_from_order or "").strip().upper()
        loc = (symbol_local or "").strip().upper()
        if not s or not loc:
            return False
        if s == loc:
            return True
        if s.replace("-", "/") == loc:
            return True
        if s.replace("/", "-") == loc:
            return True
        return False

    # ------------------------- listagem/cancelamento via HUB -------------------------

    async def _fetch_open_orders_safe(self, ex_name: str, symbol_local: Optional[str]) -> List[Dict[str, Any]]:
        try:
            lst = await self.ex_hub.fetch_open_orders(ex_name, global_pair=None)
            if symbol_local:
                return [o for o in (lst or []) if self._same_symbol(o.get("symbol") or "", symbol_local)]
        except Exception:
            return []
        return lst or []

    async def _cancel_side(self, pair: str, ex_name: str, symbol_local: str, side: str):
        """
        Cancela ordens abertas do lado informado para simplificar a reprecificaÃ§Ã£o.
        Usa ExchangeHub.cancel_order (compat MB v4) e passa o par global.
        """
        side_l = str(side).lower()

        opens = await self._fetch_open_orders_safe(ex_name, symbol_local)
        targets: List[str] = []
        for o in (opens or []):
            try:
                if (o.get("side", "").lower() == side_l) and self._same_symbol(o.get("symbol") or "", symbol_local):
                    oid = o.get("id") or o.get("orderId")
                    if oid:
                        targets.append(str(oid))
            except Exception:
                continue

        if not targets:
            return

        cancelled, errors = 0, 0
        for oid in targets:
            try:
                await self.ex_hub.cancel_order(ex_name, oid, global_pair=pair, side_hint=side_l)
                self._expected_cancel_oids.add(str(oid))
                cancelled += 1
                await asyncio.sleep(0.10)
            except Exception as e:
                errors += 1
                log.warning(f"[cancel_side] {ex_name} {symbol_local} {side_l} falhou ao cancelar {oid}: {e}")

        # verificaÃ§Ã£o rÃ¡pida
        for _ in range(1):
            remaining = []
            opens2 = await self._fetch_open_orders_safe(ex_name, symbol_local)
            for o in (opens2 or []):
                try:
                    if (o.get("side", "").lower() == side_l) and self._same_symbol(o.get("symbol") or "", symbol_local):
                        oid = o.get("id") or o.get("orderId")
                        if oid and (str(oid) in targets):
                            remaining.append(str(oid))
                except Exception:
                    continue
            if not remaining:
                break
            for oid in remaining:
                try:
                    await self.ex_hub.cancel_order(ex_name, oid, global_pair=pair, side_hint=side_l)
                    self._expected_cancel_oids.add(str(oid))
                    cancelled += 1
                    await asyncio.sleep(0.15)
                except Exception as e:
                    errors += 1
                    log.warning(f"[cancel_side][retry] {ex_name} {symbol_local} {side_l} cancel {oid} erro: {e}")

        if cancelled or errors:
            log.info(f"[cancel_side] {ex_name} {symbol_local} {side_l}: canceladas={cancelled} erros={errors}")

    async def _dedupe_side(self, pair: str, ex_name: str, symbol_local: str, side: str, keep_oid: str):
        """
        Garante no mÃ¡ximo 1 ordem por exchange/sÃ­mbolo/lado.
        Cancela quaisquer outras abertas que nÃ£o sejam keep_oid (via HUB).
        """
        side_l = str(side).lower()
        opens = await self._fetch_open_orders_safe(ex_name, symbol_local)
        victims: List[str] = []
        for o in (opens or []):
            try:
                same_side = o.get("side", "").lower() == side_l
                same_sym = self._same_symbol(o.get("symbol") or "", symbol_local)
                oid = str(o.get("id") or o.get("orderId") or "")
                if same_side and same_sym and oid and (oid != str(keep_oid)):
                    victims.append(oid)
            except Exception:
                continue

        if not victims:
            return

        killed, errs = 0, 0
        for oid in victims:
            try:
                await self.ex_hub.cancel_order(ex_name, oid, global_pair=pair, side_hint=side_l)
                self._expected_cancel_oids.add(str(oid))
                killed += 1
                await asyncio.sleep(0.10)
            except Exception as e:
                errs += 1
                log.warning(f"[dedupe] {ex_name} {symbol_local} {side_l} falha ao cancelar duplicada {oid}: {e}")

        if killed or errs:
            log.info(f"[dedupe] {ex_name} {symbol_local} {side_l}: removidas={killed} erros={errs} (mantida={keep_oid})")

    # ------------------------- BOOT: listar e limpar ordens abertas -------------------------

    def _symbols_for_pairs(self, ex_name: str, pairs: List[str]) -> List[str]:
        syms: List[str] = []
        for p in pairs or []:
            b = self.ex_hub.resolve_symbol_local(ex_name, "BUY", p)
            s = self.ex_hub.resolve_symbol_local(ex_name, "SELL", p)
            if b:
                syms.append(b)
            if s and s != b:
                syms.append(s)
        # remove duplicatas mantendo ordem
        seen = set()
        out = []
        for x in syms:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    async def boot_show_open_orders(self, pairs: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        report: Dict[str, List[Dict[str, Any]]] = {}
        for ex_name in self.ex_hub.enabled_ids:
            syms = set(self._symbols_for_pairs(ex_name, pairs))
            try:
                opens = await self.ex_hub.fetch_open_orders(ex_name, global_pair=None)
            except Exception:
                opens = []

            picked = []
            for o in (opens or []):
                try:
                    sym = (o.get("symbol") or "").strip()
                    ok_sym = (not syms) or any(self._same_symbol(sym, s) for s in syms)
                    if ok_sym:
                        picked.append({
                            "id": o.get("id") or o.get("orderId"),
                            "symbol": sym,
                            "side": o.get("side"),
                            "price": o.get("price"),
                            "amount": o.get("amount"),
                            "status": o.get("status"),
                        })
                except Exception:
                    continue
            report[ex_name] = picked
            log.info(f"[boot] {ex_name}: ordens abertas relevantes={len(picked)} (syms={list(syms) or ['*']})")
            if picked:
                self._emit_event(f"Boot: {ex_name} tem {len(picked)} ordem(ns) aberta(s) para {', '.join(list(syms) or ['*'])}.")
        return report

    async def boot_wipe_pairs(self, pairs: List[str]) -> None:
        for ex_name in self.ex_hub.enabled_ids:
            syms = set(self._symbols_for_pairs(ex_name, pairs))
            try:
                opens = await self.ex_hub.fetch_open_orders(ex_name, global_pair=None)
            except Exception:
                opens = []

            victims: List[Tuple[str, str]] = []  # (oid, symbol)
            for o in (opens or []):
                try:
                    sym = (o.get("symbol") or "").strip()
                    if (not syms) or any(self._same_symbol(sym, s) for s in syms):
                        oid = o.get("id") or o.get("orderId")
                        if oid:
                            victims.append((str(oid), sym))
                except Exception:
                    continue

            if not victims:
                log.info(f"[boot] {ex_name}: nenhum cancelamento necessÃ¡rio.")
                continue

            cancelled, errors = 0, 0
            for oid, sym in victims:
                try:
                    await self.ex_hub.cancel_order(ex_name, oid, global_pair=None, side_hint=None)
                    cancelled += 1
                    await asyncio.sleep(0.10)
                except Exception as e:
                    errors += 1
                    log.warning(f"[boot] {ex_name} cancel {oid}@{sym} erro: {e}")

            # verificaÃ§Ã£o pÃ³s-cancelamento
            still = 0
            try:
                opens2 = await self.ex_hub.fetch_open_orders(ex_name, global_pair=None)
            except Exception:
                opens2 = []
            for o in (opens2 or []):
                try:
                    sym = (o.get("symbol") or "").strip()
                    oid = str(o.get("id") or o.get("orderId") or "")
                    if oid and (oid, sym) in victims:
                        still += 1
                except Exception:
                    continue

            log.info(f"[boot] {ex_name}: canceladas={cancelled} erros={errors} restantes={still}")
            self._emit_event(f"Boot: {ex_name} â€” ordens canceladas={cancelled}, erros={errors}, restantes={still}.")

    # ------------------------- criaÃ§Ã£o de ordem (com fallback) -------------------------

    def _mb_has_legacy_keys(self) -> bool:
        sect = "EXCHANGES.mercadobitcoin"
        api = self.cfg.get(sect, "API_KEY", fallback="").strip()
        sec = self.cfg.get(sect, "API_SECRET", fallback="").strip()
        return bool(api and sec)

    def _build_client_order_id(self, ex_name: str, pair: str, side_l: str, cycle_id: str, intent: str = "") -> str:
        tenant = str(getattr(self.ex_hub, "tenant_id", "default"))
        raw = f"{tenant}|{ex_name}|{pair}|{side_l}|{cycle_id}|{intent or '-'}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        ex_tag = str(ex_name).lower().replace("_", "")[:6]
        return f"COID-{ex_tag}-{digest}"[:40]

    @staticmethod
    def _short_client_order_id(client_order_id: str) -> str:
        txt = str(client_order_id or "")
        if len(txt) <= 10:
            return txt
        return txt[-10:]

    def _is_duplicate_submit(self, key: str) -> bool:
        now = time.time()
        expired = [k for k, ts in self._recent_order_hashes.items() if now - ts > self._order_hash_ttl_sec]
        for k in expired:
            self._recent_order_hashes.pop(k, None)
        prev = self._recent_order_hashes.get(key)
        if prev and (now - prev) <= self._order_hash_ttl_sec:
            return True
        self._recent_order_hashes[key] = now
        return False

    @staticmethod
    def _looks_paper_order_id(oid: Any) -> bool:
        txt = str(oid or "").strip().lower()
        return txt.startswith("paper_") or txt.startswith("pending::")

    def _is_paper_mode(self) -> bool:
        return str(getattr(self.ex_hub, "mode", "") or "").strip().upper() == "PAPER"

    async def _create_limit_order_safe(
        self,
        ex_name: str,
        pair: str,
        symbol_local: str,
        side_l: str,
        qty_local: float,
        price_usdt: float,
        price_local: float,
        cycle_id: str,
    ) -> Dict[str, Any]:
        """
        Tenta via ExchangeHub.create_limit_order (preÃ§o em USDT).
        Para MercadoBitcoin: usa MB v4 adapter corrigido via Exchange Hub.
        """
        # 1) SEMPRE tentar via hub primeiro (MB v4 e afins) - CORRIGIDO
        try:
            if hasattr(self.ex_hub, "create_limit_order"):
                intent = f"{symbol_local}:{round(float(qty_local), 8)}:{round(float(price_usdt), 8)}"
                client_order_id = self._build_client_order_id(ex_name, pair, side_l, cycle_id=cycle_id, intent=intent)
                state_row = self.state.get_or_create_order_intent(
                    tenant_id=str(getattr(self.ex_hub, "tenant_id", "default")),
                    exchange=ex_name,
                    client_order_id=client_order_id,
                    pair=pair,
                    side=side_l,
                    symbol_local=symbol_local,
                    price_local=float(price_local),
                    amount=float(qty_local),
                    cycle_id=str(cycle_id or ""),
                )
                dedupe_state = str(state_row.get("dedupe_state") or "NEW")
                decision = await self.risk_policy.evaluate({
                    "tenant_id": str(getattr(self.ex_hub, "tenant_id", "default")),
                    "exchange": ex_name,
                    "symbol": pair,
                    "side": side_l,
                    "amount": float(qty_local),
                    "price_usdt": float(price_usdt),
                    "symbol_local": symbol_local,
                    "client_order_id": client_order_id,
                })
                if not decision.allowed:
                    self.state.mark_order_failed(
                        tenant_id=str(getattr(self.ex_hub, "tenant_id", "default")),
                        exchange=ex_name,
                        client_order_id=client_order_id,
                        error_code=str(decision.rule_type or "RISK_BLOCKED"),
                        retryable=True,
                    )
                    log.warning(f"[{pair}] blocked by RiskPolicy ex={ex_name} side={side_l} rule={decision.rule_type} reason={decision.reason}")
                    return {"id": "", "status": "blocked", "clientOrderId": client_order_id, "error": decision.reason, "rule_type": decision.rule_type}
                if not bool(state_row.get("should_submit", True)):
                    log.info(
                        f"[{pair}] dedupe_state={dedupe_state} skip create ex={ex_name} side={side_l} coid={self._short_client_order_id(client_order_id)}"
                    )
                    return {
                        "id": str(state_row.get("id") or ""),
                        "status": str(state_row.get("status") or "pending"),
                        "clientOrderId": client_order_id,
                        "dedupe_state": dedupe_state,
                        "reused": dedupe_state != "NEW",
                        "info": {"deduped": True},
                    }
                submit_hash = f"{ex_name}:{pair}:{symbol_local}:{side_l}:{round(float(qty_local), 8)}:{round(float(price_usdt), 8)}:{client_order_id}"
                if self._is_duplicate_submit(submit_hash):
                    log.warning(f"[{pair}] duplicate submit prevented ex={ex_name} side={side_l} symbol={symbol_local}")
                    return {"id": str(state_row.get("id") or ""), "status": "pending", "clientOrderId": client_order_id, "dedupe_state": "BLOCKED", "reused": True}
                try:
                    resp = await self.ex_hub.create_limit_order(
                        ex_name=ex_name,
                        global_pair=pair,
                        side=side_l,
                        amount=float(qty_local),
                        price_usdt=float(price_usdt),
                        params={"clientOrderId": client_order_id},
                    )
                    oid = str((resp or {}).get("id") or (resp or {}).get("orderId") or state_row.get("id") or "")
                    self.state.mark_order_submitted(
                        tenant_id=str(getattr(self.ex_hub, "tenant_id", "default")),
                        exchange=ex_name,
                        client_order_id=client_order_id,
                        exchange_order_id=oid,
                        status=str((resp or {}).get("status") or "open"),
                    )
                    out = dict(resp or {})
                    out["clientOrderId"] = client_order_id
                    out["dedupe_state"] = dedupe_state
                    out["reused"] = dedupe_state != "NEW"
                    return out
                except Exception as submit_exc:
                    self.state.mark_order_failed(
                        tenant_id=str(getattr(self.ex_hub, "tenant_id", "default")),
                        exchange=ex_name,
                        client_order_id=client_order_id,
                        error_code=type(submit_exc).__name__,
                        retryable=True,
                    )
                    raise
        except Exception as e:
            msg = str(e)
            log.info(f"[{pair}] {ex_name} hub.create_limit_order falhou: {msg}")

            if self._is_paper_mode():
                log.warning(
                    f"[{pair}] {ex_name} modo PAPER: fallback CCXT real desabilitado para evitar ordens reais por engano."
                )
                return {
                    "id": f"paper_{ex_name}_{pair}_{side_l}_{int(time.time() * 1000)}",
                    "symbol": symbol_local,
                    "type": "limit",
                    "side": side_l,
                    "amount": float(qty_local),
                    "price": float(price_local),
                    "status": "open",
                    "info": {"paper": True, "fallback": True},
                }
            
            # Para MB, verificar se temos fallback CCXT disponÃ­vel
            if ex_name.lower() == "mercadobitcoin":
                if not self._mb_has_legacy_keys():
                    log.info("[MB] Sem API_KEY/SECRET legados no config â€” sem fallback CCXT.")
                    return {}
                # Se tem chaves legadas, tenta CCXT
                log.info("[MB] Tentando fallback CCXT com chaves legadas...")

        # 2) fallback para create_order nativo (ccxt/adapter), com preÃ§o local
        # SÃ³ tenta se for MB com chaves legadas ou outra exchange
        if ex_name.lower() != "mercadobitcoin" or self._mb_has_legacy_keys():
            ex = self.ex_hub.exchanges.get(ex_name)
            if ex:
                try:
                    return await ex.create_order(symbol_local, "limit", side_l, float(qty_local), float(price_local))
                except Exception as e:
                    log.warning(f"[{pair}] {ex_name} fallback CCXT tambÃ©m falhou: {e}")

        return {}  # retorna vazio se tudo falhou

    # ------------------------- reprecificaÃ§Ã£o -------------------------

    async def _reprice_one(
        self,
        ex_name: str,
        symbol_local: str,
        side: str,
        price_usdt: float,
        pair: str,
        cycle_id: str,
        min_notional_usdt: float,
        risk_percentage: float = 0.0,
        max_daily_loss: float = 0.0,
        amount_override: Optional[float] = None,
        cancel_before: bool = True,
    ):
        ex = self.ex_hub.exchanges.get(ex_name)
        if not ex:
            log.warning(f"[{pair}] {str(side).upper()} {ex_name}: exchange nÃ£o instanciada.")
            return

        side_l = str(side).lower()
        side_u = side_l.upper()
        if self._is_manual_cancel_blocked(pair, ex_name, side_l):
            return

        price_local = self._usdt_to_local_price(ex_name, symbol_local, price_usdt)
        price_local = self.adapters.round_price(ex_name, symbol_local, price_local)

        # CORREÃ‡ÃƒO CRÃTICA: Para Mercado Bitcoin, garantir arredondamento para 2 casas decimais
        if ex_name.lower() == "mercadobitcoin":
            price_local_antes = price_local
            price_local = round(price_local, 2)
            log.info(f"[{pair}] {ex_name} preÃ§o arredondado para step 0.01: {price_local_antes} -> {price_local}")

        if not self._band_hit(pair, ex_name, side_l, price_local):
            rec = self.orders.get(pair, {}).get(ex_name, {}).get(side_l)
            if rec:
                log.info(f"[{pair}] {ex_name} {side_u} mantendo ordem (Î”<{self.track_bps}bps): "
                         f"oid={rec.get('oid','?')} price_local={rec.get('price_local')}")
            return

        if amount_override is None:
            amount_raw = await self._calc_amount(
                ex_name,
                symbol_local,
                side_l,
                price_usdt,
                pair,
                risk_percentage=float(risk_percentage or 0.0),
                max_daily_loss=float(max_daily_loss or 0.0),
            )
        else:
            amount_raw = float(amount_override)

        ok, amount_grown, reason = self.adapters.enforce_minima(
            ex_name=ex_name,
            symbol_local=symbol_local,
            amount=float(amount_raw),
            price_usdt=float(price_usdt),
            router_min_notional_usdt=float(min_notional_usdt or self.min_router_notional),
        )
        if not ok or amount_grown <= 0:
            log.info(f"[{pair}] {ex_name} {side_u} {symbol_local} bloqueado por mÃ­nimos: {reason} "
                     f"(amount_calc={amount_raw} @ {price_usdt} USDT)")
            return

        base, quote = symbol_local.split("/")
        if side_l == "buy":
            q_free = await self._quote_free(ex, quote, ex_name=ex_name)
            q_usdt = (float(q_free) / float(self.ex_hub.usdt_brl)) if quote == "BRL" else float(q_free)
            max_amt_by_balance = (q_usdt / price_usdt) if price_usdt > 0 else 0.0
        else:
            b_free = await self._base_free(ex, base, ex_name=ex_name)
            max_amt_by_balance = float(b_free)

        amount_capped = min(float(amount_grown), float(max_amt_by_balance))
        amount_capped = self.adapters.round_amount(ex_name, symbol_local, amount_capped)

        ok2, reason2 = self._meets_minima_no_grow(
            ex_name=ex_name,
            symbol_local=symbol_local,
            amount=float(amount_capped),
            price_usdt=float(price_usdt),
            router_min_notional_usdt=float(min_notional_usdt or self.min_router_notional),
        )
        if not ok2:
            log.info(
                f"[{pair}] {ex_name} {side_u} {symbol_local} bloqueado por saldo: "
                f"{reason2} (amount_calc={amount_raw} -> grown={amount_grown} -> capped={amount_capped}, "
                f"max_by_balance={max_amt_by_balance})"
            )
            return

        prev = self.orders.get(pair, {}).get(ex_name, {}).get(side_l)
        is_move = bool(prev and prev.get("symbol") == symbol_local)
        prev_price = float(prev.get("price_local")) if is_move else None

        try:
            if cancel_before:
                await self._cancel_side(pair, ex_name, symbol_local, side_l)
        except Exception as e:
            log.warning(f"[{pair}] {ex_name} {symbol_local} {side_l} falha ao cancelar opens: {e}")

        try:
            qty_local = self.adapters.round_amount(ex_name, symbol_local, float(amount_capped))
            order = await self._create_limit_order_safe(
                ex_name=ex_name,
                pair=pair,
                symbol_local=symbol_local,
                side_l=side_l,
                qty_local=float(qty_local),
                price_usdt=float(price_usdt),
                price_local=float(price_local),
                cycle_id=str(cycle_id or ""),
            )

            # Robustez: sÃ³ segue se veio um dict com id
            if not isinstance(order, dict) or not (order.get("id") or order.get("orderId")):
                log.info(f"[{pair}] {ex_name} {side_u} {symbol_local}: create_order nÃ£o retornou id â€” nada foi registrado.")
                return

            oid = order.get("id") or order.get("orderId") or "?"
            client_order_id = str(order.get("clientOrderId") or "")
            dedupe_state = str(order.get("dedupe_state") or ("REUSED" if order.get("reused") else "NEW"))

            if bool((order.get("info") or {}).get("paper")):
                self._record_paper_execution(
                    pair=pair,
                    side=side_l,
                    qty=float(qty_local),
                    price_usdt=float(price_usdt),
                    risk_percentage=float(risk_percentage or 0.0),
                )

            base_ccy, quote_ccy = symbol_local.split("/")
            money = "R$" if quote_ccy.upper() == "BRL" else "$"
            msg_side = "Compra" if side_l == "buy" else "Venda"

            if is_move:
                self._emit_event(
                    f"{msg_side} movida: {qty_local} {base_ccy} na {ex_name} "
                    f"de {money} {prev_price} para {money} {price_local} ({symbol_local})."
                )
            else:
                self._emit_event(
                    f"{msg_side} aberta: {qty_local} {base_ccy} "
                    f"na {ex_name} a {money} {price_local} ({symbol_local})."
                )

            log.info(f"[{pair}] [{ex_name}] {side_u} {symbol_local} qty={qty_local} price={price_local} (oid={oid})")

            self._ensure_slot(pair, ex_name)
            self.orders[pair][ex_name][side_l] = {
                "ex": ex_name,
                "symbol": symbol_local,
                "oid": oid,
                "client_order_id": client_order_id,
                "client_order_id_short": self._short_client_order_id(client_order_id),
                "dedupe_state": dedupe_state,
                "price_local": float(price_local),
                "price_usdt": float(price_usdt),
                "qty": float(qty_local),
                "ts": time.time(),
                "filled": False,
            }

            try:
                await self._dedupe_side(pair, ex_name, symbol_local, side_l, str(oid))
            except Exception as e:
                log.warning(f"[dedupe] {ex_name} {symbol_local} {side_l} falhou ao deduplicar: {e}")

        except Exception as e:
            log.warning(f"[{pair}] {ex_name} {symbol_local} {side_l} create_order falhou: {e}")

    # -------- checagem de mÃ­nimos sem crescer --------

    def _meets_minima_no_grow(
        self,
        ex_name: str,
        symbol_local: str,
        amount: float,
        price_usdt: float,
        router_min_notional_usdt: float,
    ) -> Tuple[bool, str]:
        min_qty = float(self.adapters.get_min_qty(ex_name, symbol_local) or 0.0)
        min_notional_ex = float(self.adapters.get_min_notional_usdt(ex_name, symbol_local) or 0.0)
        min_notional = max(float(min_notional_ex), float(router_min_notional_usdt or 0.0))

        if amount <= 0 or price_usdt <= 0:
            return False, "zero"

        amount_q = self.adapters.round_amount(ex_name, symbol_local, float(amount))

        if min_qty > 0 and amount_q < min_qty:
            return False, f"amount<{min_qty}"

        if min_notional > 0 and (price_usdt * amount_q) < min_notional:
            return False, f"notional<{min_notional}"

        return True, ""

    # ------------------------- API pÃºblica -------------------------

    async def _reprice_side_local(
        self,
        pair: str,
        ex_name: str,
        side: str,
        spread: float,
        cycle_id: str,
        risk_percentage: float = 0.0,
        max_daily_loss: float = 0.0,
    ):
        symbol_local = self.ex_hub.resolve_symbol_local(ex_name, side.upper(), pair)
        if not symbol_local:
            return

        if side.lower() == "buy":
            ask_u = await self._best_ask_usdt(ex_name, symbol_local)
            if not ask_u or ask_u <= 0:
                return
            target_u = ask_u * (1.0 - float(spread))
            ok, why = await self._has_buy_capacity(ex_name, symbol_local, target_u)
            if not ok:
                if self.verbose_skips:
                    log.info(f"[{pair}] BUY skip {ex_name} ({symbol_local}): {why}")
                return
            await self._reprice_one(
                ex_name=ex_name,
                symbol_local=symbol_local,
                side="buy",
                price_usdt=float(target_u),
                pair=pair,
                cycle_id=str(cycle_id or ""),
                min_notional_usdt=float(self.min_router_notional),
                risk_percentage=float(risk_percentage or 0.0),
                max_daily_loss=float(max_daily_loss or 0.0),
            )
        else:
            bid_u = await self._best_bid_usdt(ex_name, symbol_local)
            if not bid_u or bid_u <= 0:
                return
            target_u = bid_u * (1.0 + float(spread))
            ok, why = await self._has_sell_capacity(ex_name, symbol_local, target_u)
            if not ok:
                if self.verbose_skips:
                    log.info(f"[{pair}] SELL skip {ex_name} ({symbol_local}): {why}")
                return
            await self._reprice_one(
                ex_name=ex_name,
                symbol_local=symbol_local,
                side="sell",
                price_usdt=float(target_u),
                pair=pair,
                cycle_id=str(cycle_id or ""),
                min_notional_usdt=float(self.min_router_notional),
                risk_percentage=float(risk_percentage or 0.0),
                max_daily_loss=float(max_daily_loss or 0.0),
            )

    async def reprice_pair(
        self,
        pair: str,
        ref_usdt: float,
        buy_target_usdt: float,
        sell_target_usdt: float,
        min_notional_usdt: float = 0.0,
        risk_percentage: float = 0.0,
        max_daily_loss: float = 0.0,
        cycle_id: Optional[str] = None,
    ):
        if not cycle_id:
            cycle_bucket = int(time.time() // 30)
            cycle_id = f"{pair}:{cycle_bucket}:{round(float(ref_usdt or 0.0),6)}:{round(float(buy_target_usdt or 0.0),6)}:{round(float(sell_target_usdt or 0.0),6)}"
        if self.anchor_mode == "LOCAL":
            buy_spread, sell_spread = self._pair_spreads(pair)
            log.info(f"[{pair}] reprice(LOCAL): spreads buy={buy_spread:.4f} sell={sell_spread:.4f}")

            for ex_name in self.ex_hub.enabled_ids:
                await self._reprice_side_local(
                    pair,
                    ex_name,
                    "buy",
                    buy_spread,
                    str(cycle_id),
                    risk_percentage=float(risk_percentage or 0.0),
                    max_daily_loss=float(max_daily_loss or 0.0),
                )
                if self.place_both_sides_per_ex:
                    await self._reprice_side_local(
                        pair,
                        ex_name,
                        "sell",
                        sell_spread,
                        str(cycle_id),
                        risk_percentage=float(risk_percentage or 0.0),
                        max_daily_loss=float(max_daily_loss or 0.0),
                    )
            return

        # ---- Comportamento legado (REF) ----
        log.info(f"[{pair}] reprice(REF): buy_tgt={buy_target_usdt:.6f} | sell_tgt={sell_target_usdt:.6f}")

        buy_pick = await self._pick_buy_exchange_orderbook(pair, buy_target_usdt)
        if not buy_pick:
            buy_pick = await self._pick_by_mids("buy", pair, buy_target_usdt)
            if buy_pick:
                log.info(f"[{pair}] BUY fallback via mids -> {buy_pick[0]} {buy_pick[1]} midâ‰ˆ{buy_pick[2]:.6f}")
        if buy_pick:
            ex_name, symbol_local, _best_ask = buy_pick
            await self._reprice_one(
                ex_name=ex_name, symbol_local=symbol_local, side="buy",
                price_usdt=float(buy_target_usdt), pair=pair,
                cycle_id=str(cycle_id),
                min_notional_usdt=float(min_notional_usdt or self.min_router_notional),
                risk_percentage=float(risk_percentage or 0.0),
                max_daily_loss=float(max_daily_loss or 0.0),
            )
        else:
            log.warning(f"[{pair}] BUY: nenhuma exchange com saldo suficiente.")

        sell_pick = await self._pick_sell_exchange_orderbook(pair, sell_target_usdt)
        if not sell_pick:
            sell_pick = await self._pick_by_mids("sell", pair, sell_target_usdt)
            if sell_pick:
                log.info(f"[{pair}] SELL fallback via mids -> {sell_pick[0]} {sell_pick[1]} midâ‰ˆ{sell_pick[2]:.6f}")
        if sell_pick:
            ex_name, symbol_local, _best_bid = sell_pick
            await self._reprice_one(
                ex_name=ex_name, symbol_local=symbol_local, side="sell",
                price_usdt=float(sell_target_usdt), pair=pair,
                cycle_id=str(cycle_id),
                min_notional_usdt=float(min_notional_usdt or self.min_router_notional),
                risk_percentage=float(risk_percentage or 0.0),
                max_daily_loss=float(max_daily_loss or 0.0),
            )
        else:
            log.warning(f"[{pair}] SELL: nenhuma exchange com saldo suficiente.")

    async def reprice(self, pair: str, buy_tgt_usdt: float, sell_tgt_usdt: float, cycle_id: Optional[str] = None) -> None:
        await self.reprice_pair(pair, ref_usdt=0.0, buy_target_usdt=buy_tgt_usdt, sell_target_usdt=sell_tgt_usdt, cycle_id=cycle_id)

    # ------------------------- suporte REF: escolhas por orderbook/mids -------------------------

    async def _pick_buy_exchange_orderbook(self, pair: str, price_usdt_for_checks: float) -> Optional[Tuple[str, str, float]]:
        if not self.buy_cheaper:
            return None
        best: Tuple[str, str, float] = (None, None, float("inf"))  # type: ignore
        for ex_name in self.ex_hub.enabled_ids:
            try:
                symbol_local = self.ex_hub.resolve_symbol_local(ex_name, "BUY", pair)
                if not symbol_local:
                    continue
                ok, why = await self._has_buy_capacity(ex_name, symbol_local, price_usdt_for_checks)
                if not ok:
                    if self.verbose_skips:
                        log.info(f"[{pair}] BUY skip {ex_name} ({symbol_local}): {why}")
                    continue
                ask_u = await self._best_ask_usdt(ex_name, symbol_local)
                if ask_u is None:
                    continue
                if float(ask_u) < float(best[2]):
                    best = (ex_name, symbol_local, float(ask_u))
            except Exception:
                continue
        return best if best[0] else None

    async def _pick_sell_exchange_orderbook(self, pair: str, price_usdt_for_checks: float) -> Optional[Tuple[str, str, float]]:
        if not self.sell_higher:
            return None
        best: Tuple[str, str, float] = (None, None, -1.0)  # type: ignore
        for ex_name in self.ex_hub.enabled_ids:
            try:
                symbol_local = self.ex_hub.resolve_symbol_local(ex_name, "SELL", pair)
                if not symbol_local:
                    continue
                ok, why = await self._has_sell_capacity(ex_name, symbol_local, price_usdt_for_checks)
                if not ok:
                    if self.verbose_skips:
                        log.info(f"[{pair}] SELL skip {ex_name} ({symbol_local}): {why}")
                    continue
                bid_u = await self._best_bid_usdt(ex_name, symbol_local)
                if bid_u is None:
                    continue
                if float(bid_u) > float(best[2]):
                    best = (ex_name, symbol_local, float(bid_u))
            except Exception:
                continue
        return best if best[0] else None

    async def _pick_by_mids(self, side: str, pair: str, price_usdt_for_checks: float) -> Optional[Tuple[str, str, float]]:
        cand: List[Tuple[str, str, float]] = []
        for ex_name in self.ex_hub.enabled_ids:
            try:
                symbol_local = self.ex_hub.resolve_symbol_local(ex_name, side.upper(), pair)
                if not symbol_local:
                    continue
                if side.lower() == "buy":
                    ok, why = await self._has_buy_capacity(ex_name, symbol_local, price_usdt_for_checks)
                else:
                    ok, why = await self._has_sell_capacity(ex_name, symbol_local, price_usdt_for_checks)
                if not ok:
                    if self.verbose_skips:
                        log.info(f"[{pair}] {side.upper()} skip {ex_name} ({symbol_local}): {why}")
                    continue
                mid_u = await self.ex_hub.get_mid_usdt(ex_name, side.upper(), pair)
                if symbol_local and mid_u:
                    cand.append((ex_name, symbol_local, float(mid_u)))
            except Exception:
                continue
        if not cand:
            return None
        if side.lower() == "buy":
            return min(cand, key=lambda x: x[2])
        return max(cand, key=lambda x: x[2])

    # ------------------------- pÃ³s-fill: abrir lado oposto -------------------------

    async def _open_opposite_after_fill(self, pair: str, ex_name: str, symbol_local: str, side_filled: str, qty_filled: float):
        if not self.auto_post_fill_opposite:
            return

        buy_spread, sell_spread = self._pair_spreads(pair)
        side_filled = side_filled.lower()
        opposite = "sell" if side_filled == "buy" else "buy"

        if opposite == "sell":
            bid_u = await self._best_bid_usdt(ex_name, symbol_local)
            if not bid_u or bid_u <= 0:
                return
            target_u = bid_u * (1.0 + sell_spread)
        else:
            ask_u = await self._best_ask_usdt(ex_name, symbol_local)
            if not ask_u or ask_u <= 0:
                return
            target_u = ask_u * (1.0 - buy_spread)

        amount_override = float(qty_filled) if self.post_fill_use_filled_qty else None

        await self._reprice_one(
            ex_name=ex_name,
            symbol_local=symbol_local,
            side=opposite,
            price_usdt=float(target_u),
            pair=pair,
            cycle_id=f"postfill:{pair}:{int(time.time() // 30)}:{opposite}",
            min_notional_usdt=float(self.min_router_notional),
            cancel_before=True,
            amount_override=amount_override,
        )

    # ------------------------- monitoramento de fills -------------------------

    async def _fetch_order_safe(self, ex_name: str, oid: str, symbol_local: str) -> Optional[Dict[str, Any]]:
        """
        Busca a ordem de forma resiliente usando Exchange Hub corrigido:
          - Usa ex_hub.fetch_order che jÃ¡ suporta MB v4
          - Fallback para CCXT se necessÃ¡rio
        """
        not_found_tokens = (
            "not found",
            "order not found",
            "unknown order",
            "does not exist",
            "doesn't exist",
            "invalid order",
            "invalid orderid",
            "invalid order id",
            "order_not_found",
            "order_not_exist",
            "order does not exist",
            "record not found",
            "no such order",
            "not_exist",
            "ordem nÃ£o encontrada",
            "ordem nao encontrada",
        )
        paper_mode = self._is_paper_mode()
        paper_oid = self._looks_paper_order_id(oid)

        try:
            # Usa o mÃ©todo fetch_order do Exchange Hub (CORRIGIDO)
            if hasattr(self.ex_hub, "fetch_order") and (not paper_mode or paper_oid):
                hub_resp = await self.ex_hub.fetch_order(
                    ex_name=ex_name,
                    order_id=oid,
                    global_pair=symbol_local,  # usa symbol_local como global_pair
                    side_hint=None
                )
                if isinstance(hub_resp, dict):
                    info = hub_resp.get("info") or {}
                    is_paper_info = bool(isinstance(info, dict) and info.get("paper"))
                    if paper_mode and is_paper_info and (not paper_oid):
                        # Em modo PAPER + oid real, ignorar resposta simulada e consultar exchange real.
                        pass
                    else:
                        return hub_resp
        except Exception as e:
            msg = str(e or "").lower()
            if any(token in msg for token in not_found_tokens):
                return {"status": "canceled", "id": oid, "symbol": symbol_local}
            log.warning(f"[fills] ex_hub.fetch_order falhou ({ex_name} {oid}): {e}")

        # Fallback para CCXT direto
        try:
            ex = self.ex_hub.exchanges.get(ex_name)
            if ex:
                return await ex.fetch_order(oid, symbol_local)
        except Exception as e:
            msg = str(e or "").lower()
            if any(token in msg for token in not_found_tokens):
                return {"status": "canceled", "id": oid, "symbol": symbol_local}
            log.warning(f"[fills] CCXT fetch_order tambÃ©m falhou ({ex_name} {oid}): {e}")

        return None

    @staticmethod
    def _get_float(d: Dict[str, Any], keys: List[str], default: float = 0.0) -> float:
        for k in keys:
            try:
                v = d.get(k)
                if v is None:
                    continue
                return float(v)
            except Exception:
                continue
        return float(default)

    @staticmethod
    def _slot_cleanup(orders_map: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]], pair: str, ex_name: str, side: str) -> None:
        try:
            orders_map.get(pair, {}).get(ex_name, {}).pop(side, None)
            if not orders_map.get(pair, {}).get(ex_name, {}):
                orders_map.get(pair, {}).pop(ex_name, None)
            if not orders_map.get(pair, {}):
                orders_map.pop(pair, None)
        except Exception:
            pass

    async def _open_order_ids_for_symbol(self, ex_name: str, symbol_local: str, force_exchange_query: bool = False) -> Optional[set]:
        """
        Retorna IDs de ordens abertas para exchange/sÃ­mbolo.
        Se a consulta falhar, retorna None (nÃ£o inferir cancelamento nesse caso).
        """
        try:
            if force_exchange_query:
                ex = self.ex_hub.exchanges.get(ex_name)
                if not ex:
                    return None
                try:
                    opens = await ex.fetch_open_orders(symbol_local)
                except Exception:
                    opens = await ex.fetch_open_orders(None)
            else:
                opens = await self.ex_hub.fetch_open_orders(ex_name, global_pair=None)
            ids = set()
            for o in (opens or []):
                try:
                    if symbol_local and not self._same_symbol(o.get("symbol") or "", symbol_local):
                        continue
                    oid = o.get("id") or o.get("orderId")
                    if oid:
                        ids.add(str(oid))
                except Exception:
                    continue
            return ids
        except Exception as e:
            log.warning(f"[fills] fetch_open_orders falhou ({ex_name} {symbol_local}): {e}")
            return None

    async def poll_fills(self) -> None:
        open_ids_cache: Dict[Tuple[str, str, bool], Optional[set]] = {}

        async def _get_open_ids_cached(ex_name: str, symbol_local: str, force_exchange_query: bool = False) -> Optional[set]:
            key = (str(ex_name), str(symbol_local), bool(force_exchange_query))
            if key not in open_ids_cache:
                open_ids_cache[key] = await self._open_order_ids_for_symbol(
                    ex_name,
                    symbol_local,
                    force_exchange_query=force_exchange_query,
                )
            return open_ids_cache.get(key)

        manual_cancel_statuses = {
            "canceled",
            "cancelled",
            "canceled_by_user",
            "cancelled_by_user",
        }

        for pair, ex_map in list(self.orders.items()):
            for ex_name, sides in list(ex_map.items()):
                for side, rec in list(sides.items()):
                    if rec.get("filled"):
                        continue

                    symbol_local = rec.get("symbol")
                    oid = rec.get("oid")
                    if not oid or not symbol_local:
                        continue

                    oid_str = str(oid)
                    expected_internal_cancel = oid_str in self._expected_cancel_oids
                    force_exchange_query = self._is_paper_mode() and (not self._looks_paper_order_id(oid))

                    try:
                        o = await self._fetch_order_safe(ex_name, oid, symbol_local)
                        if not isinstance(o, dict):
                            open_ids = await _get_open_ids_cached(
                                ex_name,
                                symbol_local,
                                force_exchange_query=force_exchange_query,
                            )
                            if open_ids is not None and oid_str not in open_ids:
                                self._slot_cleanup(self.orders, pair, ex_name, side)
                                self._expected_cancel_oids.discard(oid_str)
                                if expected_internal_cancel:
                                    log.info(
                                        "[%s] %s %s cancelamento interno confirmado por ausencia em open_orders (oid=%s).",
                                        pair,
                                        ex_name,
                                        side.upper(),
                                        oid,
                                    )
                                elif self.recreate_after_external_cancel:
                                    self._clear_manual_cancel_block(pair, ex_name, side)
                                    self._emit_event(
                                        f"[{pair}] {ex_name} {side.upper()} removida na exchange; recriando no proximo ciclo.",
                                        level="warn",
                                    )
                                    log.info(
                                        "[%s] %s %s sem retorno em fetch_order e ausente em open_orders (oid=%s). Slot limpo para recriacao.",
                                        pair,
                                        ex_name,
                                        side.upper(),
                                        oid,
                                    )
                                else:
                                    self._block_side_after_manual_cancel(
                                        pair=pair,
                                        ex_name=ex_name,
                                        side=side,
                                        oid=oid_str,
                                        reason="ausente em open_orders",
                                    )
                            continue
                    except Exception:
                        continue

                    status = str(o.get("status") or "").lower()
                    if status in (
                        "canceled",
                        "cancelled",
                        "expired",
                        "rejected",
                        "canceled_by_user",
                        "cancelled_by_user",
                        "cancelling",
                        "inactive",
                        "deleted",
                    ):
                        self._slot_cleanup(self.orders, pair, ex_name, side)
                        self._expected_cancel_oids.discard(oid_str)
                        if expected_internal_cancel:
                            log.info(
                                "[%s] %s %s cancelamento interno confirmado (status=%s, oid=%s).",
                                pair,
                                ex_name,
                                side.upper(),
                                status,
                                oid,
                            )
                        elif (not self.recreate_after_external_cancel) and (status in manual_cancel_statuses):
                            self._block_side_after_manual_cancel(
                                pair=pair,
                                ex_name=ex_name,
                                side=side,
                                oid=oid_str,
                                reason=f"status={status}",
                            )
                        else:
                            self._clear_manual_cancel_block(pair, ex_name, side)
                            self._emit_event(
                                f"[{pair}] {ex_name} {side.upper()} cancelada na exchange; recriando no proximo ciclo.",
                                level="warn",
                            )
                            log.info(
                                "[%s] %s %s cancelada externamente (oid=%s). Slot limpo para recriacao automatica.",
                                pair,
                                ex_name,
                                side.upper(),
                                oid,
                            )
                        continue

                    if status and status not in (
                        "open",
                        "new",
                        "created",
                        "pending",
                        "active",
                        "partially_filled",
                        "partial",
                        "partially-filled",
                        "closed",
                        "filled",
                        "executed",
                        "done",
                    ):
                        open_ids = await _get_open_ids_cached(
                            ex_name,
                            symbol_local,
                            force_exchange_query=force_exchange_query,
                        )
                        if open_ids is not None and oid_str not in open_ids:
                            self._slot_cleanup(self.orders, pair, ex_name, side)
                            self._expected_cancel_oids.discard(oid_str)
                            if expected_internal_cancel:
                                log.info(
                                    "[%s] %s %s cancelamento interno confirmado (status=%s, oid=%s).",
                                    pair,
                                    ex_name,
                                    side.upper(),
                                    status,
                                    oid,
                                )
                            elif self.recreate_after_external_cancel:
                                self._clear_manual_cancel_block(pair, ex_name, side)
                                self._emit_event(
                                    f"[{pair}] {ex_name} {side.upper()} removida na exchange; recriando no proximo ciclo.",
                                    level="warn",
                                )
                                log.info(
                                    "[%s] %s %s status=%s e ausente em open_orders (oid=%s). Slot limpo para recriacao.",
                                    pair,
                                    ex_name,
                                    side.upper(),
                                    status,
                                    oid,
                                )
                            else:
                                self._block_side_after_manual_cancel(
                                    pair=pair,
                                    ex_name=ex_name,
                                    side=side,
                                    oid=oid_str,
                                    reason=f"status={status}+ausente_em_open_orders",
                                )
                            continue

                    if status in ("closed", "filled", "executed", "done"):
                        rec["filled"] = True

                        filled = self._get_float(
                            o,
                            ["filled", "executedQuantity", "executedQty", "cumQty", "amount", "quantity"],
                            default=rec.get("qty") or 0.0,
                        )
                        avg = self._get_float(
                            o,
                            ["average", "avgPrice", "executedPrice", "price", "limitPrice"],
                            default=rec.get("price_local") or 0.0,
                        )

                        notional = filled * avg
                        base, quote = (symbol_local.split("/") + ["?"])[:2]
                        money = "R$" if (quote or "").upper() == "BRL" else "$"

                        if side == "buy":
                            self._emit_event(
                                f"Compra EXECUTADA: {filled} {base} na {ex_name} a {money} {avg} "
                                f"(~ {notional:.2f} {quote})."
                            )
                            log.info(f"[{pair}] BUY filled {filled} {base} @ {avg} ({ex_name}, {symbol_local})")
                            try:
                                await self._open_opposite_after_fill(pair, ex_name, symbol_local, "buy", filled)
                            except Exception as e:
                                log.warning(f"[{pair}] pos-fill SELL falhou ({ex_name} {symbol_local}): {e}")
                            self._alert_need_balance(ex_name, symbol_local, quote, "compra executada")
                        else:
                            self._emit_event(
                                f"Venda EXECUTADA: {filled} {base} na {ex_name} a {money} {avg} "
                                f"(~ {notional:.2f} {quote})."
                            )
                            log.info(f"[{pair}] SELL filled {filled} {base} @ {avg} ({ex_name}, {symbol_local})")
                            try:
                                await self._open_opposite_after_fill(pair, ex_name, symbol_local, "sell", filled)
                            except Exception as e:
                                log.warning(f"[{pair}] pos-fill BUY falhou ({ex_name} {symbol_local}): {e}")
                            self._alert_need_balance(ex_name, symbol_local, base, "venda executada")

        if self.one_cycle_exit:
            for pair, ex_map in self.orders.items():
                for ex_name, sides in ex_map.items():
                    if sides.get("buy", {}).get("filled") and sides.get("sell", {}).get("filled"):
                        log.info(f"[{pair}] {ex_name}: BUY e SELL executados. Conferir na corretora e reiniciar o bot.")
                        self._should_exit = True
                        return
    # ------------------------- utilitÃ¡rios -------------------------

    @property
    def should_exit(self) -> bool:
        return bool(self._should_exit)

    def snapshot_orders(self) -> List[Dict[str, Any]]:
        """
        Snapshot leve das ordens atuais, pensado para consumo por API/frontend.

        Retorna lista de dicts:
        {
            "pair": "BTC-USDT",
            "exchange": "mercadobitcoin",
            "side": "BUY" | "SELL",
            "symbol": "BTC/BRL",
            "price_local": 123456.78,
            "price_usdt": 12345.67,
            "qty": 0.001,
            "filled": False,
            "oid": "...",
            "ts": 1732920000.0
        }
        """
        out: List[Dict[str, Any]] = []
        for pair, ex_map in self.orders.items():
            for ex_name, sides in ex_map.items():
                for side, rec in sides.items():
                    out.append({
                        "pair": pair,
                        "exchange": ex_name,
                        "side": str(side).upper(),
                        "symbol": rec.get("symbol"),
                        "price_local": rec.get("price_local"),
                        "price_usdt": rec.get("price_usdt"),
                        "qty": rec.get("qty"),
                        "filled": bool(rec.get("filled")),
                        "oid": rec.get("oid"),
                        "ts": rec.get("ts"),
                    })
        return out
