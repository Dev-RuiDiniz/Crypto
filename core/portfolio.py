# core/portfolio.py
# Responsável por:
# - Ler do config o modo/valor de stake por par (FIXO_USDT ou PCT_BALANCE)
# - Consultar saldos nas exchanges via ExchangeHub
# - Normalizar saldos para USDT (BRL→USDT usando USDT_BRL_RATE)
# - Calcular quanto de USDT pode ser utilizado em cada ordem por exchange/par
# - Respeitar MIN_NOTIONAL_USDT (config [ROUTER])

from __future__ import annotations

import configparser
from typing import Dict, Tuple, Optional

try:
    from utils.logger import get_logger
except Exception:
    import logging
    def get_logger(name: str): return logging.getLogger(name)

log = get_logger("portfolio")


class Portfolio:
    def __init__(self, cfg: configparser.ConfigParser, exchange_hub):
        self.cfg = cfg
        self.ex_hub = exchange_hub

        # Limiar mínimo (em USDT) para abrir ordens (ignoramos valores abaixo disso)
        self.min_notional_usdt = float(self.cfg.get("ROUTER", "MIN_NOTIONAL_USDT", fallback="5"))

    # ---------------------------
    # Helpers de config

    def _stake_key(self, pair: str, suffix: str) -> str:
        # Ex.: BTC/USDT_MODE, BTC/USDT_VALUE
        return f"{pair}_MODE" if suffix == "MODE" else f"{pair}_VALUE"

    @staticmethod
    def _parse_float_with_comments(raw: str, default: float = 0.0) -> float:
        """
        Aceita valores com comentários/observações, ex.:
          "25 ; fixo em USDT"  -> 25.0
          "0.15 # 15% do saldo"-> 0.15
        """
        try:
            if raw is None:
                return float(default)
            s = str(raw)
            # remove comentários simples após ';' ou '#'
            for sep in (";", "#"):
                if sep in s:
                    s = s.split(sep, 1)[0]
            return float(s.strip() or default)
        except Exception:
            return float(default)

    def _stake_mode_value(self, pair: str) -> Tuple[str, float]:
        """
        Lê de [STAKE] o modo e valor para o par.
        Modos:
          - FIXO_USDT    -> VALUE = valor fixo em USDT por ordem
          - PCT_BALANCE  -> VALUE = percentual (0.10 = 10%) do saldo livre na exchange
        """
        sect = "STAKE"
        pair = pair.upper()
        mode = self.cfg.get(sect, self._stake_key(pair, "MODE"), fallback="FIXO_USDT").upper().strip()
        value_raw = self.cfg.get(sect, self._stake_key(pair, "VALUE"), fallback="0")
        value = self._parse_float_with_comments(value_raw, default=0.0)
        return mode, max(0.0, float(value))

    # ---------------------------
    # Saldos normalizados

    async def free_quote_balance_usdt(self, ex_name: str, pair: str) -> float:
        """
        Retorna o saldo livre na moeda de cotação do símbolo local (daquele par na exchange),
        normalizado para USDT.
        Ex.: se em mercadobitcoin o par for mapeado para BTC/BRL, pega FREE em BRL e divide por USDT_BRL_RATE.
        """
        try:
            symbol_local = self.ex_hub.resolve_symbol_local(ex_name, "BUY", pair)
            if not symbol_local:
                return 0.0
            free_u = await self.ex_hub.get_free_balance_normalized_usdt(ex_name, symbol_local)
            return float(free_u or 0.0)
        except Exception as e:
            log.warning(f"[{pair}] free_quote_balance_usdt falhou em {ex_name}: {e}")
            return 0.0

    async def free_base_balance_units(self, ex_name: str, pair: str) -> float:
        """
        Retorna o saldo livre da moeda BASE (em unidades de BASE) para o par na exchange.
        Útil para dimensionar SELL com base no que você tem de BASE.
        """
        try:
            # usamos o símbolo local do lado SELL para garantir mapeamento correto
            symbol_local = self.ex_hub.resolve_symbol_local(ex_name, "SELL", pair)
            if not symbol_local or "/" not in symbol_local:
                return 0.0
            base = symbol_local.split("/")[0].strip().upper()
            # Reaproveitamos o get_balance do hub (que já usa MB v4 se disponível)
            bal = await self.ex_hub.get_balance(ex_name)
            if "free" in bal and isinstance(bal["free"], dict):
                return float(bal["free"].get(base, 0.0) or 0.0)
            if isinstance(bal, dict) and base in bal:
                return float((bal.get(base) or {}).get("free", 0.0) or 0.0)
        except Exception as e:
            log.warning(f"[{pair}] free_base_balance_units falhou em {ex_name}: {e}")
        return 0.0

    async def snapshot_pair_balances_usdt(self, pair: str) -> Dict[str, float]:
        """
        Retorna um dicionário {exchange: free_quote_balance_em_USDT} para o par informado.
        Útil para logs e diagnósticos antes de montar as ordens.
        """
        out: Dict[str, float] = {}
        for ex in self.ex_hub.enabled_ids:
            try:
                out[ex] = await self.free_quote_balance_usdt(ex, pair)
            except Exception as e:
                log.warning(f"[{pair}] Falha ao obter saldo de {ex}: {e}")
                out[ex] = 0.0
        return out

    # ---------------------------
    # Cálculo de stake

    async def stake_for_order_usdt(self, ex_name: str, pair: str) -> float:
        """
        Calcula o *budget* em USDT para abrir uma ordem (compra ou venda) para um par em uma exchange.
        Aplica:
          - modo FIXO_USDT ou PCT_BALANCE (com base no saldo de QUOTE)
          - min(free_balance, stake_calculado)
          - MIN_NOTIONAL_USDT do config
        Observação: este método usa o saldo de QUOTE (compat com legado).
        Para SELL com orçamento baseado em BASE, veja stake_for_order_usdt_side(...).
        """
        mode, val = self._stake_mode_value(pair)
        free_u = await self.free_quote_balance_usdt(ex_name, pair)

        stake = 0.0
        if mode == "FIXO_USDT":
            stake = min(free_u, val)
        elif mode == "PCT_BALANCE":
            pct = max(0.0, min(1.0, val))
            stake = free_u * pct
        else:
            # fallback seguro: FIXO_USDT com 0
            stake = 0.0

        # Respeitar mínimo configurado
        if stake < self.min_notional_usdt:
            return 0.0

        return float(stake)

    async def stake_for_order_usdt_side(
        self,
        ex_name: str,
        pair: str,
        side: str,
        price_usdt_hint: Optional[float] = None,
    ) -> float:
        """
        Variante opcional sensível ao lado:
          - BUY  -> igual stake_for_order_usdt (usa QUOTE normalizado em USDT)
          - SELL -> converte BASE livre para USDT usando o mid (ou price_usdt_hint) do par
        Retorna 0.0 se não atingir MIN_NOTIONAL_USDT.
        """
        side_l = (side or "").strip().lower()
        if side_l not in ("buy", "sell"):
            return await self.stake_for_order_usdt(ex_name, pair)

        mode, val = self._stake_mode_value(pair)

        if side_l == "buy":
            # mesmo comportamento do método principal
            return await self.stake_for_order_usdt(ex_name, pair)

        # SELL: orçamento baseado em BASE * preço (USDT)
        try:
            base_free = await self.free_base_balance_units(ex_name, pair)
            if base_free <= 0:
                return 0.0

            # pega um preço em USDT: hint > mid
            price_u = float(price_usdt_hint or 0.0)
            if price_u <= 0.0:
                mid = await self.ex_hub.get_mid_usdt(ex_name, "SELL", pair)
                price_u = float(mid or 0.0)
            if price_u <= 0.0:
                return 0.0

            notional_u = base_free * price_u

            if mode == "FIXO_USDT":
                stake = min(notional_u, float(val))
            else:  # PCT_BALANCE
                pct = max(0.0, min(1.0, float(val)))
                stake = notional_u * pct

            if stake < self.min_notional_usdt:
                return 0.0
            return float(stake)
        except Exception as e:
            log.warning(f"[{pair}] stake_for_order_usdt_side SELL falhou em {ex_name}: {e}")
            return 0.0

    async def best_affordable_stake(self, pair: str) -> Optional[Dict[str, float]]:
        """
        Devolve um mapeamento {exchange: stake_usdt} para todas exchanges habilitadas onde
        o stake calculado >= MIN_NOTIONAL_USDT e saldo livre > 0.
        Retorna None se nenhuma exchange tiver stake suficiente.
        """
        candidates: Dict[str, float] = {}
        for ex in self.ex_hub.enabled_ids:
            try:
                stake = await self.stake_for_order_usdt(ex, pair)
                if stake >= self.min_notional_usdt:
                    candidates[ex] = float(stake)
            except Exception as e:
                log.warning(f"[{pair}] Erro ao calcular stake em {ex}: {e}")

        return candidates or None
