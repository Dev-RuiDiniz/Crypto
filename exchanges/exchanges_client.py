# exchanges/exchanges_client.py
# CCXT para dados públicos + adapter nativo MB v4 para privadas (saldo/ordens) quando disponível.

from __future__ import annotations

import asyncio
import configparser
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List, Iterable, Set

from tenacity import retry, stop_after_attempt, wait_exponential_jitter

import ccxt.async_support as ccxt
from ccxt.base.errors import (
    AuthenticationError,
    DDoSProtection,
    ExchangeNotAvailable,
    NetworkError,
    RequestTimeout,
    ExchangeError,
    InvalidNonce,
)

try:
    from utils.logger import get_logger
except Exception:
    import logging
    def get_logger(name: str): return logging.getLogger(name)

# Adapter MB v4 (privadas)
from .adapters import MBV4Adapter
from core.credentials_service import ExchangeCredentialsService, CredentialsNotFoundError

log = get_logger("exchanges")

# --------- Tipos ---------
@dataclass
class Quote:
    bid: Optional[float]
    ask: Optional[float]
    mid: Optional[float]
    raw_quote_ccy: str

# --------- Helpers ---------

ALIASES_CCXT = {
    "gateio": "gate",
    "mexc3": "mexc",
}

def _quote_ccy(symbol: str) -> str:
    if "/" in symbol:
        return symbol.split("/")[1].strip().upper()
    return symbol.upper()

def _safe_float(x: Any) -> Optional[float]:
    try: return float(x)
    except Exception: return None

def _parse_pairs(cfg: configparser.ConfigParser) -> List[str]:
    raw = cfg.get("PAIRS", "LIST", fallback="")
    return [s.strip() for s in raw.split(",") if s.strip()]

def _get_retry_deco(max_attempts: int, backoff_ms: int):
    return retry(
        reraise=True,
        stop=stop_after_attempt(max(1, max_attempts)),
        wait=wait_exponential_jitter(initial=backoff_ms / 1000.0, max=8.0),
    )

def _ccxt_id_candidates(ex_name: str) -> List[str]:
    # Mantemos candidatos para lidar com variações históricas no CCXT
    if ex_name.lower() == "mercadobitcoin":
        return ["mercadobitcoin", "mercado"]
    low = ex_name.lower()
    return [ALIASES_CCXT.get(low, low)]

# --------- Classe ---------

