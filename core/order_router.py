from __future__ import annotations

import asyncio
import time
from typing import Optional, Tuple, List, Dict, Any
import configparser

try:
    from utils.logger import get_logger, get_user_logger
except Exception:
    import logging
    def get_logger(name: str): return logging.getLogger(name)
    def get_user_logger(name: str): return logging.getLogger(name)

log = get_logger("router")          # técnico -> arquivo detalhado
ulog = get_user_logger("router")    # humano -> console (opcional)

from exchanges.adapters import Adapters, ceil_step


class OrderRouter:
    """
    Modo novo (padrão): ANCHOR_MODE=LOCAL
    - Para CADA exchange habilitada:
      * BUY: ancora no best ask LOCAL e lança ordem limit em ask * (1 - buy_spread)
      * SELL: ancora no best bid LOCAL e lança ordem limit em bid * (1 + sell_spread)
    - Manutenção por exchange/lado (banda em bps + cooldown)
    - Pós-fill: abre automaticamente o lado oposto na MESMA exchange (se configurado)
    - Alerta de reabastecimento **após fills**

    Compat legacy (ANCHOR_MODE=REF):
    - Mantém roteamento por alvos em USDT (modo antigo)
    """

    def __init__(self, cfg: configparser.ConfigParser, ex_hub, portfolio, risk, state):
        self.cfg = cfg
        self.ex_hub = ex_hub
        self.portfolio = portfolio
        self.risk = risk
        self.state = state

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

        # “grudar na exchange” (compat legado)
        self.sticky_per_side = self.cfg.getboolean("ROUTER", "STICKY_PER_SIDE", fallback=True)

        # Logs de “skip por saldo” somente no arquivo detalhado (console não recebe)
        self.verbose_skips = self.cfg.getboolean("LOG", "VERBOSE_SKIPS", fallback=False)

        # Eventos no console e sink opcional para painel
        self.console_events = self.cfg.getboolean("LOG", "CONSOLE_EVENTS", fallback=False)
        self._event_sink = None  # callable opcional para enviar eventos ao painel

        # >>> NOVOS flags
        self.place_both_sides_per_ex = self.cfg.getboolean("ROUTER", "PLACE_BOTH_SIDES_PER_EXCHANGE", fallback=True)
        self.alert_cooldown_sec = float(self.cfg.get("ROUTER", "ALERT_COOLDOWN_SEC", fallback="120"))
        self.auto_post_fill_opposite = self.cfg.getboolean("ROUTER", "AUTO_POST_FILL_OPPOSITE", fallback=True)
        self.post_fill_use_filled_qty = self.cfg.getboolean("ROUTER", "POST_FILL_USE_FILLED_QTY", fallback=True)

        # Deduplicação de eventos (reduzir flood visual)
        self.event_dedup_sec = float(self.cfg.get("LOG", "EVENT_DEDUP_SEC", fallback="90"))
        self._event_last_ts: Dict[str, float] = {}

        # Cache de saldos
        self.balance_ttl = float(self.cfg.get("ROUTER", "BALANCE_TTL_SEC", fallback="8"))
        self._balance_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

        # Estrutura: orders[pair][ex_name][side] = {...}
        self.orders: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}

        # Cooldown para alertas de reabastecimento (após fill)
        self._alert_last_ts: Dict[Tuple[str, str, str], float] = {}

        self._should_exit = False

    # ------------------------- eventos / integração com painel -------------------------

    def set_event_sink(self, sink):
        """Define um callback opcional para receber eventos humanos (painel)."""
        self._event_sink = sink

    def _emit_event(self, msg: str, level: str = "info"):
        """Envia evento para painel (se houver) ou console (se habilitado), com deduplicação por tempo."""
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
        Retorna (buy_spread, sell_spread) como frações.
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

    async def _best_ask_usdt(self, ex_name: str, symbol_local: str) -> Optional[float]:
        try:
            ob = await self.ex_hub.get_orderbook(ex_name, symbol_local, limit=1)
            if ob and ob.get("asks"):
                ask_local = float(ob["asks"][0][0])
                return self.ex_hub.to_usdt(ex_name, symbol_local, ask_local)
        except Exception as e:
            log.warning(f"[{ex_name}] best_ask falhou em {symbol_local}: {e}")
        return None

    async def _best_bid_usdt(self, ex_name: str, symbol_local: str) -> Optional[float]:
        try:
            ob = await self.ex_hub.get_orderbook(ex_name, symbol_local, limit=1)
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

    def _alert_need_balance(self, ex_name: str, symbol_local: str, asset: str, reason: str):
        key = (ex_name, symbol_local, asset.upper())
        now = time.time()
        last = self._alert_last_ts.get(key, 0.0)
        if now - last < self.alert_cooldown_sec:
            return
        self._alert_last_ts[key] = now
        self._emit_event(f"[ABASTECER] {ex_name} {symbol_local}: reabastecer {asset.upper()} — {reason}.", level="warn")
        log.info(f"[ALERTA] {ex_name} {symbol_local}: reabastecer {asset.upper()} — {reason}.")

    # --------- checagem de capacidade por saldo + mínimos ----------

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

    # ------------------------- cálculo de quantidade (stake) -------------------------

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

        if mode == "FIXO_USDT":
            notional_usdt = max(0.0, float(value))
            # bot_config.risk_percentage: limite adicional por operação.
            risk_frac = max(0.0, min(1.0, float(risk_percentage) / 100.0)) if risk_percentage > 0 else 0.0
            if side_l == "buy":
                q_free = await self._quote_free(ex, quote, ex_name=ex_name)
                q_usdt = (float(q_free) / float(self.ex_hub.usdt_brl)) if quote == "BRL" else float(q_free)
                notional_usdt = min(notional_usdt, q_usdt)
                if risk_frac > 0:
                    notional_usdt = min(notional_usdt, q_usdt * risk_frac)
                if max_daily_loss > 0:
                    notional_usdt = min(notional_usdt, float(max_daily_loss))
                if price_usdt > 0:
                    amount = notional_usdt / price_usdt
            else:
                if price_usdt > 0:
                    amount = notional_usdt / price_usdt
                b_free = await self._base_free(ex, base, ex_name=ex_name)
                amount = min(amount, float(b_free))
                if risk_frac > 0:
                    amount = min(amount, float(b_free) * risk_frac)
        else:
            pct = max(0.0, min(1.0, float(value)))
            if risk_percentage > 0:
                pct = min(pct, max(0.0, min(1.0, float(risk_percentage) / 100.0)))
            if side_l == "buy":
                q_free = await self._quote_free(ex, quote, ex_name=ex_name)
                q_usdt = (float(q_free) / float(self.ex_hub.usdt_brl)) if quote == "BRL" else float(q_free)
                notional_usdt = q_usdt * pct
                if max_daily_loss > 0:
                    notional_usdt = min(notional_usdt, float(max_daily_loss))
                if price_usdt > 0:
                    amount = notional_usdt / price_usdt
            else:
                b_free = await self._base_free(ex, base, ex_name=ex_name)
                amount = float(b_free) * pct

        return float(amount)

    # ------------------------- núcleo: reprecificação por exchange -------------------------

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

    # --------- helpers p/ normalização de símbolo ao filtrar ---------
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
        Cancela ordens abertas do lado informado para simplificar a reprecificação.
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
                cancelled += 1
                await asyncio.sleep(0.10)
            except Exception as e:
                errors += 1
                log.warning(f"[cancel_side] {ex_name} {symbol_local} {side_l} falhou ao cancelar {oid}: {e}")

        # verificação rápida
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
                    cancelled += 1
                    await asyncio.sleep(0.15)
                except Exception as e:
                    errors += 1
                    log.warning(f"[cancel_side][retry] {ex_name} {symbol_local} {side_l} cancel {oid} erro: {e}")

        if cancelled or errors:
            log.info(f"[cancel_side] {ex_name} {symbol_local} {side_l}: canceladas={cancelled} erros={errors}")

    async def _dedupe_side(self, pair: str, ex_name: str, symbol_local: str, side: str, keep_oid: str):
        """
        Garante no máximo 1 ordem por exchange/símbolo/lado.
        Cancela quaisquer outras abertas que não sejam keep_oid (via HUB).
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
                log.info(f"[boot] {ex_name}: nenhum cancelamento necessário.")
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

            # verificação pós-cancelamento
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
            self._emit_event(f"Boot: {ex_name} — ordens canceladas={cancelled}, erros={errors}, restantes={still}.")

    # ------------------------- criação de ordem (com fallback) -------------------------

    def _mb_has_legacy_keys(self) -> bool:
        sect = "EXCHANGES.mercadobitcoin"
        api = self.cfg.get(sect, "API_KEY", fallback="").strip()
        sec = self.cfg.get(sect, "API_SECRET", fallback="").strip()
        return bool(api and sec)

    async def _create_limit_order_safe(
        self,
        ex_name: str,
        pair: str,
        symbol_local: str,
        side_l: str,
        qty_local: float,
        price_usdt: float,
        price_local: float,
    ) -> Dict[str, Any]:
        """
        Tenta via ExchangeHub.create_limit_order (preço em USDT).
        Para MercadoBitcoin: usa MB v4 adapter corrigido via Exchange Hub.
        """
        # 1) SEMPRE tentar via hub primeiro (MB v4 e afins) - CORRIGIDO
        try:
            if hasattr(self.ex_hub, "create_limit_order"):
                return await self.ex_hub.create_limit_order(
                    ex_name=ex_name,
                    global_pair=pair,
                    side=side_l,
                    amount=float(qty_local),
                    price_usdt=float(price_usdt),
                )
        except Exception as e:
            msg = str(e)
            log.info(f"[{pair}] {ex_name} hub.create_limit_order falhou: {msg}")
            
            # Para MB, verificar se temos fallback CCXT disponível
            if ex_name.lower() == "mercadobitcoin":
                if not self._mb_has_legacy_keys():
                    log.info("[MB] Sem API_KEY/SECRET legados no config — sem fallback CCXT.")
                    return {}
                # Se tem chaves legadas, tenta CCXT
                log.info("[MB] Tentando fallback CCXT com chaves legadas...")

        # 2) fallback para create_order nativo (ccxt/adapter), com preço local
        # Só tenta se for MB com chaves legadas ou outra exchange
        if ex_name.lower() != "mercadobitcoin" or self._mb_has_legacy_keys():
            ex = self.ex_hub.exchanges.get(ex_name)
            if ex:
                try:
                    return await ex.create_order(symbol_local, "limit", side_l, float(qty_local), float(price_local))
                except Exception as e:
                    log.warning(f"[{pair}] {ex_name} fallback CCXT também falhou: {e}")

        return {}  # retorna vazio se tudo falhou

    # ------------------------- reprecificação -------------------------

    async def _reprice_one(
        self,
        ex_name: str,
        symbol_local: str,
        side: str,
        price_usdt: float,
        pair: str,
        min_notional_usdt: float,
        risk_percentage: float = 0.0,
        max_daily_loss: float = 0.0,
        amount_override: Optional[float] = None,
        cancel_before: bool = True,
    ):
        ex = self.ex_hub.exchanges.get(ex_name)
        if not ex:
            log.warning(f"[{pair}] {str(side).upper()} {ex_name}: exchange não instanciada.")
            return

        side_l = str(side).lower()
        side_u = side_l.upper()

        price_local = self._usdt_to_local_price(ex_name, symbol_local, price_usdt)
        price_local = self.adapters.round_price(ex_name, symbol_local, price_local)

        # CORREÇÃO CRÍTICA: Para Mercado Bitcoin, garantir arredondamento para 2 casas decimais
        if ex_name.lower() == "mercadobitcoin":
            price_local_antes = price_local
            price_local = round(price_local, 2)
            log.info(f"[{pair}] {ex_name} preço arredondado para step 0.01: {price_local_antes} -> {price_local}")

        if not self._band_hit(pair, ex_name, side_l, price_local):
            rec = self.orders.get(pair, {}).get(ex_name, {}).get(side_l)
            if rec:
                log.info(f"[{pair}] {ex_name} {side_u} mantendo ordem (Δ<{self.track_bps}bps): "
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
            log.info(f"[{pair}] {ex_name} {side_u} {symbol_local} bloqueado por mínimos: {reason} "
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
            )

            # Robustez: só segue se veio um dict com id
            if not isinstance(order, dict) or not (order.get("id") or order.get("orderId")):
                log.info(f"[{pair}] {ex_name} {side_u} {symbol_local}: create_order não retornou id — nada foi registrado.")
                return

            oid = order.get("id") or order.get("orderId") or "?"

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

    # -------- checagem de mínimos sem crescer --------

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

    # ------------------------- API pública -------------------------

    async def _reprice_side_local(
        self,
        pair: str,
        ex_name: str,
        side: str,
        spread: float,
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
    ):
        if self.anchor_mode == "LOCAL":
            buy_spread, sell_spread = self._pair_spreads(pair)
            log.info(f"[{pair}] reprice(LOCAL): spreads buy={buy_spread:.4f} sell={sell_spread:.4f}")

            for ex_name in self.ex_hub.enabled_ids:
                await self._reprice_side_local(
                    pair,
                    ex_name,
                    "buy",
                    buy_spread,
                    risk_percentage=float(risk_percentage or 0.0),
                    max_daily_loss=float(max_daily_loss or 0.0),
                )
                if self.place_both_sides_per_ex:
                    await self._reprice_side_local(
                        pair,
                        ex_name,
                        "sell",
                        sell_spread,
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
                log.info(f"[{pair}] BUY fallback via mids -> {buy_pick[0]} {buy_pick[1]} mid≈{buy_pick[2]:.6f}")
        if buy_pick:
            ex_name, symbol_local, _best_ask = buy_pick
            await self._reprice_one(
                ex_name=ex_name, symbol_local=symbol_local, side="buy",
                price_usdt=float(buy_target_usdt), pair=pair,
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
                log.info(f"[{pair}] SELL fallback via mids -> {sell_pick[0]} {sell_pick[1]} mid≈{sell_pick[2]:.6f}")
        if sell_pick:
            ex_name, symbol_local, _best_bid = sell_pick
            await self._reprice_one(
                ex_name=ex_name, symbol_local=symbol_local, side="sell",
                price_usdt=float(sell_target_usdt), pair=pair,
                min_notional_usdt=float(min_notional_usdt or self.min_router_notional),
                risk_percentage=float(risk_percentage or 0.0),
                max_daily_loss=float(max_daily_loss or 0.0),
            )
        else:
            log.warning(f"[{pair}] SELL: nenhuma exchange com saldo suficiente.")

    async def reprice(self, pair: str, buy_tgt_usdt: float, sell_tgt_usdt: float) -> None:
        await self.reprice_pair(pair, ref_usdt=0.0, buy_target_usdt=buy_tgt_usdt, sell_target_usdt=sell_tgt_usdt)

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

    # ------------------------- pós-fill: abrir lado oposto -------------------------

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
            min_notional_usdt=float(self.min_router_notional),
            cancel_before=True,
            amount_override=amount_override,
        )

    # ------------------------- monitoramento de fills -------------------------

    async def _fetch_order_safe(self, ex_name: str, oid: str, symbol_local: str) -> Optional[Dict[str, Any]]:
        """
        Busca a ordem de forma resiliente usando Exchange Hub corrigido:
          - Usa ex_hub.fetch_order che já suporta MB v4
          - Fallback para CCXT se necessário
        """
        try:
            # Usa o método fetch_order do Exchange Hub (CORRIGIDO)
            if hasattr(self.ex_hub, "fetch_order"):
                return await self.ex_hub.fetch_order(
                    ex_name=ex_name,
                    order_id=oid,
                    global_pair=symbol_local,  # usa symbol_local como global_pair
                    side_hint=None
                )
        except Exception as e:
            log.warning(f"[fills] ex_hub.fetch_order falhou ({ex_name} {oid}): {e}")

        # Fallback para CCXT direto
        try:
            ex = self.ex_hub.exchanges.get(ex_name)
            if ex:
                return await ex.fetch_order(oid, symbol_local)
        except Exception as e:
            log.warning(f"[fills] CCXT fetch_order também falhou ({ex_name} {oid}): {e}")

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

    async def poll_fills(self) -> None:
        for pair, ex_map in list(self.orders.items()):
            for ex_name, sides in list(ex_map.items()):
                for side, rec in list(sides.items()):
                    if rec.get("filled"):
                        continue
                    symbol_local = rec.get("symbol")
                    oid = rec.get("oid")
                    if not oid or not symbol_local:
                        continue
                    try:
                        o = await self._fetch_order_safe(ex_name, oid, symbol_local)
                        if not isinstance(o, dict):
                            continue
                    except Exception:
                        continue

                    status = str(o.get("status") or "").lower()
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
                                f"(≈ {notional:.2f} {quote})."
                            )
                            log.info(f"[{pair}] BUY filled {filled} {base} @ {avg} ({ex_name}, {symbol_local})")
                            try:
                                await self._open_opposite_after_fill(pair, ex_name, symbol_local, "buy", filled)
                            except Exception as e:
                                log.warning(f"[{pair}] pós-fill SELL falhou ({ex_name} {symbol_local}): {e}")
                            self._alert_need_balance(ex_name, symbol_local, quote, "compra executada")
                        else:
                            self._emit_event(
                                f"Venda EXECUTADA: {filled} {base} na {ex_name} a {money} {avg} "
                                f"(≈ {notional:.2f} {quote})."
                            )
                            log.info(f"[{pair}] SELL filled {filled} {base} @ {avg} ({ex_name}, {symbol_local})")
                            try:
                                await self._open_opposite_after_fill(pair, ex_name, symbol_local, "sell", filled)
                            except Exception as e:
                                log.warning(f"[{pair}] pós-fill BUY falhou ({ex_name} {symbol_local}): {e}")
                            self._alert_need_balance(ex_name, symbol_local, base, "venda executada")

        if self.one_cycle_exit:
            for pair, ex_map in self.orders.items():
                for ex_name, sides in ex_map.items():
                    if sides.get("buy", {}).get("filled") and sides.get("sell", {}).get("filled"):
                        log.info(f"[{pair}] {ex_name}: BUY e SELL executados. Conferir na corretora e reiniciar o bot.")
                        self._should_exit = True
                        return

    # ------------------------- utilitários -------------------------

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
