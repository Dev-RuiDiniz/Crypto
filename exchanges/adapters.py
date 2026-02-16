# exchanges/adapters.py
# -------------------------------------------------------------------
# 1) Adapters: utilidades de step/precision/mínimos com overrides via config
# 2) MBV4Adapter: integração PRIVADA da API v4 do Mercado Bitcoin (Bearer)
#    - Seguindo documentação oficial: /accounts/{accountId}/{symbol}/orders
#    - Símbolos no formato BASE-QUOTE (ex: SOL-BRL)
#    - Obrigatório accountId obtido via /accounts
#    - CORREÇÃO: Arredondamento de preço para step 0.01 do MB
# -------------------------------------------------------------------

from __future__ import annotations

import math
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

import configparser

try:
    import aiohttp
except Exception:
    aiohttp = None

try:
    from utils.logger import get_logger
except Exception:
    import logging
    def get_logger(name: str): return logging.getLogger(name)

log = get_logger("adapters")

# =================================================
# Helpers comuns
# =================================================

def floor_step(value: float, step: float) -> float:
    try:
        step = float(step)
        if step <= 0:
            return float(value)
        return float(math.floor(float(value) / step) * step)
    except Exception:
        return float(value)

def round_step(value: float, step: float) -> float:
    return floor_step(value, step)

def ceil_step(value: float, step: float) -> float:
    try:
        step = float(step)
        if step <= 0:
            return float(value)
        return float(math.ceil(float(value) / step) * step)
    except Exception:
        return float(value)

def _quote_ccy(symbol: str) -> str:
    if not symbol:
        return ""
    return symbol.split("/")[1].strip().upper() if "/" in symbol else symbol.upper()

def _base_ccy(symbol: str) -> str:
    if not symbol:
        return ""
    return symbol.split("/")[0].strip().upper() if "/" in symbol else symbol.upper()

def _to_step_from_precision(precision: Optional[int]) -> float:
    try:
        if precision is None:
            return 0.0
        p = int(precision)
        if p <= 0:
            return 0.0
        return 10.0 ** (-p)
    except Exception:
        return 0.0

# =================================================
# 1) Adapters (steps/mínimos/overrides) - CORRIGIDO
# =================================================

