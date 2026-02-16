# MB.py
# ---------------------------------------------------------------------
# Coletor/Diagnóstico Mercado Bitcoin v4 (privado) com auto-discovery.
#
# - Lê credenciais de [EXCHANGES.mercadobitcoin] em config.txt (mesma pasta).
# - Se MBV4_BASE ausente, tenta bases conhecidas até uma responder.
# - Usa BEARER se presente; caso contrário, faz POST /authorize (login/senha).
# - Descobre automaticamente a rota de ORDERS testando variações conhecidas.
# - Faz dumps de payloads (accounts, balances, open_orders) em ./mb_dumps/
#
# Uso:  python MB.py
# (argumentos opcionais: --ini caminho\do\arquivo.ini)
# ---------------------------------------------------------------------

from __future__ import annotations
import os
import sys
import json
import time
import argparse
import datetime as dt
import configparser
from typing import Dict, Any, Optional, Tuple, List

# -------- HTTP backend (requests se disponível; senão urllib) ----------
_USE_REQUESTS = False
try:
    import requests  # type: ignore
    _USE_REQUESTS = True
except Exception:
    import urllib.request
    import urllib.parse
    import ssl


def _http_request(method: str, url: str, *, headers: Dict[str, str] | None = None,
                  params: Dict[str, Any] | None = None, json_body: Dict[str, Any] | None = None,
                  timeout: int = 15) -> Tuple[int, Any, Dict[str, str]]:
    """Retorna (status, payload, response_headers). Usa requests se disponível; senão urllib."""
    headers = headers or {}
    params = params or {}
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers = {**headers, "Content-Type": "application/json"}

    if _USE_REQUESTS:
        try:
            resp = requests.request(method.upper(), url, headers=headers, params=params, data=data, timeout=timeout)
            payload: Any
            try:
                payload = resp.json()
            except Exception:
                payload = resp.text
            return resp.status_code, payload, dict(resp.headers or {})
        except Exception as e:
            return 0, {"error": f"requests_exc:{e}"}, {}
    else:
        try:
            # montar URL com params
            if params:
                q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
                url = f"{url}?{q}"
            req = urllib.request.Request(url=url, data=data, headers=headers, method=method.upper())
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:  # type: ignore
                raw = resp.read()
                text = raw.decode("utf-8", errors="ignore")
                payload: Any
                try:
                    payload = json.loads(text)
                except Exception:
                    payload = text
                return getattr(resp, "status", 200), payload, dict(resp.headers.items())
        except urllib.error.HTTPError as he:  # type: ignore
            try:
                text = he.read().decode("utf-8", errors="ignore")
                payload = json.loads(text)
            except Exception:
                payload = {"raw": text}
            return he.code, payload, dict(getattr(he, "headers", {}) or {})
        except Exception as e:
            return 0, {"error": f"urllib_exc:{e}"}, {}


# ---------------------------- Utilidades --------------------------------
def _now_ts() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _pretty(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)


def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def _save_dump(prefix: str, data: Any):
    _ensure_dir("./mb_dumps")
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    fn = os.path.join("./mb_dumps", f"{prefix}_{ts}.json")
    with open(fn, "w", encoding="utf-8") as f:
        f.write(_pretty(data))
    print(f"[{_now_ts()}] dump salvo: {fn}")


def _parse_extra_headers(raw: str | None, account_id: str | None) -> Dict[str, str]:
    """Formata 'Chave: Valor;Outra: X'. Substitui {accountId} se presente."""
    if not raw:
        return {}
    out: Dict[str, str] = {}
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    for p in parts:
        if ":" in p:
            k, v = p.split(":", 1)
            v = v.strip()
            if "{accountId}" in v and account_id:
                v = v.replace("{accountId}", account_id)
            out[k.strip()] = v
    return out


