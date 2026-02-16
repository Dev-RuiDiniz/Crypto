# core/strategy_spread.py
# Calcula o "preço geral do ativo" (referencial) e define alvos buy/sell com base no spread.
# - Lê spreads por par (seção [SPREAD]) – ex.: BTC/USDT=0.03 (3%)
# - Suporta ANCHOR_MODE em [STRATEGY]: LOCAL (default) ou REF
#   * LOCAL: o router deve ancorar nos asks/bids locais ± spread
#   * REF:   alvos = ref * (1±spread)

from __future__ import annotations

import asyncio
import time
import statistics
from typing import Dict, Any, List, Optional, Tuple

import configparser

try:
    from utils.logger import get_logger
except Exception:
    import logging
    def get_logger(name: str): return logging.getLogger(name)

log = get_logger("strategy")


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return float(default)
        # protege contra "0.10 ; coment" mesmo com inline_comment_prefixes
        s = str(x).split(";")[0].split("#")[0].strip()
        if s == "":
            return float(default)
        return float(s)
    except Exception:
        return float(default)


class StrategySpread:
    def __init__(self, cfg: configparser.ConfigParser):
        self.cfg = cfg

        # Referência de preço (para REF mode)
        self.ref_mode = self.cfg.get("GLOBAL", "REF_PRICE", fallback="MEDIAN").upper()

        # Threshold/cooldown para reprecificação
        self.reprice_bps = _safe_float(self.cfg.get("GLOBAL", "REPRICE_THRESHOLD_BPS", fallback="15"), 15.0)
        self.cooldown_sec = _safe_float(self.cfg.get("GLOBAL", "ADJUST_COOLDOWN_SEC", fallback="5"), 5.0)

        # Lista de pares
        raw_pairs = self.cfg.get("PAIRS", "LIST", fallback="")
        self.pairs: List[str] = [s.strip().upper() for s in raw_pairs.split(",") if s.strip()]

        # Anchor mode: LOCAL (default) ou REF
        amode = self.cfg.get("STRATEGY", "ANCHOR_MODE", fallback="LOCAL").strip().upper()
        if amode not in ("LOCAL", "REF"):
            amode = "LOCAL"
        self.anchor_mode = amode

        # Estado anterior para dif e cooldown
        self.last_state: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------
    # API “simples” para o monitor atual

    def get_anchor_mode(self) -> str:
        """Retorna o modo de âncora (LOCAL|REF)."""
        return self.anchor_mode

    def spread_of(self, pair: str) -> float:
        """
        Retorna o spread (0.0..1.0) do par, com parse seguro.
        Fallback = 0.0 para evitar cair silenciosamente em 10%.
        """
        pair = pair.strip().upper()
        val = self.cfg.get("SPREAD", pair, fallback=None)
        return _safe_float(val, 0.0)

    def targets_for(self, pair: str, ref_price_usdt: float) -> Tuple[float, float]:
        """
        Retorna (buy_target_usdt, sell_target_usdt).
        - Em ANCHOR_MODE=REF: usa ref * (1±spread)
        - Em ANCHOR_MODE=LOCAL: devolve valores informativos com base na ref,
          mas o router deve ancorar nos asks/bids locais ± spread.
        """
        ref = _safe_float(ref_price_usdt, 0.0)
        s = self.spread_of(pair)
        if ref <= 0.0 or s <= 0.0:
            # sem spread ou ref -> devolve ref “puro” para não travar o fluxo
            return float(ref), float(ref)
        buy = ref * (1.0 - s)
        sell = ref * (1.0 + s)
        return float(buy), float(sell)

    def moved_enough(self, old_ref: Optional[float], new_ref: Optional[float]) -> bool:
        """Checa variação mínima em bps para disparar reprecificação."""
        try:
            if old_ref is None or new_ref is None:
                return True
            old_ref = _safe_float(old_ref, 0.0)
            new_ref = _safe_float(new_ref, 0.0)
            if old_ref <= 0.0:
                return True
            delta = abs(new_ref - old_ref)
            bps = (delta / old_ref) * 10_000.0
            return bps >= float(self.reprice_bps)
        except Exception:
            return True

    # ------------------------------------------------------
    # API “completa” (mantida do seu script anterior)

    async def compute_targets(self, ex_hub, pair: str) -> Optional[Dict[str, Any]]:
        """
        Coleta mids por exchange com diagnóstico, calcula o referencial
        (MEDIAN ou VWAP aproximado) e retorna buy/sell targets + estado.
        Em ANCHOR_MODE=LOCAL, os alvos são informativos — o router deve
        usar asks/bids locais ± spread (este método expõe o spread correto).
        """
        pair = pair.upper()
        spread = self._get_spread(pair)
        if spread <= 0:
            log.warning(f"[{pair}] Spread inválido/zerado no config. Ignorando.")
            return None

        mids, errors = await self._collect_mids_usdt(ex_hub, pair)
        if not mids:
            # Não há dado suficiente — mas devolvemos os erros para log do monitor
            if errors:
                for e in errors:
                    log.warning(f"[{pair}] mids indisponíveis em {e['ex']} ({e['symbol_local']}): {e['err']} - {e['detail']}")
            return {"pair": pair, "errors": errors, "changed": False, "anchor_mode": self.anchor_mode}

        ref = await self._calc_reference(ex_hub, pair, mids)
        if ref is None or ref <= 0:
            return {
                "pair": pair,
                "errors": errors + [{"ex": "strategy", "symbol_local": "-", "err": "ref_calc", "detail": "referencial inválido"}],
                "changed": False,
                "anchor_mode": self.anchor_mode,
            }

        ref = float(ref)
        # Mesmo em LOCAL, calculamos alvos com base na ref apenas para logging.
        buy = ref * (1.0 - spread)
        sell = ref * (1.0 + spread)
        ts = time.time()

        changed = self._should_update(pair, ref, ts)
        state = {
            "pair": pair,
            "ref": ref,
            "buy_usdt": float(buy),
            "sell_usdt": float(sell),
            "spread": float(spread),
            "quotes_used": [{"ex": ex, "mid_usdt": float(mid)} for ex, mid in mids],
            "errors": errors,
            "ts": ts,
            "changed": changed,
            "anchor_mode": self.anchor_mode,
        }

        self.last_state[pair] = {"ts": ts, "ref": ref, "buy": float(buy), "sell": float(sell), "spread": float(spread)}
        return state

    def get_last_targets(self, pair: str) -> Optional[Dict[str, Any]]:
        pair = pair.upper()
        st = self.last_state.get(pair)
        if not st:
            return None
        return {
            "pair": pair,
            "ref": float(st["ref"]),
            "buy_usdt": float(st["buy"]),
            "sell_usdt": float(st["sell"]),
            "spread": float(st["spread"]),
            "ts": float(st["ts"]),
            "changed": False,
            "anchor_mode": self.anchor_mode,
        }

    # ----------------------------- Internos -----------------------------

    def _get_spread(self, pair: str) -> float:
        """Idêntico a spread_of, mantido por compatibilidade interna."""
        return self.spread_of(pair)

    async def _collect_mids_usdt(self, ex_hub, pair: str) -> Tuple[List[Tuple[str, float]], List[Dict[str, Any]]]:
        """
        Busca mid-price em USDT por exchange com diagnóstico detalhado.
        Retorna (mids_ok, errors_list).
        """
        async def one(ex_name: str):
            return await ex_hub.probe_mid_usdt(ex_name, "BUY", pair)

        # usa apenas exchanges habilitadas
        tasks = [one(ex_name) for ex_name in getattr(ex_hub, "enabled_ids", [])]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        mids: List[Tuple[str, float]] = []
        errors: List[Dict[str, Any]] = []
        for r in results:
            if not r:
                continue
            if r.get("ok"):
                mids.append((r["ex"], _safe_float(r["mid_usdt"], 0.0)))
            else:
                errors.append(r)
        # remove mids <= 0
        mids = [(ex, m) for (ex, m) in mids if m and m > 0]
        return mids, errors

    async def _calc_reference(self, ex_hub, pair: str, mids: List[Tuple[str, float]]) -> Optional[float]:
        if not mids:
            return None
        if self.ref_mode == "MEDIAN":
            return float(statistics.median([_safe_float(m) for _, m in mids]))
        if self.ref_mode == "VWAP":
            vwap = await self._approx_vwap_top(ex_hub, pair)
            if vwap is not None and vwap > 0:
                return float(vwap)
            return float(statistics.median([_safe_float(m) for _, m in mids]))
        return float(statistics.median([_safe_float(m) for _, m in mids]))

    async def _approx_vwap_top(self, ex_hub, pair: str) -> Optional[float]:
        async def one(ex_name: str):
            try:
                symbol_local = ex_hub.resolve_symbol_local(ex_name, "BUY", pair)
                ob = await ex_hub.get_orderbook(ex_name, symbol_local, limit=1)
                bid_p = _safe_float(ob["bids"][0][0], 0.0) if ob.get("bids") else 0.0
                bid_q = _safe_float(ob["bids"][0][1], 0.0) if ob.get("bids") else 0.0
                ask_p = _safe_float(ob["asks"][0][0], 0.0) if ob.get("asks") else 0.0
                ask_q = _safe_float(ob["asks"][0][1], 0.0) if ob.get("asks") else 0.0

                bid_p_u = ex_hub.to_usdt(ex_name, symbol_local, bid_p) if bid_p > 0 else None
                ask_p_u = ex_hub.to_usdt(ex_name, symbol_local, ask_p) if ask_p > 0 else None

                if bid_p_u is not None and ask_p_u is not None:
                    mid_u = (bid_p_u + ask_p_u) / 2.0
                elif bid_p_u is not None:
                    mid_u = bid_p_u
                elif ask_p_u is not None:
                    mid_u = ask_p_u
                else:
                    return None

                weight = 0.0
                if bid_p_u is not None and bid_q > 0:
                    weight += bid_p_u * bid_q
                if ask_p_u is not None and ask_q > 0:
                    weight += ask_p_u * ask_q
                if weight <= 0:
                    weight = 1.0
                return (float(mid_u), float(weight))
            except Exception:
                return None

        # usa apenas exchanges habilitadas
        results = await asyncio.gather(*[one(ex) for ex in getattr(ex_hub, "enabled_ids", [])], return_exceptions=False)
        vals = [(mid, w) for r in results if r and isinstance(r, tuple) for (mid, w) in [r]]
        if not vals:
            return None
        num = sum(float(mid) * float(w) for mid, w in vals)
        den = sum(float(w) for _, w in vals)
        if den <= 0:
            return None
        return float(num / den)

    def _should_update(self, pair: str, new_ref: float, ts_now: float) -> bool:
        prev = self.last_state.get(pair)
        if not prev:
            return True
        # cooldown
        try:
            if self.cooldown_sec > 0 and (float(ts_now) - _safe_float(prev["ts"], 0.0)) < float(self.cooldown_sec):
                return False
        except Exception:
            pass
        old_ref = _safe_float(prev.get("ref"), 0.0)
        if old_ref <= 0:
            return True
        diff_bps = abs(float(new_ref) - old_ref) / old_ref * 10_000.0
        return diff_bps >= float(self.reprice_bps)
