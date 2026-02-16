# core/risk_manager.py
# Limites básicos de risco:
# - nº máximo de ordens abertas por par/exchange (com overrides por par/lado)
# - teto de exposição bruta em USDT (com overrides por par e por exchange)
# - kill switch por drawdown (placeholder; cálculo do equity fica para versão futura)

from __future__ import annotations

import configparser
from typing import Dict, Tuple, Optional

try:
    from utils.logger import get_logger
except Exception:
    import logging
    def get_logger(name: str): return logging.getLogger(name)

log = get_logger("risk")


def _parse_int_with_comments(raw: str, default: int) -> int:
    try:
        if raw is None:
            return int(default)
        s = str(raw)
        for sep in (";", "#"):
            if sep in s:
                s = s.split(sep, 1)[0]
        return int(s.strip() or default)
    except Exception:
        return int(default)


def _parse_float_with_comments(raw: str, default: float) -> float:
    try:
        if raw is None:
            return float(default)
        s = str(raw)
        for sep in (";", "#"):
            if sep in s:
                s = s.split(sep, 1)[0]
        return float(s.strip() or default)
    except Exception:
        return float(default)


class RiskManager:
    def __init__(self, cfg: configparser.ConfigParser):
        self.cfg = cfg

        # Globais (back-compat)
        self.max_open_per_pair_ex = _parse_int_with_comments(
            self.cfg.get("RISK", "MAX_OPEN_ORDERS_PER_PAIR_PER_EXCHANGE", fallback="2"),
            default=2,
        )
        self.max_gross_exposure_usdt = _parse_float_with_comments(
            self.cfg.get("RISK", "MAX_GROSS_EXPOSURE_USDT", fallback="0"),
            default=0.0,
        )
        self.kill_dd_pct = _parse_float_with_comments(
            self.cfg.get("RISK", "KILL_SWITCH_DRAWDOWN_PCT", fallback="0"),
            default=0.0,
        )
        self.cancel_all_on_kill = self.cfg.getboolean("RISK", "CANCEL_ALL_ON_KILLSWITCH", fallback=True)

    # ----------------------------------------------------
    # RESOLUÇÃO DE LIMITES (com overrides opcionais)

    def _pair_key(self, pair: str, suffix: str) -> str:
        # BTC/USDT_MAX_OPEN_PER_EXCHANGE   |  BTC/USDT_BUY_MAX_OPEN_PER_EXCHANGE
        return f"{pair.upper()}_{suffix}"

    def _ex_key(self, ex_name: str, suffix: str) -> str:
        # mercadobitcoin_MAX_GROSS_EXPOSURE_USDT
        return f"{ex_name.lower()}_{suffix}"

    def _get_int(self, sect: str, key: str, default: int) -> int:
        if not self.cfg.has_option(sect, key):
            return int(default)
        return _parse_int_with_comments(self.cfg.get(sect, key, fallback=str(default)), default=default)

    def _get_float(self, sect: str, key: str, default: float) -> float:
        if not self.cfg.has_option(sect, key):
            return float(default)
        return _parse_float_with_comments(self.cfg.get(sect, key, fallback=str(default)), default=default)

    def open_limit_for(self, pair: str, side: Optional[str] = None) -> int:
        """
        Ordem de prioridade para limite de 'open por par/exchange':
          1) [RISK] <PAIR>_<SIDE>_MAX_OPEN_PER_EXCHANGE
          2) [RISK] <PAIR>_MAX_OPEN_PER_EXCHANGE
          3) [RISK] MAX_OPEN_ORDERS_PER_PAIR_PER_EXCHANGE (global)
        """
        sect = "RISK"
        if side:
            k_side = self._pair_key(pair, f"{side.upper()}_MAX_OPEN_PER_EXCHANGE")
            v = self._get_int(sect, k_side, default=self.max_open_per_pair_ex)
            if self.cfg.has_option(sect, k_side):
                return v
        k_pair = self._pair_key(pair, "MAX_OPEN_PER_EXCHANGE")
        if self.cfg.has_option(sect, k_pair):
            return self._get_int(sect, k_pair, default=self.max_open_per_pair_ex)
        return int(self.max_open_per_pair_ex)

    def gross_cap_for(self, pair: Optional[str] = None, ex_name: Optional[str] = None) -> float:
        """
        Ordem de prioridade para teto de exposição bruta:
          1) [RISK] <PAIR>_MAX_GROSS_EXPOSURE_USDT
          2) [RISK] <EXCHANGE>_MAX_GROSS_EXPOSURE_USDT
          3) [RISK] MAX_GROSS_EXPOSURE_USDT (global)
        """
        sect = "RISK"
        if pair:
            k_pair = self._pair_key(pair, "MAX_GROSS_EXPOSURE_USDT")
            if self.cfg.has_option(sect, k_pair):
                return self._get_float(sect, k_pair, default=self.max_gross_exposure_usdt)
        if ex_name:
            k_ex = self._ex_key(ex_name, "MAX_GROSS_EXPOSURE_USDT")
            if self.cfg.has_option(sect, k_ex):
                return self._get_float(sect, k_ex, default=self.max_gross_exposure_usdt)
        return float(self.max_gross_exposure_usdt)

    # ----------------------------------------------------
    # CHECAGENS BÁSICAS (back-compat)

    def can_open_more(self, open_count_for_pair_ex: int) -> bool:
        """
        Retorna True se ainda pode abrir mais ordens para esse (pair, exchange).
        (Mantida para compatibilidade; usa o limite global configurado.)
        """
        return open_count_for_pair_ex < self.max_open_per_pair_ex

    def exposure_ok(self, current_gross_usdt: float, planned_delta_usdt: float) -> bool:
        """
        Verifica teto de exposição bruta (somatório de |preço_usdt * qty| de ordens vivas).
        Se max_gross_exposure_usdt == 0 => sem limite.
        (Mantida para compatibilidade; usa o teto global.)
        """
        if self.max_gross_exposure_usdt <= 0:
            return True
        return (current_gross_usdt + max(0.0, planned_delta_usdt)) <= self.max_gross_exposure_usdt

    # ----------------------------------------------------
    # CHECAGENS COM OVERRIDES (novas, opcionais)

    def can_open_more_for(self, pair: str, side: Optional[str], open_count_for_pair_ex: int) -> bool:
        """
        Usa a hierarquia de limites por par/lado descrita em open_limit_for().
        """
        limit = self.open_limit_for(pair, side=side)
        return int(open_count_for_pair_ex) < int(limit)

    def exposure_ok_for(
        self,
        pair: Optional[str],
        ex_name: Optional[str],
        current_gross_usdt: float,
        planned_delta_usdt: float,
    ) -> bool:
        """
        Usa a hierarquia de tetos de exposição em gross_cap_for().
        """
        cap = float(self.gross_cap_for(pair=pair, ex_name=ex_name))
        if cap <= 0:
            return True
        return (float(current_gross_usdt) + max(0.0, float(planned_delta_usdt))) <= cap

    # ----------------------------------------------------
    # KILL SWITCH

    def should_kill_switch(self, equity_peak: float, equity_now: float) -> bool:
        """
        Placeholder para gatilho de kill switch por drawdown. Retorna True se dd% >= limiar.
        """
        if self.kill_dd_pct <= 0:
            return False
        if equity_peak <= 0:
            return False
        dd_pct = (equity_peak - equity_now) / equity_peak * 100.0
        return dd_pct >= self.kill_dd_pct

    # ----------------------------------------------------
    # UTILITÁRIO OPCIONAL: normalizar notional local -> USDT

    @staticmethod
    def normalize_notional_usdt(
        *,
        ex_hub,
        ex_name: str,
        symbol_local: str,
        price_local: float,
        amount: float,
    ) -> float:
        """
        Converte notional local (price_local * amount) para USDT usando a lógica do ExchangeHub,
        que já trata BRL->USDT (USDT_BRL_RATE) e outros quotes.
        """
        try:
            local_notional = float(price_local) * float(amount)
            # converte um preço local para USDT dividindo pelo fator inverso da conversão de preço
            # Reaproveitamos a função do hub para converter um preço local para USDT:
            # to_usdt(ex, symbol_local, price_local)
            price_1u_usdt = float(ex_hub.to_usdt(ex_name, symbol_local, float(price_local)))
            if price_1u_usdt <= 0:
                return 0.0
            # Como price_1u_usdt é o preço de 1 unidade em USDT, notional_usdt = amount * price_1u_usdt
            return float(amount) * float(price_1u_usdt)
        except Exception:
            return 0.0

    # ----------------------------------------------------
    # ATALHO OPCIONAL “TUDO EM UM”

    def can_open(
        self,
        *,
        pair: str,
        side: Optional[str],
        ex_name: Optional[str],
        open_count_for_pair_ex: int,
        current_gross_usdt: float,
        planned_delta_usdt: float,
    ) -> Tuple[bool, str]:
        """
        Combina checagem de limite de ordens + teto de exposição com overrides.
        Retorna (ok, motivo_ou_vazio).
        """
        if not self.can_open_more_for(pair, side, open_count_for_pair_ex):
            return False, "max_open_limit_hit"

        if not self.exposure_ok_for(pair, ex_name, current_gross_usdt, planned_delta_usdt):
            return False, "gross_exposure_cap_hit"

        return True, ""