# -------------------------- Cliente MB v4 --------------------------------
class MBV4Client:
    BASE_CANDIDATES = [
        "https://api.mercadobitcoin.net/api/v4",
        "https://mercadobitcoin.net/api/v4",
        "https://api.mercadobitcoin.com.br/api/v4",
        "https://apiv4.mercadobitcoin.net/api/v4",
    ]

    ORDERS_BASES = [
        "/accounts/{accountId}/orders",
        "/accounts/{accountId}/spot/orders",
        "/spot/orders",
        "/trading/spot/orders",
        "/trading/orders",
        "/orders",
    ]

    def __init__(self, ini: str):
        self.ini_path = ini
        self.cfg = configparser.ConfigParser()
        self.cfg.read(self.ini_path, encoding="utf-8")

        sec = "EXCHANGES.mercadobitcoin"
        self.enabled = self.cfg.getboolean(sec, "ENABLED", fallback=True)
        self.base = self.cfg.get(sec, "MBV4_BASE", fallback="").strip()
        self.login = self.cfg.get(sec, "MBV4_LOGIN", fallback="").strip()
        self.password = self.cfg.get(sec, "MBV4_PASSWORD", fallback="").strip()
        self.bearer = self.cfg.get(sec, "MBV4_BEARER_TOKEN", fallback="").strip()
        self.extra_headers_raw = self.cfg.get(sec, "MBV4_EXTRA_HEADERS", fallback="").strip()
        self.timeout = int(self.cfg.get("GLOBAL", "HTTP_TIMEOUT_SEC", fallback="15"))

        self.token: str = self.bearer
        self.account_id: Optional[str] = None
        self.orders_base_chosen: Optional[str] = None

    # ---------- Discovery da BASE ----------
    def discover_base(self) -> str:
        if self.base:
            print(f"[{_now_ts()}] usando MBV4_BASE do INI: {self.base}")
            return self.base

        print(f"[{_now_ts()}] MBV4_BASE não informado — iniciando auto-discovery...")
        for cand in self.BASE_CANDIDATES:
            # critério: se eu consigo /authorize (com login/senha) OU /accounts (com bearer)
            ok = False
            if self.login and self.password:
                code, payload, _ = _http_request(
                    "POST", f"{cand}/authorize",
                    json_body={"login": self.login, "password": self.password},
                    timeout=self.timeout
                )
                ok = (code == 200 and isinstance(payload, dict) and "access_token" in payload)
            elif self.bearer:
                code, _, _ = _http_request("GET", f"{cand}/accounts",
                                           headers={"Authorization": f"Bearer {self.bearer}"},
                                           timeout=self.timeout)
                ok = (code == 200)

            print(f"[{_now_ts()}]  • testando base {cand} -> {'OK' if ok else 'falhou'}")
            if ok:
                self.base = cand
                print(f"[{_now_ts()}] base descoberta: {self.base}")
                return self.base

        raise RuntimeError("Falha no auto-discovery do MBV4_BASE — nenhuma base respondeu como esperado.")

    # ---------- Auth ----------
    def ensure_token(self):
        if self.token:
            # já temos um bearer no INI; usamos direto
            print(f"[{_now_ts()}] bearer do INI detectado (usando como está).")
            return

        if not (self.login and self.password):
            raise RuntimeError("Sem BEARER e sem MBV4_LOGIN/MBV4_PASSWORD no config.txt.")

        code, payload, _ = _http_request(
            "POST", f"{self.base}/authorize",
            json_body={"login": self.login, "password": self.password},
            timeout=self.timeout
        )
        if code != 200 or not isinstance(payload, dict) or "access_token" not in payload:
            raise RuntimeError(f"/authorize falhou: HTTP {code} - {payload}")
        self.token = str(payload.get("access_token") or "").strip()
        print(f"[{_now_ts()}] token obtido via /authorize.")

    def _headers(self, *, add_account: bool = False) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        # aplica extras (com substituição de {accountId} quando already known)
        extras = _parse_extra_headers(self.extra_headers_raw, self.account_id if add_account else None)
        return {**h, **extras}

    # ---------- Conta ----------
    def fetch_accounts(self) -> Any:
        code, payload, _ = _http_request("GET", f"{self.base}/accounts", headers=self._headers(), timeout=self.timeout)
        if code != 200:
            raise RuntimeError(f"/accounts falhou: HTTP {code} - {payload}")
        # Extrai accountId “default”
        accounts_list: List[Dict[str, Any]] = []
        if isinstance(payload, dict) and isinstance(payload.get("accounts"), list):
            accounts_list = payload["accounts"]
        elif isinstance(payload, list):
            accounts_list = payload
        if not accounts_list:
            raise RuntimeError("Nenhuma conta retornada em /accounts.")
        cand = accounts_list[0]
        acc_id = str(cand.get("id") or cand.get("accountId") or cand.get("account_id") or "").strip()
        if not acc_id:
            raise RuntimeError(f"Formato inesperado de conta: {cand}")
        self.account_id = acc_id
        return payload

    def fetch_balances(self) -> Any:
        if not self.account_id:
            raise RuntimeError("accountId ausente antes de /balances.")
        code, payload, _ = _http_request(
            "GET", f"{self.base}/accounts/{self.account_id}/balances",
            headers=self._headers(add_account=True), timeout=self.timeout)
        if code != 200:
            raise RuntimeError(f"/accounts/{self.account_id}/balances falhou: HTTP {code} - {payload}")
        return payload

    # ---------- Discovery da rota de ORDERS ----------
    def discover_orders_base(self) -> str:
        if not self.account_id:
            raise RuntimeError("accountId ausente para descobrir rota de ORDERS.")

        print(f"[{_now_ts()}] Descobrindo rota ORDERS...")
        for base_path in self.ORDERS_BASES:
            path = base_path.replace("{accountId}", self.account_id)
            # critério: GET listagem com status=open. Se 2xx, elegemos.
            code, payload, _ = _http_request(
                "GET", f"{self.base}{path}",
                headers=self._headers(add_account=True),
                params={"status": "open"},
                timeout=self.timeout
            )
            if code in (200, 201, 202, 204):
                self.orders_base_chosen = base_path
                print(f"[{_now_ts()}] rota ORDERS eleita: {base_path}")
                return base_path
            elif code == 404:
                print(f"[{_now_ts()}] 404 em {path} — tentando próxima base...")
            else:
                print(f"[{_now_ts()}] {code} em {path} — não é 404; parando para sua análise.")
                # Se a API devolver, por ex., 400 com erro “falta param”, ainda assim vale dump.
                # Não elegemos, mas registramos.
        raise RuntimeError("Não foi possível eleger uma rota ORDERS (todas retornaram 404 ou erro).")

    def fetch_open_orders(self) -> Any:
        if not self.orders_base_chosen:
            raise RuntimeError("Rota ORDERS não foi descoberta.")
        path = self.orders_base_chosen.replace("{accountId}", self.account_id or "")
        code, payload, _ = _http_request(
            "GET", f"{self.base}{path}",
            headers=self._headers(add_account=True),
            params={"status": "open"},
            timeout=self.timeout
        )
        # Mesmo se não for 200, vamos devolver o payload para inspeção.
        if code != 200:
            print(f"[{_now_ts()}] AVISO: open_orders retornou HTTP {code} — dumpando assim mesmo.")
        return {"http_status": code, "data": payload, "path": path}

    # ---------- Pipeline principal ----------
    def run(self):
        # 1) Descobrir/definir base
        self.discover_base()

        # 2) Garantir token
        self.ensure_token()

        # 3) /accounts
        accounts = self.fetch_accounts()
        print(f"[{_now_ts()}] /accounts -> OK")
        _save_dump("accounts", accounts)

        # 4) /balances
        balances = self.fetch_balances()
        print(f"[{_now_ts()}] /balances -> OK")
        _save_dump("balances", balances)

        # 5) Descobrir rota /orders
        try:
            self.discover_orders_base()
        except Exception as e:
            print(f"[{_now_ts()}] Falha no discovery de ORDERS: {e}")

        # 6) /orders?status=open (se houver base)
        if self.orders_base_chosen:
            open_orders = self.fetch_open_orders()
            print(f"[{_now_ts()}] /orders (open) -> HTTP {open_orders.get('http_status')}")
            _save_dump("open_orders", open_orders)
        else:
            print(f"[{_now_ts()}] PULANDO open_orders (rota não descoberta).")


# ------------------------------- main ------------------------------------
def main():
    parser = argparse.ArgumentParser(description="MB v4 Inspector (descobre base/ordens e faz dumps).")
    parser.add_argument("--ini", default="config.txt", help="Caminho do INI (default: ./config.txt)")
    args = parser.parse_args()

    ini_path = args.ini
    if not os.path.isfile(ini_path):
        print(f"INI não encontrado em: {ini_path}")
        sys.exit(2)

    try:
        client = MBV4Client(ini_path)
        client.run()
        print(f"[{_now_ts()}] FINALIZADO com sucesso.")
    except Exception as e:
        print(f"[{_now_ts()}] ERRO fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