class ExchangeHub:
    def __init__(
        self,
        config: configparser.ConfigParser,
        credentials_service: Optional[ExchangeCredentialsService] = None,
        tenant_id: str = "default",
    ):
        self.cfg = config
        self.tenant_id = tenant_id
        self.credentials_service = credentials_service or ExchangeCredentialsService(config)
        self.mode = self.cfg.get("GLOBAL", "MODE", fallback="PAPER").upper()
        self.usdt_brl = float(self.cfg.get("GLOBAL", "USDT_BRL_RATE", fallback="5.50"))
        
        # CORREÇÃO CRÍTICA: Leitura de parâmetros de rede com fallback para [BOOT]
        # Primeiro tenta [GLOBAL], depois [BOOT], depois default
        self.http_timeout = self._get_param_with_fallback(
            "HTTP_TIMEOUT_SEC", 15, 
            fallback_sections=["BOOT"],  # Tenta BOOT se não encontrar em GLOBAL
            fallback_keys=["HTTP_TIMEOUT"]  # Tenta chave antiga
        )
        
        self.max_retries = self._get_param_with_fallback(
            "MAX_RETRIES", 3,
            fallback_sections=["BOOT"]
        )
        
        self.retry_backoff_ms = self._get_param_with_fallback(
            "RETRY_BACKOFF_MS", 400,
            fallback_sections=["BOOT"]
        )
        
        # Log dos parâmetros carregados
        log.info(
            f"[ExchangeHub] Parâmetros de rede carregados: "
            f"HTTP_TIMEOUT_SEC={self.http_timeout}s, "
            f"MAX_RETRIES={self.max_retries}, "
            f"RETRY_BACKOFF_MS={self.retry_backoff_ms}ms"
        )
        
        self.enabled_ids: List[str] = self._discover_enabled()
        self.exchanges: Dict[str, ccxt.Exchange] = {}
        self._markets_loaded: Dict[str, bool] = {}
        self.symbol_map = self._build_symbol_map()

        # Adapter nativo MB v4 (privadas)
        self.mb_v4: Optional[MBV4Adapter] = None
        if "mercadobitcoin" in [x.lower() for x in self.enabled_ids]:
            mb_cfg = configparser.ConfigParser(interpolation=None)
            mb_cfg.read_dict({s: dict(self.cfg.items(s)) for s in self.cfg.sections()})
            if not mb_cfg.has_section("EXCHANGES.mercadobitcoin"):
                mb_cfg.add_section("EXCHANGES.mercadobitcoin")
            try:
                mb_creds = self.credentials_service.get_credentials(self.tenant_id, "mercadobitcoin")
                mb_cfg["EXCHANGES.mercadobitcoin"]["api_key"] = mb_creds.api_key
                mb_cfg["EXCHANGES.mercadobitcoin"]["api_secret"] = mb_creds.api_secret
                mb_cfg["EXCHANGES.mercadobitcoin"]["password"] = mb_creds.passphrase or ""
                mb_cfg["EXCHANGES.mercadobitcoin"]["mbv4_login"] = ""
                mb_cfg["EXCHANGES.mercadobitcoin"]["mbv4_password"] = ""
                mb_cfg["EXCHANGES.mercadobitcoin"]["mbv4_bearer_token"] = ""
            except CredentialsNotFoundError:
                pass
            self.mb_v4 = MBV4Adapter(mb_cfg)
            if self.mb_v4.enabled and not (self.mb_v4.token or (self.mb_v4.login_user and self.mb_v4.login_pass)):
                log.warning("[mercadobitcoin v4] ativo porém sem token/login — privadas desabilitadas no MB até configurar MBV4_BEARER_TOKEN ou MBV4_LOGIN/MBV4_PASSWORD.")

    # ---------------- helpers de configuração ----------------
    
    def _get_param_with_fallback(
        self, 
        key: str, 
        default: int,
        fallback_sections: Optional[List[str]] = None,
        fallback_keys: Optional[List[str]] = None
    ) -> int:
        """
        Obtém um parâmetro inteiro com múltiplos fallbacks:
        1. Tenta [GLOBAL][key]
        2. Tenta seções de fallback (ex: [BOOT][key])
        3. Tenta chaves alternativas (ex: HTTP_TIMEOUT ao invés de HTTP_TIMEOUT_SEC)
        4. Usa default
        """
        sections_to_try = ["GLOBAL"]
        if fallback_sections:
            sections_to_try.extend(fallback_sections)
            
        keys_to_try = [key]
        if fallback_keys:
            keys_to_try.extend(fallback_keys)
        
        for section in sections_to_try:
            if not self.cfg.has_section(section):
                continue
                
            for k in keys_to_try:
                try:
                    value = self.cfg.get(section, k)
                    if value is not None:
                        result = int(value)
                        log.debug(f"[ExchangeHub] Parâmetro {key}={result} carregado de [{section}][{k}]")
                        return result
                except (configparser.NoOptionError, ValueError):
                    continue
        
        log.debug(f"[ExchangeHub] Parâmetro {key} não encontrado, usando default={default}")
        return default

    # ---------------- config

    def _discover_enabled(self) -> List[str]:
        ids = []
        for sect in self.cfg.sections():
            if not sect.startswith("EXCHANGES."):
                continue
            ex_name = sect.split(".", 1)[1]
            if self.cfg.getboolean(sect, "ENABLED", fallback=False):
                ids.append(ex_name)
        return ids

    def _build_symbol_map(self) -> Dict[str, Dict[str, str]]:
        """
        Aceita chaves do [SYMBOLS] como:
          novadax.SOL/USDT.BUY=SOL/BRL
          novadax.SOL/USDT.SELL=SOL/BRL
          mexc.SELL=BTC/USDT       (fallback global por side)
        """
        out: Dict[str, Dict[str, str]] = {}
        sect = "SYMBOLS"
        if not self.cfg.has_section(sect):
            return out
        for key, value in self.cfg.items(sect):
            k = key.strip().lower()
            v = value.strip()
            if "." not in k:
                continue
            ex, rest = k.split(".", 1)
            out.setdefault(ex, {})
            # Restos possíveis:
            # <pair>.buy | <pair>.sell | buy | sell
            if rest.endswith(".buy"):
                pair = rest[:-4].upper()
                out[ex][f"{pair}.BUY"] = v
            elif rest.endswith(".sell"):
                pair = rest[:-5].upper()
                out[ex][f"{pair}.SELL"] = v
            elif rest in ("buy", "sell"):
                out[ex][rest.upper()] = v
        return out

    def _pick_symbol(self, ex_name: str, side: str, global_pair: str) -> str:
        sideU = side.upper()
        ex = ex_name.lower()
        pairU = (global_pair or "").upper()
        if ex in self.symbol_map:
            m = self.symbol_map[ex]
            if pairU and f"{pairU}.{sideU}" in m:
                return m[f"{pairU}.{sideU}"]
            if sideU in m:
                return m[sideU]
        # se nada mapeado, usa o próprio par informado
        return pairU or global_pair

    def _both_side_symbols(self, ex_name: str, global_pair: str) -> List[str]:
        """
        Devolve os símbolos locais candidatos (BUY e SELL) para um par global.
        Remove duplicatas.
        """
        buy = self._pick_symbol(ex_name, "BUY", global_pair)
        sell = self._pick_symbol(ex_name, "SELL", global_pair)
        out: List[str] = []
        if buy: out.append(buy)
        if sell and sell != buy: out.append(sell)
        return out

    def _build_auth_params(self, ex_name: str) -> Dict[str, Any]:
        creds = self.credentials_service.get_credentials(self.tenant_id, ex_name)
        return {
            "apiKey": creds.api_key,
            "secret": creds.api_secret,
            "password": creds.passphrase,
        }

    # ---------------- boot

    async def connect_all(self):
        for ex_name in self.enabled_ids:
            ex = await self._instantiate_exchange(ex_name)
            if ex is None:
                log.error(f"[{ex_name}] não foi possível instanciar a exchange (verifique id/versão no CCXT).")
                continue
            self.exchanges[ex_name] = ex

        await asyncio.gather(*[
            self._safe_load_markets(ex_name)
            for ex_name in self.exchanges.keys()
        ])

    async def _instantiate_exchange(self, ex_name: str) -> Optional[ccxt.Exchange]:
        try:
            params = self._build_auth_params(ex_name)
        except CredentialsNotFoundError:
            log.error(
                "[%s] credenciais ausentes no cofre para tenant=%s; cadastre exchange_credentials ativa.",
                ex_name,
                self.tenant_id,
            )
            raise
        for cand in _ccxt_id_candidates(ex_name):
            if not hasattr(ccxt, cand):
                continue
            try:
                ex_cls = getattr(ccxt, cand)
                ex = ex_cls({
                    "apiKey": params.get("apiKey"),
                    "secret": params.get("secret"),
                    "password": params.get("password"),
                    "enableRateLimit": True,
                    "timeout": self.http_timeout * 1000,
                    "options": {
                        "defaultType": "spot",
                        "recvWindow": 60_000,  # útil p/ MEXC
                    },
                })
                if cand == "mexc":
                    await self._sync_time_and_window_mexc(ex)
                return ex
            except Exception as e:
                log.warning(f"[{ex_name}] falha ao instanciar id '{cand}': {e}")
                continue
        return None

    async def _sync_time_and_window_mexc(self, ex: ccxt.Exchange):
        try:
            try:
                ex.options = ex.options or {}
                ex.options["recvWindow"] = max(int(ex.options.get("recvWindow", 5000)), 60_000)
            except Exception:
                pass
            try:
                if hasattr(ex, "load_time_difference"):
                    await ex.load_time_difference()
                elif hasattr(ex, "fetch_time"):
                    await ex.fetch_time()
            except Exception as e:
                log.warning(f"[mexc] sync time falhou (prossegue mesmo assim): {e}")
        except Exception:
            pass

    async def close_all(self):
        # fecha ccxt
        try:
            await asyncio.gather(*[
                self.exchanges[ex_name].close()
                for ex_name in list(self.exchanges.keys())
                if self.exchanges.get(ex_name)
            ])
        except Exception:
            pass
        # fecha adapter mb v4
        if self.mb_v4:
            await self.mb_v4.close()

    # ---------------- ferramenta central de cancelamento ----------------

    async def cancel_all_open_orders(
        self,
        only_pairs: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Dict[str, int]]:
        """
        Cancela todas as ordens 'open' em todas as exchanges habilitadas.

        Estratégia por exchange:
          1) Lista ordens abertas (global e/ou por pares informados) => L0
          2) Se não for dry-run:
               2a) tenta cancel_all_orders nativo (global ou por símbolos BUY/SELL mapeados)
               2b) lista de novo => L1
               2c) para qualquer remanescente, faz fallback por ID (cancel_order)
          3) Lista final => Lf
          4) cancelled = max(0, L0 - Lf)
        """
        summary: Dict[str, Dict[str, int]] = {}

        async def _list_open(ex_name: str) -> List[Dict[str, Any]]:
            # tenta global
            try:
                return await self.fetch_open_orders(ex_name, global_pair=None)
            except Exception:
                pass
            # fallback por par (se disponível)
            acc: List[Dict[str, Any]] = []
            pairs = only_pairs or []
            for gp in pairs:
                try:
                    acc.extend(await self.fetch_open_orders(ex_name, global_pair=gp))
                except Exception:
                    continue
            return acc

        async def _native_cancel(ex_name: str):
            """
            Usa cancel_all_orders quando existir.
            Se only_pairs estiver setado, tenta por símbolos BUY/SELL.

            Importante: quando mercadobitcoin + MB v4 habilitado, **não** usar CCXT aqui.
            O adapter MB v4 já lida com as rotas corretas e fallbacks (DELETE/POST cancel).
            """
            # Skip CCXT para MB quando o adapter v4 está ativo
            if ex_name.lower() == "mercadobitcoin" and self.mb_v4 and self.mb_v4.enabled:
                return

            ex = self.exchanges.get(ex_name)
            if not ex or not hasattr(ex, "cancel_all_orders"):
                return
            try:
                if not only_pairs:
                    try:
                        await ex.cancel_all_orders(None)
                    except TypeError:
                        await ex.cancel_all_orders()
                    return
                # por par -> por símbolos locais (BUY/SELL)
                tried: Set[str] = set()
                for gp in only_pairs:
                    for sym in self._both_side_symbols(ex_name, gp):
                        if not sym or sym in tried:
                            continue
                        tried.add(sym)
                        try:
                            await ex.cancel_all_orders(sym)
                            await asyncio.sleep(0.1)
                        except Exception:
                            # ignora: algumas exchanges aceitam só global
                            pass
            except Exception as e:
                log.warning(f"[{ex_name}] cancel_all_orders falhou: {e}")

        for ex_name in self.enabled_ids:
            errors = 0

            # L0
            try:
                pre_opens = await _list_open(ex_name)
            except Exception:
                pre_opens = []
            listed0 = len(pre_opens)

            if dry_run:
                summary[ex_name] = {"listed": listed0, "cancelled": 0, "errors": 0}
                continue

            # 2a) nativo
            await _native_cancel(ex_name)

            # 2b) L1
            try:
                mid_opens = await _list_open(ex_name)
            except Exception:
                mid_opens = []

            # 2c) fallback por ID (cancela o que sobrou)
            to_cancel = mid_opens
            for o in to_cancel:
                oid   = str(o.get("id"))
                # pode vir como 'symbol' ou 'instrument' (MB v4) — para outras exchanges,
                # esse valor costuma já ser o símbolo local; para MB v4, o método ignora.
                sym_l = o.get("symbol") or o.get("instrument") or ""
                side  = o.get("side") or None
                try:
                    await self.cancel_order(ex_name, oid, global_pair=sym_l, side_hint=side)
                    await asyncio.sleep(0.15)  # alivia rate-limit
                except Exception:
                    errors += 1

            # 3) Lf
            try:
                post_opens = await _list_open(ex_name)
            except Exception:
                post_opens = []
            listedf = len(post_opens)

            cancelled = max(0, listed0 - listedf)
            summary[ex_name] = {"listed": listed0, "cancelled": cancelled, "errors": errors}

        return summary

    async def _safe_load_markets(self, ex_name: str):
        ex = self.exchanges[ex_name]
        if self._markets_loaded.get(ex_name):
            return
        try:
            await ex.load_markets(reload=True)
            self._markets_loaded[ex_name] = True
        except (InvalidNonce, ExchangeError, NetworkError, RequestTimeout) as e:
            if getattr(ex, "id", "").lower() == "mexc":
                log.warning(f"[{ex_name}] load_markets falhou, tentando sync + retry: {e}")
                await self._sync_time_and_window_mexc(ex)
                try:
                    await ex.load_markets(reload=True)
                    self._markets_loaded[ex_name] = True
                    return
                except Exception as e2:
                    self._markets_loaded[ex_name] = False
                    log.warning(f"[{ex_name}] load_markets retry falhou: {e2}")
                    return
            self._markets_loaded[ex_name] = False
            log.warning(f"[{ex_name}] load_markets falhou: {e}")
        except Exception as e:
            self._markets_loaded[ex_name] = False
            log.warning(f"[{ex_name}] load_markets falhou: {e}")

    # ---------------- normalização

    def to_usdt(self, ex_name: str, symbol_local: str, price_local: float) -> float:
        quote = _quote_ccy(symbol_local)
        if quote == "BRL":
            return price_local / self.usdt_brl
        return price_local

    def from_usdt(self, ex_name: str, symbol_local: str, price_usdt: float) -> float:
        quote = _quote_ccy(symbol_local)
        if quote == "BRL":
            return price_usdt * self.usdt_brl
        return price_usdt

    # ---------------- market data (público via CCXT)

    async def get_ticker(self, ex_name: str, symbol_local: str) -> Quote:
        ex = self.exchanges[ex_name]
        deco = _get_retry_deco(self.max_retries, self.retry_backoff_ms)

        @deco
        async def _do() -> Quote:
            t = await ex.fetch_ticker(symbol_local)
            bid = _safe_float(t.get("bid"))
            ask = _safe_float(t.get("ask"))
            mid = (bid + ask) / 2 if (bid is not None and ask is not None) else None
            return Quote(bid=bid, ask=ask, mid=mid, raw_quote_ccy=_quote_ccy(symbol_local))

        return await _do()

    async def get_orderbook(self, ex_name: str, symbol_local: str, limit: int = 10) -> Dict[str, Any]:
        ex = self.exchanges[ex_name]
        deco = _get_retry_deco(self.max_retries, self.retry_backoff_ms)

        @deco
        async def _do() -> Dict[str, Any]:
            return await ex.fetch_order_book(symbol_local, limit=limit)

        return await _do()

    async def get_mid_price_usdt(self, ex_name: str, symbol_local: str) -> Optional[float]:
        q = await self.get_ticker(ex_name, symbol_local)
        if q.mid is None:
            return None
        return self.to_usdt(ex_name, symbol_local, q.mid)

    # ------------ probe com diagnóstico (público)

    async def probe_mid_usdt(self, ex_name: str, side: str, global_pair: str) -> Dict[str, Any]:
        sym = self._pick_symbol(ex_name, side, global_pair)
        try:
            mid = await self.get_mid_price_usdt(ex_name, sym)
            if mid is None:
                return {"ex": ex_name, "symbol_local": sym, "ok": False, "mid_usdt": None, "err": "no_mid", "detail": "ticker sem bid/ask (mid=None)"}
            return {"ex": ex_name, "symbol_local": sym, "ok": True, "mid_usdt": float(mid), "err": None, "detail": ""}
        except AuthenticationError as e:
            return {"ex": ex_name, "symbol_local": sym, "ok": False, "mid_usdt": None, "err": "auth", "detail": str(e)}
        except RequestTimeout as e:
            return {"ex": ex_name, "symbol_local": sym, "ok": False, "mid_usdt": None, "err": "timeout", "detail": str(e)}
        except DDoSProtection as e:
            return {"ex": ex_name, "symbol_local": sym, "ok": False, "mid_usdt": None, "err": "ddos", "detail": str(e)}
        except ExchangeNotAvailable as e:
            return {"ex": ex_name, "symbol_local": sym, "ok": False, "mid_usdt": None, "err": "not_available", "detail": str(e)}
        except NetworkError as e:
            return {"ex": ex_name, "symbol_local": sym, "ok": False, "mid_usdt": None, "err": "network", "detail": str(e)}
        except ExchangeError as e:
            return {"ex": ex_name, "symbol_local": sym, "ok": False, "mid_usdt": None, "err": "exchange", "detail": str(e)}
        except Exception as e:
            return {"ex": ex_name, "symbol_local": sym, "ok": False, "mid_usdt": None, "err": "other", "detail": str(e)}

    # ---------------- saldos (privadas → MB v4 se disponível)

    async def get_balance(self, ex_name: str) -> Dict[str, Any]:
        if ex_name.lower() == "mercadobitcoin" and self.mb_v4 and self.mb_v4.enabled:
            try:
                return await self.mb_v4.get_balances()
            except Exception as e:
                log.warning(f"[mercadobitcoin v4] get_balances falhou: {e} — fallback: {{}}")
                return {}
        # outras exchanges via CCXT
        ex = self.exchanges[ex_name]
        deco = _get_retry_deco(self.max_retries, self.retry_backoff_ms)
        @deco
        async def _do() -> Dict[str, Any]:
            return await ex.fetch_balance()
        try:
            bal = await _do()
            return bal or {}
        except Exception as e:
            log.warning(f"[{ex_name}] fetch_balance falhou: {e}")
            return {}

    async def get_free_quote_balance(self, ex_name: str, quote_ccy: str) -> float:
        bal = await self.get_balance(ex_name)
        free = 0.0
        if "free" in bal and isinstance(bal["free"], dict):
            free = float(bal["free"].get(quote_ccy, 0.0) or 0.0)
        elif isinstance(bal, dict) and quote_ccy in bal:
            free = float((bal.get(quote_ccy) or {}).get("free", 0.0) or 0.0)
        return free

    async def get_free_balance_normalized_usdt(self, ex_name: str, symbol_local_for_quote: str) -> float:
        quote = _quote_ccy(symbol_local_for_quote)
        free_quote = await self.get_free_quote_balance(ex_name, quote)
        if quote == "BRL":
            return free_quote / self.usdt_brl
        return free_quote

    # ---------------- ordens (privadas → MB v4 se disponível) - CORRIGIDO

    async def create_limit_order(
        self,
        ex_name: str,
        global_pair: str,
        side: str,
        amount: float,
        price_usdt: float,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params = params or {}
        side = side.lower()
        symbol_local = self._pick_symbol(ex_name, side, global_pair)
        price_local = self.from_usdt(ex_name, symbol_local, price_usdt)

        # CORREÇÃO: Arredondamento específico para Mercado Bitcoin
        if ex_name.lower() == "mercadobitcoin":
            price_local_antes = price_local
            price_local = round(price_local, 2)  # Step 0.01 do MB
            log.info(f"[{ex_name}] Preço convertido: {price_usdt} USDT -> {price_local_antes} BRL -> {price_local} BRL (arredondado)")

        if self.mode == "PAPER":
            return {
                "id": f"paper_{ex_name}_{global_pair}_{side}",
                "symbol": symbol_local,
                "type": "limit",
                "side": side,
                "amount": float(amount),
                "price": float(price_local),
                "status": "open",
                "info": {"paper": True},
            }

        # Mercado Bitcoin via v4 adapter CORRIGIDO
        if ex_name.lower() == "mercadobitcoin" and self.mb_v4 and self.mb_v4.enabled:
            try:
                resp = await self.mb_v4.create_limit_order(symbol_local, side, float(amount), float(price_local))
                return {
                    "id": resp.id,
                    "symbol": resp.symbol or symbol_local,
                    "type": "limit",
                    "side": side,
                    "amount": float(resp.amount or amount),
                    "price": float(resp.price or price_local),
                    "status": resp.status,
                    "info": {"mb_v4": True},
                }
            except Exception as e:
                log.error(f"[MB v4] create_limit_order falhou: {e}")
                # Fallback para CCXT se disponível
                if ex_name in self.exchanges:
                    log.info(f"[MB v4] usando fallback CCXT para {symbol_local}")
                    ex = self.exchanges[ex_name]
                    return await ex.create_order(symbol_local, "limit", side, amount, price_local, params)
                raise

        # Outras via CCXT
        ex = self.exchanges[ex_name]
        deco = _get_retry_deco(self.max_retries, self.retry_backoff_ms)
        @deco
        async def _do() -> Dict[str, Any]:
            return await ex.create_order(symbol_local, "limit", side, amount, price_local, params)
        return await _do()

    async def cancel_order(
        self,
        ex_name: str,
        order_id: str,
        global_pair: str,
        side_hint: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        params = params or {}
        symbol_local = self._pick_symbol(ex_name, (side_hint or "BUY"), global_pair)

        if self.mode == "PAPER":
            return {"id": order_id, "status": "canceled", "info": {"paper": True}}

        # Mercado Bitcoin via v4 adapter CORRIGIDO
        if ex_name.lower() == "mercadobitcoin" and self.mb_v4 and self.mb_v4.enabled:
            try:
                return await self.mb_v4.cancel_order(order_id, symbol_local)
            except Exception as e:
                log.error(f"[MB v4] cancel_order falhou: {e}")
                # Fallback para CCXT se disponível
                if ex_name in self.exchanges:
                    log.info(f"[MB v4] usando fallback CCXT para cancelar {order_id}")
                    ex = self.exchanges[ex_name]
                    try:
                        return await ex.cancel_order(order_id, symbol_local, params)
                    except Exception:
                        return await ex.cancel_order(order_id, None, params)
                raise

        # Outras via CCXT
        ex = self.exchanges[ex_name]
        deco = _get_retry_deco(self.max_retries, self.retry_backoff_ms)
        @deco
        async def _do():
            try:
                return await ex.cancel_order(order_id, symbol_local, params)
            except Exception:
                # algumas exchanges aceitam None para symbol
                return await ex.cancel_order(order_id, None, params)
        return await _do()

    async def fetch_open_orders(
        self,
        ex_name: str,
        global_pair: Optional[str] = None,
        side_hint: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        params = params or {}
        if self.mode == "PAPER":
            return []

        # Mercado Bitcoin via v4 adapter CORRIGIDO
        if ex_name.lower() == "mercadobitcoin" and self.mb_v4 and self.mb_v4.enabled:
            sym_local = self._pick_symbol(ex_name, (side_hint or "BUY"), global_pair) if global_pair else None
            try:
                raw = await self.mb_v4.fetch_open_orders(sym_local)
                out: List[Dict[str, Any]] = []
                for o in (raw or []):
                    # Normaliza resposta MB v4 para formato CCXT
                    oid = str(o.get("id") or o.get("orderId") or "")
                    side = (o.get("side") or "").lower()
                    symbol = str(o.get("instrument") or o.get("symbol") or sym_local or "")
                    
                    # Converte preço e quantidade
                    try:
                        price = float(o.get("limitPrice") or o.get("price") or 0.0)
                    except (TypeError, ValueError):
                        price = 0.0
                        
                    try:
                        amount = float(o.get("qty") or o.get("quantity") or 0.0)
                    except (TypeError, ValueError):
                        amount = 0.0

                    status = str(o.get("status") or "open").lower()
                    
                    out.append({
                        "id": oid,
                        "symbol": symbol,
                        "type": "limit",
                        "side": side,
                        "price": price,
                        "amount": amount,
                        "status": status,
                        "info": {"mb_v4": True, "raw": o},
                    })
                return out
            except Exception as e:
                log.error(f"[MB v4] fetch_open_orders falhou: {e}")
                # Fallback para CCXT
                if ex_name in self.exchanges:
                    return await self._fetch_open_orders_ccxt(ex_name, global_pair, side_hint, params)
                return []

        # Outras via CCXT
        return await self._fetch_open_orders_ccxt(ex_name, global_pair, side_hint, params)

    async def _fetch_open_orders_ccxt(
        self,
        ex_name: str,
        global_pair: Optional[str] = None,
        side_hint: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Helper para fetch_open_orders via CCXT"""
        ex = self.exchanges[ex_name]
        symbol_local = None
        if global_pair:
            symbol_local = self._pick_symbol(ex_name, (side_hint or "BUY"), global_pair)
        deco = _get_retry_deco(self.max_retries, self.retry_backoff_ms)
        @deco
        async def _do():
            return await ex.fetch_open_orders(symbol_local, params=params)
        return await _do()

    async def fetch_order(
        self,
        ex_name: str,
        order_id: str,
        global_pair: str,
        side_hint: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Busca ordem específica - NOVO método para MB v4"""
        params = params or {}
        symbol_local = self._pick_symbol(ex_name, (side_hint or "BUY"), global_pair)

        if self.mode == "PAPER":
            return {"id": order_id, "status": "open", "info": {"paper": True}}

        # Mercado Bitcoin via v4 adapter
        if ex_name.lower() == "mercadobitcoin" and self.mb_v4 and self.mb_v4.enabled:
            try:
                return await self.mb_v4.fetch_order(order_id, symbol_local)
            except Exception as e:
                log.error(f"[MB v4] fetch_order falhou: {e}")
                # Fallback para CCXT
                if ex_name in self.exchanges:
                    ex = self.exchanges[ex_name]
                    return await ex.fetch_order(order_id, symbol_local, params)
                raise

        # Outras via CCXT
        ex = self.exchanges[ex_name]
        deco = _get_retry_deco(self.max_retries, self.retry_backoff_ms)
        @deco
        async def _do():
            return await ex.fetch_order(order_id, symbol_local, params)
        return await _do()

    # ---------------- atalhos públicos

    def resolve_symbol_local(self, ex_name: str, side: str, global_pair: str) -> str:
        return self._pick_symbol(ex_name, side, global_pair)

    async def get_quote_usdt(self, ex_name: str, side: str, global_pair: str) -> Quote:
        symbol_local = self._pick_symbol(ex_name, side, global_pair)
        return await self.get_ticker(ex_name, symbol_local)

    async def get_best_bid_ask_usdt(self, ex_name: str, side: str, global_pair: str) -> Tuple[Optional[float], Optional[float]]:
        symbol_local = self._pick_symbol(ex_name, side, global_pair)
        q = await self.get_ticker(ex_name, symbol_local)
        bid_u = self.to_usdt(ex_name, symbol_local, q.bid) if q.bid is not None else None
        ask_u = self.to_usdt(ex_name, symbol_local, q.ask) if q.ask is not None else None
        return bid_u, ask_u

    async def get_mid_usdt(self, ex_name: str, side: str, global_pair: str) -> Optional[float]:
        symbol_local = self._pick_symbol(ex_name, side, global_pair)
        return await self.get_mid_price_usdt(ex_name, symbol_local)
