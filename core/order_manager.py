# core/order_manager.py
# Cria/ajusta/cancela ordens pendentes com base nos planos do OrderRouter.
# Mantém um pequeno registro em memória dos ids por (exchange, pair, side) e persiste no StateStore.

from __future__ import annotations

import configparser
import time
from typing import Dict, Tuple, Optional, List

try:
    from utils.logger import get_logger
    from utils.types import OrderPlan, LiveOrder
except Exception:
    import logging
    def get_logger(name: str): return logging.getLogger(name)
    class OrderPlan: ...
    class LiveOrder: ...

log = get_logger("order_manager")

# Rounding/adapters para respeitar price_step/amount_step e mínimos na comparação
try:
    from exchanges.adapters import Adapters
except Exception:
    Adapters = None  # fallback silencioso (sem quantização se não houver)

Key = Tuple[str, str, str]  # (ex_name, pair, side)


class OrderManager:
    def __init__(self, cfg: configparser.ConfigParser, ex_hub, state, risk):
        self.cfg = cfg
        self.ex_hub = ex_hub
        self.state = state
        self.risk = risk

        # registro simples em memória
        self._live: Dict[Key, LiveOrder] = {}

        # Anti-churn (coerente com o router)
        self.track_bps = int(self.cfg.get("ROUTER", "TRACK_LOCAL_BPS", fallback="0"))
        self.cooldown_sec = float(self.cfg.get("ROUTER", "REPRICE_COOLDOWN_SEC", fallback="0"))
        self._last_ts: Dict[Key, float] = {}

        # Adapters para quantização (se disponível)
        self.adapters = Adapters(self.cfg, ex_hub) if Adapters else None

        # Mínimo de notional do Router (em USDT)
        self.min_router_notional = float(self.cfg.get("ROUTER", "MIN_NOTIONAL_USDT", fallback="1"))

    # ------------------------------------------------------------
    def _round_price(self, ex_name: str, symbol_local: str, price_local: float) -> float:
        if self.adapters:
            try:
                return self.adapters.round_price(ex_name, symbol_local, float(price_local))
            except Exception:
                pass
        return float(price_local)

    def _round_amount(self, ex_name: str, symbol_local: str, amount: float) -> float:
        if self.adapters:
            try:
                return self.adapters.round_amount(ex_name, symbol_local, float(amount))
            except Exception:
                pass
        return float(amount)

    def _should_move(self, key: Key, symbol_local: str, new_price_local: float, new_amount: float) -> bool:
        """
        Decide se vale cancelar e recriar:
        - Respeita cooldown por (ex, pair, side)
        - Respeita banda em bps (TRACK_LOCAL_BPS) para preço
        - Ignora microdiferenças de quantidade após quantização
        """
        live = self._live.get(key)
        now = time.time()

        # Sem ordem viva -> precisa criar
        if not live or getattr(live, "status", "open") != "open":
            return True

        # Cooldown
        last = float(self._last_ts.get(key, 0.0))
        if self.cooldown_sec > 0 and (now - last) < self.cooldown_sec:
            return False

        # Comparação já quantizada
        live_p = float(getattr(live, "price_local", 0.0) or 0.0)
        live_a = float(getattr(live, "amount", 0.0) or 0.0)

        # Se não há drift relevante em preço, não move
        if live_p > 0.0 and self.track_bps > 0:
            drift = abs(new_price_local - live_p) / live_p
            if drift < (self.track_bps / 10000.0):
                # Mesmo que o preço esteja dentro da banda, se a quantidade mudou de fato (quantizada), então move.
                if abs(new_amount - live_a) <= 1e-12:
                    return False

        # Se quantidade e preço são idênticos após quantização, não move
        if (abs(new_price_local - live_p) <= 1e-12) and (abs(new_amount - live_a) <= 1e-12):
            return False

        return True

    # ------------------------------------------------------------

    async def ensure_orders(self, plans: List[OrderPlan]) -> None:
        """
        Garante que exista 1 ordem por (ex_name, pair, side) no preço/quantidade planejados.
        Se já existir diferente → cancel + recreate.
        Aplica anti-churn (bps + cooldown) e comparação com quantização.
        """
        for p in plans:
            key: Key = (p.ex_name, p.pair, p.side)
            # Resolve símbolo local (mapeamento BUY/SELL por exchange)
            symbol_local = getattr(p, "symbol_local", None) or self.ex_hub.resolve_symbol_local(p.ex_name, p.side.upper(), p.pair) or ""
            ex_name, pair, side = key

            # Quantiza preço/quantidade do plano antes de comparar
            price_local_plan = float(getattr(p, "price_local", 0.0) or 0.0)
            price_local_q = self._round_price(ex_name, symbol_local, price_local_plan)
            amount_plan = float(getattr(p, "amount", 0.0) or 0.0)
            amount_q = self._round_amount(ex_name, symbol_local, amount_plan)

            # Se amount/preço ficaram zero após quantização, pula
            if amount_q <= 0.0 or price_local_q <= 0.0:
                log.info(f"[SKIP] {pair} {side.upper()} @ {ex_name} {symbol_local} amount/price inviáveis após quantização "
                         f"(amount={amount_q}, price={price_local_q})")
                continue

            # Reforça mínimos (sem 'grow' aqui; quem cresce é o Router — aqui garantimos que ainda atende)
            price_usdt_for_check = float(getattr(p, "price_usdt", 0.0) or 0.0)
            if price_usdt_for_check <= 0.0:
                # Deriva de local -> USDT (corrige caso o plano não tenha setado)
                try:
                    price_usdt_for_check = self.ex_hub.to_usdt(ex_name, symbol_local, price_local_q)
                except Exception:
                    price_usdt_for_check = 0.0

            if self.adapters and price_usdt_for_check > 0.0:
                ok_min, why_min = self._meets_minima_no_grow(ex_name, symbol_local, amount_q, price_usdt_for_check)
                if not ok_min:
                    log.info(f"[SKIP] {pair} {side.upper()} @ {ex_name} {symbol_local} bloqueado por mínimos: {why_min} "
                             f"(amount={amount_q}, price_usdt={price_usdt_for_check})")
                    continue

            live = self._live.get(key)

            if live and getattr(live, "status", "open") == "open":
                if self._should_move(key, symbol_local, price_local_q, amount_q):
                    await self._cancel(key, live)
                    await self._create_quantized(key, p, symbol_local, price_local_q, amount_q, price_usdt_for_check)
                else:
                    # Mantém como está
                    continue
            else:
                await self._create_quantized(key, p, symbol_local, price_local_q, amount_q, price_usdt_for_check)

    async def cancel_all_for_pair(self, pair: str) -> None:
        keys = [k for k in list(self._live.keys()) if k[1] == pair]
        for key in keys:
            live = self._live.get(key)
            if live and getattr(live, "status", "open") == "open":
                await self._cancel(key, live)

    async def cancel_all(self) -> None:
        for key, live in list(self._live.items()):
            if live and getattr(live, "status", "open") == "open":
                await self._cancel(key, live)

    # ------------------------------------------------------------

    def _meets_minima_no_grow(self, ex_name: str, symbol_local: str, amount: float, price_usdt: float) -> Tuple[bool, str]:
        """
        Verifica min_qty e min_notional (USDT) sem aumentar a quantidade.
        (Espelha a checagem do Router para evitar enviar ordens que seriam rejeitadas.)
        """
        try:
            if not self.adapters:
                return True, ""
            min_qty = float(self.adapters.get_min_qty(ex_name, symbol_local) or 0.0)
            min_notional_ex = float(self.adapters.get_min_notional_usdt(ex_name, symbol_local) or 0.0)
            min_notional = max(min_notional_ex, float(self.min_router_notional or 0.0))

            if amount <= 0 or price_usdt <= 0:
                return False, "zero"

            amount_q = self._round_amount(ex_name, symbol_local, float(amount))

            if min_qty > 0 and amount_q < min_qty:
                return False, f"amount<{min_qty}"

            if min_notional > 0 and (price_usdt * amount_q) < min_notional:
                return False, f"notional<{min_notional}"

            return True, ""
        except Exception as e:
            return False, f"exception:{e}"

    async def _create_quantized(self, key: Key, p: OrderPlan, symbol_local: str, price_local_q: float, amount_q: float, price_usdt_hint: float = 0.0) -> None:
        """
        Cria a ordem usando valores já quantizados (evita rejeições e churn).
        Garante price_usdt válido (deriva de local se faltar).
        Trata mensagens comuns do MB v4 para logs mais claros.
        """
        ex_name, pair, side = key
        try:
            # Garante price_usdt
            price_usdt = float(getattr(p, "price_usdt", 0.0) or 0.0)
            if price_usdt <= 0.0:
                price_usdt = float(price_usdt_hint or 0.0)
            if price_usdt <= 0.0:
                try:
                    price_usdt = self.ex_hub.to_usdt(ex_name, symbol_local, price_local_q)
                except Exception:
                    pass

            resp = await self.ex_hub.create_limit_order(
                ex_name=ex_name,
                global_pair=pair,
                side=side,
                amount=float(amount_q),
                price_usdt=float(price_usdt),
                params=None,
            )
            order_id = str(resp.get("id", "")) or str(resp.get("orderId", "")) or ""
            status = str(resp.get("status", "open")) or "open"

            live = LiveOrder(
                order_id=order_id,
                pair=pair,
                side=side,
                ex_name=ex_name,
                symbol_local=symbol_local,
                price_local=float(price_local_q),
                amount=float(amount_q),
                status=status,
            )
            self._live[key] = live
            self._last_ts[key] = time.time()

            log.info(
                f"[CREATE] {pair} {side.UPPER()} @ {ex_name} {symbol_local} "
                f"price_local={price_local_q:.8f} amount={amount_q:.8f} id={order_id} note={getattr(p,'note','') or ''}"
            )

            # >>> PERSISTÊNCIA <<<
            try:
                self.state.record_order_create(live)
            except Exception as e:
                log.warning(f"[state_store] create falhou para {order_id}: {e}")

        except Exception as e:
            msg = str(e)
            # Logs “amigáveis” para MB v4
            if ex_name == "mercadobitcoin":
                if "404" in msg or "Not Found" in msg:
                    log.error("[MB v4] create_limit_order retornou 404. "
                              "Cheque: par suportado, mínimos (qty/notional) e validade do bearer token.")
                elif "requires \"apiKey\"" in msg or "requires apiKey" in msg:
                    log.error("[MB] A API legada exige API_KEY/SECRET no config (não confundir com login v4).")
                else:
                    log.error(f"[CREATE][FAIL] {pair} {side} @ MB: {msg}")
            else:
                log.error(f"[CREATE][FAIL] {pair} {side} @ {ex_name}: {msg}")

    async def _create(self, key: Key, p: OrderPlan) -> None:
        """
        Mantida por compatibilidade (usa valores brutos do plano).
        Hoje o fluxo normal passa por _create_quantized.
        """
        ex_name, pair, side = key
        symbol_local = getattr(p, "symbol_local", None) or self.ex_hub.resolve_symbol_local(ex_name, side.upper(), pair) or ""
        price_local_q = self._round_price(ex_name, symbol_local, float(getattr(p, "price_local", 0.0) or 0.0))
        amount_q = self._round_amount(ex_name, symbol_local, float(getattr(p, "amount", 0.0) or 0.0))
        await self._create_quantized(key, p, symbol_local, price_local_q, amount_q)

    async def _cancel(self, key: Key, live: LiveOrder) -> None:
        ex_name, pair, side = key
        try:
            await self.ex_hub.cancel_order(
                ex_name=ex_name,
                order_id=live.order_id,
                global_pair=pair,
                side_hint=str(side).lower(),  # padroniza com o router
            )
            live.status = "canceled"
            self._last_ts[key] = time.time()
            log.info(f"[CANCEL] {pair} {side.upper()} @ {ex_name} id={live.order_id}")

            # >>> PERSISTÊNCIA <<<
            try:
                self.state.record_order_cancel(live)
            except Exception as e:
                log.warning(f"[state_store] cancel falhou para {live.order_id}: {e}")

        except Exception as e:
            log.error(f"[CANCEL][FAIL] {pair} {side} @ {ex_name} id={live.order_id}: {e}")