class Adapters:
    def __init__(self, cfg: configparser.ConfigParser, ex_hub):
        self.cfg = cfg
        self.ex_hub = ex_hub
        if self.cfg.has_section("ADAPTERS_OVERRIDES"):
            items = self.cfg.items("ADAPTERS_OVERRIDES")
            self._ovr: Dict[str, str] = {k.lower(): v for k, v in items}
        else:
            self._ovr = {}

    def _get_market(self, ex_name: str, symbol_local: str) -> Dict[str, Any]:
        try:
            ex = self.ex_hub.exchanges.get(ex_name)
            if not ex:
                return {}
            mkts = getattr(ex, "markets", None)
            if isinstance(mkts, dict) and symbol_local in mkts:
                return mkts[symbol_local] or {}
            if hasattr(ex, "market"):
                return ex.market(symbol_local) or {}
        except Exception:
            pass
        return {}

    def _ov_key(self, ex_name: str, symbol_local: str, field: str) -> str:
        return f"{ex_name}.{symbol_local}.{field}".lower()

    def _get_override_float(self, ex_name: str, symbol_local: str, field: str) -> Optional[float]:
        k = self._ov_key(ex_name, symbol_local, field)
        if k in self._ovr:
            try:
                raw = str(self._ovr[k]).split(";")[0].strip()
                return float(raw)
            except Exception:
                return None
        return None

    def get_price_step(self, ex_name: str, symbol_local: str) -> float:
        # CORREÇÃO: Override específico para Mercado Bitcoin com pares BRL
        if ex_name.lower() == "mercadobitcoin" and "BRL" in symbol_local.upper():
            return 0.01  # Step mínimo do MB para pares BRL
        
        ov = self._get_override_float(ex_name, symbol_local, "price_step")
        if ov is not None and ov > 0:
            return float(ov)
        
        m = self._get_market(ex_name, symbol_local)
        try:
            prec = (m.get("precision") or {}).get("price", None)
        except Exception:
            prec = None
        step = _to_step_from_precision(prec)
        if step <= 0:
            try:
                st = (m.get("limits") or {}).get("price") or {}
                if "step" in st and st["step"] is not None:
                    step = float(st["step"])
            except Exception:
                pass
        if step <= 0:
            try:
                st = (m.get("limits") or {}).get("price") or {}
                mn = st.get("min", None)
                if mn is not None and float(mn) > 0:
                    step = float(mn)
            except Exception:
                pass
        return float(step) if step and step > 0 else 0.0

    def get_amount_step(self, ex_name: str, symbol_local: str) -> float:
        ov = self._get_override_float(ex_name, symbol_local, "amount_step")
        if ov is not None and ov > 0:
            return float(ov)
        m = self._get_market(ex_name, symbol_local)
        try:
            prec = (m.get("precision") or {}).get("amount", None)
        except Exception:
            prec = None
        step = _to_step_from_precision(prec)
        if step <= 0:
            try:
                st = (m.get("limits") or {}).get("amount") or {}
                if "step" in st and st["step"] is not None:
                    step = float(st["step"])
            except Exception:
                pass
        if step <= 0:
            try:
                st = (m.get("limits") or {}).get("amount") or {}
                mn = st.get("min", None)
                if mn is not None and float(mn) > 0:
                    step = float(mn)
            except Exception:
                pass
        return float(step) if step and step > 0 else 0.0

    def get_min_qty(self, ex_name: str, symbol_local: str) -> float:
        ov = self._get_override_float(ex_name, symbol_local, "min_qty")
        if ov is not None and ov >= 0:
            return float(ov)
        m = self._get_market(ex_name, symbol_local)
        try:
            mn = (m.get("limits") or {}).get("amount") or {}
            val = mn.get("min", None)
            return float(val) if val is not None else 0.0
        except Exception:
            return 0.0

    def get_min_notional_usdt(self, ex_name: str, symbol_local: str) -> float:
        ov = self._get_override_float(ex_name, symbol_local, "min_notional")
        if ov is not None and ov >= 0:
            return float(ov)
        m = self._get_market(ex_name, symbol_local)
        try:
            cost = (m.get("limits") or {}).get("cost") or {}
            min_cost = cost.get("min", None)
            if min_cost is None:
                return 0.0
            quote = _quote_ccy(symbol_local)
            if quote == "USDT":
                return float(min_cost)
            elif quote == "BRL":
                return float(min_cost) / float(self.ex_hub.usdt_brl)
            else:
                return 0.0
        except Exception:
            return 0.0

    def quantize_price(self, ex_name: str, symbol_local: str, price_local: float) -> float:
        step = self.get_price_step(ex_name, symbol_local)
        if step and step > 0:
            return floor_step(price_local, step)
        m = self._get_market(ex_name, symbol_local)
        try:
            p = (m.get("precision") or {}).get("price", None)
            return float(round(float(price_local), int(p))) if p is not None else float(price_local)
        except Exception:
            return float(price_local)

    def quantize_amount(self, ex_name: str, symbol_local: str, amount: float) -> float:
        step = self.get_amount_step(ex_name, symbol_local)
        if step and step > 0:
            return floor_step(amount, step)
        m = self._get_market(ex_name, symbol_local)
        try:
            p = (m.get("precision") or {}).get("amount", None)
            return float(round(float(amount), int(p))) if p is not None else float(amount)
        except Exception:
            return float(amount)

    def round_price(self, ex_name: str, symbol_local: str, price_local: float) -> float:
        return self.quantize_price(ex_name, symbol_local, price_local)

    def round_amount(self, ex_name: str, symbol_local: str, amount: float) -> float:
        return self.quantize_amount(ex_name, symbol_local, amount)

    def ensure_min_requirements(
        self,
        ex_name: str,
        symbol_local: str,
        amount: float,
        price_usdt: float,
        router_min_notional_usdt: float = 0.0,
    ) -> Tuple[bool, float, str]:
        try:
            amount = float(amount)
            price_usdt = float(price_usdt)
            if amount <= 0 or price_usdt <= 0:
                return (False, float(amount), "zero")

            min_qty = float(self.get_min_qty(ex_name, symbol_local) or 0.0)
            min_notional_ex = float(self.get_min_notional_usdt(ex_name, symbol_local) or 0.0)
            min_notional = max(float(min_notional_ex), float(router_min_notional_usdt or 0.0))

            amount_q = max(amount, min_qty)

            notional_usdt = price_usdt * amount_q
            if min_notional > 0 and notional_usdt < min_notional:
                amount_q = min_notional / price_usdt

            step = self.get_amount_step(ex_name, symbol_local)
            if step and step > 0:
                amount_q = floor_step(amount_q, step)
                if amount_q < min_qty:
                    amount_q = ceil_step(min_qty, step)
                if (price_usdt * amount_q) < min_notional:
                    amount_q = ceil_step(min_notional / price_usdt, step)
            else:
                amount_q = max(amount_q, min_qty)

            notional_usdt = price_usdt * amount_q
            if min_qty > 0 and amount_q < min_qty:
                return (False, amount_q, f"amount<{min_qty}")
            if min_notional > 0 and notional_usdt < min_notional:
                return (False, amount_q, f"notional<{min_notional}")
            return (True, amount_q, "")
        except Exception as e:
            return (False, float(amount), f"exception:{e}")

    def enforce_minima(self, ex_name: str, symbol_local: str, amount: float, price_usdt: float, router_min_notional_usdt: float = 0.0):
        return self.ensure_min_requirements(ex_name, symbol_local, amount, price_usdt, router_min_notional_usdt)

    def ensure_minima(self, ex_name: str, symbol_local: str, amount: float, price_usdt: float, router_min_notional_usdt: float = 0.0):
        return self.ensure_min_requirements(ex_name, symbol_local, amount, price_usdt, router_min_notional_usdt)

# =================================================
# 2) Mercado Bitcoin v4 – Adapter (privado) CORRIGIDO
# =================================================

@dataclass
class MBV4OrderResp:
    id: str
    status: str
    price: Optional[float]
    amount: Optional[float]
    side: Optional[str]
    symbol: Optional[str]

class MBV4Adapter:
    """
    Adapter corrigido seguindo documentação oficial:
    - Endpoint: /accounts/{accountId}/{symbol}/orders
    - Símbolos: BASE-QUOTE (ex: SOL-BRL)
    - Obrigatório: accountId obtido via /accounts
    - CORREÇÃO: Arredondamento de preço para step 0.01 do MB
    """

    def __init__(self, cfg: configparser.ConfigParser, section: str = "EXCHANGES.mercadobitcoin"):
        self.cfg = cfg
        self.section = section
        self.enabled = self.cfg.getboolean(self.section, "ENABLED", fallback=False)
        self.base_url = "https://api.mercadobitcoin.net/api/v4"
        self.login_user = self.cfg.get(self.section, "MBV4_LOGIN", fallback="").strip()
        self.login_pass = self.cfg.get(self.section, "MBV4_PASSWORD", fallback="").strip()
        self.token = self.cfg.get(self.section, "MBV4_BEARER_TOKEN", fallback="").strip()
        self.token_exp: Optional[int] = None
        self.timeout = int(self.cfg.get("GLOBAL", "HTTP_TIMEOUT_SEC", fallback="15"))
        self._session: Optional["aiohttp.ClientSession"] = None

        # Cache de conta
        self._cached_account_id: Optional[str] = None
        self._cached_account_id_ts: float = 0.0
        self._account_ttl_sec: float = 3600.0  # 1 hora

        if self.enabled and aiohttp is None:
            raise RuntimeError("Dependência ausente: 'aiohttp'. Instale com: pip install aiohttp")

        if self.enabled and not (self.token or (self.login_user and self.login_pass)):
            log.warning("[mercadobitcoin v4] ENABLED=true, mas sem token e sem MBV4_LOGIN/MBV4_PASSWORD — privadas desabilitadas no MB.")

    async def _ensure_session(self):
        if self._session and not self._session.closed:
            return
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    @staticmethod
    def to_v4_symbol(symbol_local: str) -> str:
        """Converte SOL/BRL para SOL-BRL conforme documentação"""
        return symbol_local.replace("/", "-").upper()

    async def _authorize(self) -> None:
        if not (self.login_user and self.login_pass):
            raise RuntimeError("[MB v4] Credenciais ausentes para /authorize (MBV4_LOGIN/MBV4_PASSWORD).")
        await self._ensure_session()
        url = f"{self.base_url}/authorize"
        body = {"login": self.login_user, "password": self.login_pass}
        async with self._session.post(url, headers={"Content-Type": "application/json", "Accept": "application/json"}, data=json.dumps(body)) as resp:
            txt_ct = resp.headers.get("Content-Type", "")
            try:
                data = await resp.json() if "application/json" in txt_ct else json.loads(await resp.text())
            except Exception:
                data = {"raw": await resp.text()}
            if resp.status != 200 or "access_token" not in data:
                raise RuntimeError(f"[MB v4] authorize falhou: HTTP {resp.status} - {data}")
            self.token = str(data.get("access_token") or "").strip()
            self.token_exp = None
            if isinstance(data.get("expiration"), (int, float)):
                self.token_exp = int(data["expiration"])
            else:
                try:
                    import base64
                    parts = self.token.split(".")
                    if len(parts) >= 2:
                        pad = "=="[(len(parts[1]) % 4):]
                        payload = json.loads(base64.urlsafe_b64decode(parts[1] + pad).decode("utf-8"))
                        if isinstance(payload.get("exp"), (int, float)):
                            self.token_exp = int(payload["exp"])
                except Exception:
                    pass
            if self.token_exp is not None:
                self.token_exp = max(0, self.token_exp - 30)
            log.info("[mercadobitcoin v4] token obtido via /authorize.")

    def _auth_headers(self) -> Dict[str, str]:
        base = {"Content-Type": "application/json", "Accept": "application/json"}
        if not self.token:
            return base
        return {"Authorization": f"Bearer {self.token}", **base}

    async def _ensure_token(self):
        if not self.enabled:
            raise RuntimeError("[MB v4] adapter desabilitado (ENABLED=false).")
        now = int(time.time())
        if self.token:
            if self.token_exp is None or self.token_exp > now:
                return
        if self.login_user and self.login_pass:
            await self._authorize()
            return
        raise RuntimeError("[MB v4] MBV4_BEARER_TOKEN não configurado e sem MBV4_LOGIN/MBV4_PASSWORD.")

    async def _req(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        private: bool = True,
    ) -> Tuple[int, Any]:
        await self._ensure_session()
        if private:
            await self._ensure_token()
        url = f"{self.base_url}{path}"
        headers = self._auth_headers()
        params = {k: v for k, v in (params or {}).items() if v is not None}
        data = json.dumps(body) if body is not None else None
        async with self._session.request(method.upper(), url, headers=headers, params=params, data=data) as resp:
            ct = resp.headers.get("Content-Type", "")
            try:
                payload = await resp.json() if "application/json" in ct else await resp.text()
            except Exception:
                payload = await resp.text()
            if resp.status in (401, 403) and self.login_user and self.login_pass and private:
                log.warning("[mercadobitcoin v4] token possivelmente expirado — tentando renovar via /authorize.")
                try:
                    await self._authorize()
                    async with self._session.request(method.upper(), url, headers=self._auth_headers(), params=params, data=data) as resp2:
                        ct2 = resp2.headers.get("Content-Type", "")
                        try:
                            payload2 = await resp2.json() if "application/json" in ct2 else await resp2.text()
                        except Exception:
                            payload2 = await resp2.text()
                        return resp2.status, payload2
                except Exception:
                    return resp.status, payload
            return resp.status, payload

    async def _get_default_account_id(self) -> str:
        """Obtém accountId conforme documentação - List Accounts"""
        now = time.time()
        if self._cached_account_id and (now - self._cached_account_id_ts) < self._account_ttl_sec:
            return self._cached_account_id

        code, data = await self._req("GET", "/accounts")
        if code != 200:
            raise RuntimeError(f"[MB v4] listar contas falhou: HTTP {code} - {data}")
        
        # Normaliza resposta
        accounts = []
        if isinstance(data, dict) and isinstance(data.get("accounts"), list):
            accounts = data["accounts"]
        elif isinstance(data, list):
            accounts = data
        else:
            raise RuntimeError(f"[MB v4] formato inesperado em /accounts: {data}")

        if not accounts:
            raise RuntimeError("[MB v4] nenhuma conta retornada em /accounts")

        # Pega a primeira conta (geralmente é a principal)
        account = accounts[0]
        account_id = str(account.get("id") or account.get("accountId") or "")
        if not account_id:
            raise RuntimeError(f"[MB v4] não encontrou 'id' em {account}")

        self._cached_account_id = account_id
        self._cached_account_id_ts = now
        log.info(f"[mercadobitcoin v4] accountId obtido: {account_id}")
        return account_id

    async def get_balances(self) -> Dict[str, Any]:
        """Obtém saldos conforme documentação"""
        account_id = await self._get_default_account_id()
        code, data = await self._req("GET", f"/accounts/{account_id}/balances")
        if code == 200 and isinstance(data, (dict, list)):
            return self._normalize_balances(data)
        raise RuntimeError(f"[MB v4] Falha ao obter saldos: {(code, data)}")

    def _normalize_balances(self, raw: Any) -> Dict[str, Any]:
        """Normaliza resposta de saldos para formato padrão"""
        arr = []
        if isinstance(raw, dict):
            if isinstance(raw.get("balances"), list):
                arr = raw["balances"]
            elif isinstance(raw.get("data"), list):
                arr = raw["data"]
            elif isinstance(raw.get("data"), dict) and isinstance(raw["data"].get("items"), list):
                arr = raw["data"]["items"]
        elif isinstance(raw, list):
            arr = raw

        free: Dict[str, float] = {}
        used: Dict[str, float] = {}
        for it in arr:
            asset = str(it.get("asset") or it.get("currency") or it.get("symbol") or "").upper()
            if not asset:
                continue
            avail = float(it.get("available") or it.get("free") or it.get("balance") or 0.0)
            locked = float(it.get("locked") or it.get("inOrder") or it.get("reserved") or 0.0)
            free[asset] = free.get(asset, 0.0) + avail
            used[asset] = used.get(asset, 0.0) + locked
        return {"free": free, "used": used}

    # -------- ORDENS (CORRIGIDO) --------

    def _normalize_order_response(self, data: Dict[str, Any]) -> MBV4OrderResp:
        """Normaliza resposta de ordem para formato padrão"""
        oid = str(data.get("id") or data.get("orderId") or "")
        status = str(data.get("status") or "open")
        side = str(data.get("side") or "").lower()
        symbol = str(data.get("instrument") or data.get("symbol") or "")
        
        # Converte preços e quantidades
        try:
            price = float(data.get("limitPrice") or data.get("price") or 0.0)
        except (TypeError, ValueError):
            price = 0.0
            
        try:
            amount = float(data.get("qty") or data.get("quantity") or 0.0)
        except (TypeError, ValueError):
            amount = 0.0

        return MBV4OrderResp(
            id=oid, 
            status=status, 
            price=price, 
            amount=amount, 
            side=side, 
            symbol=symbol
        )

    async def create_limit_order(self, symbol_local: str, side: str, amount: float, price_local: float) -> MBV4OrderResp:
        """
        Cria ordem limitada conforme documentação:
        POST /accounts/{accountId}/{symbol}/orders
        CORREÇÃO: Arredonda preço para 2 casas decimais (step 0.01 do MB)
        """
        account_id = await self._get_default_account_id()
        v4_symbol = self.to_v4_symbol(symbol_local)
        
        # CORREÇÃO CRÍTICA: Arredonda o preço para 2 casas decimais (step 0.01 do MB)
        price_rounded = round(float(price_local), 2)
        log.info(f"[MB v4] Preço arredondado: {price_local} -> {price_rounded} (symbol: {v4_symbol})")
        
        # Payload conforme documentação oficial
        payload = {
            "qty": str(amount),
            "side": side.lower(),
            "type": "limit",
            "limitPrice": float(price_rounded)  # Usa preço arredondado
        }

        endpoint = f"/accounts/{account_id}/{v4_symbol}/orders"
        code, data = await self._req("POST", endpoint, body=payload)
        
        if code in (200, 201) and isinstance(data, dict):
            # Documentação retorna { "orderId": "..." }
            if "orderId" in data:
                # Cria resposta normalizada
                order_data = {
                    "id": data["orderId"],
                    "status": "created",
                    "side": side.lower(),
                    "instrument": v4_symbol,
                    "limitPrice": price_rounded,  # Usa preço arredondado
                    "qty": amount
                }
                return self._normalize_order_response(order_data)
        
        raise RuntimeError(f"[MB v4] create_order falhou: HTTP {code} - {data}")

    async def cancel_order(self, order_id: str, symbol_local: str) -> Dict[str, Any]:
        """
        Cancela ordem conforme documentação:
        DELETE /accounts/{accountId}/{symbol}/orders/{orderId}
        """
        account_id = await self._get_default_account_id()
        v4_symbol = self.to_v4_symbol(symbol_local)
        
        endpoint = f"/accounts/{account_id}/{v4_symbol}/orders/{order_id}"
        code, data = await self._req("DELETE", endpoint)
        
        if code in (200, 202, 204):
            return data if isinstance(data, dict) else {"status": "cancelled"}
            
        raise RuntimeError(f"[MB v4] cancel_order falhou: HTTP {code} - {data}")

    async def fetch_order(self, order_id: str, symbol_local: str) -> Dict[str, Any]:
        """
        Busca ordem específica conforme documentação:
        GET /accounts/{accountId}/{symbol}/orders/{orderId}
        """
        account_id = await self._get_default_account_id()
        v4_symbol = self.to_v4_symbol(symbol_local)
        
        endpoint = f"/accounts/{account_id}/{v4_symbol}/orders/{order_id}"
        code, data = await self._req("GET", endpoint)
        
        if code == 200 and isinstance(data, dict):
            return data
            
        raise RuntimeError(f"[MB v4] fetch_order falhou: HTTP {code} - {data}")

    async def fetch_open_orders(self, symbol_local: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Lista ordens abertas conforme documentação:
        GET /accounts/{accountId}/{symbol}/orders?status=working
        OU
        GET /accounts/{accountId}/orders?status=working (para todos os símbolos)
        """
        account_id = await self._get_default_account_id()
        
        params = {"status": "working"}  # working = ordens abertas conforme doc
        
        if symbol_local:
            v4_symbol = self.to_v4_symbol(symbol_local)
            endpoint = f"/accounts/{account_id}/{v4_symbol}/orders"
        else:
            endpoint = f"/accounts/{account_id}/orders"

        code, data = await self._req("GET", endpoint, params=params)
        
        if code == 200:
            return self._extract_orders_list(data)
        return []

    def _extract_orders_list(self, data: Any) -> List[Dict[str, Any]]:
        """Extrai lista de ordens da resposta"""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if isinstance(data.get("items"), list):
                return data["items"]
            if isinstance(data.get("content"), list):
                return data["content"]
            if isinstance(data.get("data"), list):
                return data["data"]
        return []