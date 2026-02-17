# api/shared_state.py
"""
Estado compartilhado em MEMÓRIA entre o bot (MainMonitor) e a API Flask.

- O bot (core/monitors.py) chama: set_snapshot(data)
- A API (api/handlers.py) chama: get_snapshot() para responder /api/balances,
  /api/orders, /api/mids etc.

Tudo protegido por lock para ser seguro entre threads.
"""

from __future__ import annotations

import threading
from typing import Dict, Any, Optional

# Lock para acesso concorrente
_LOCK = threading.Lock()
_SNAPSHOT: Optional[Dict[str, Any]] = None


def _empty_snapshot() -> Dict[str, Any]:
    """
    Snapshot vazio padrão, usado antes do primeiro set_snapshot()
    ou em caso de erro.
    """
    return {
        "timestamp": None,
        "mode": "UNKNOWN",
        "pairs": [],
        "exchanges": [],
        "balances": {},
        "mids": {},
        "orders": [],
        # opcional: espaço para eventos, se um dia quiser expor no front
        "events": [],
    }


def _ensure_basic_keys(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Garante que o dict tenha sempre as chaves básicas esperadas pelo restante
    da aplicação. Não altera estrutura de orders (pode ser list ou dict).
    """
    data.setdefault("timestamp", None)
    data.setdefault("mode", "UNKNOWN")
    data.setdefault("pairs", [])
    data.setdefault("exchanges", [])
    data.setdefault("balances", {})
    data.setdefault("mids", {})
    data.setdefault("orders", [])
    # events é opcional – só garante que exista se o produtor mandar
    if "events" not in data:
        data["events"] = []
    if "metrics" not in data:
        data["metrics"] = {}
    return data


def set_snapshot(data: Dict[str, Any]) -> None:
    """
    Atualiza o snapshot em memória.

    Deve ser chamado pelo MainMonitor (core/monitors.py) a cada ciclo,
    depois de atualizar mids, ordens, etc.

    Exemplo de uso no monitor:
        snap = self._build_api_snapshot(ref_map, mids_map)
        set_snapshot(snap)
    """
    global _SNAPSHOT

    if not isinstance(data, dict):
        data = {}

    # Não mexe na estrutura de 'orders' além de garantir que exista a chave.
    safe_data = _ensure_basic_keys(dict(data))

    with _LOCK:
        # copia rasa para evitar que alguém altere o dict original fora daqui
        _SNAPSHOT = safe_data


def get_snapshot() -> Dict[str, Any]:
    """
    Retorna o snapshot atual em memória.

    Se ainda não houver snapshot, devolve um snapshot vazio, mas sempre
    com as chaves esperadas (`balances`, `mids`, `orders`, etc).
    """
    with _LOCK:
        if not isinstance(_SNAPSHOT, dict):
            return _empty_snapshot()

        # Cópia rasa para evitar mutação externa
        snap = dict(_SNAPSHOT)

    return _ensure_basic_keys(snap)


def debug_info() -> Dict[str, Any]:
    """
    Retorna um resumo do snapshot para debug (pode ser usado em /api/debug,
    se quiser, ou em prints manuais).

    Não é obrigatório usar, mas ajuda a saber se o bot está de fato
    publicando algo em memória.
    """
    s = get_snapshot()
    balances = s.get("balances") or {}
    mids = s.get("mids") or {}
    orders = s.get("orders") or []
    events = s.get("events") or []

    # orders pode ser list ou dict (compatível com handlers.get_orders)
    if isinstance(orders, dict):
        orders_count = sum(len(v or []) for v in orders.values())
    elif isinstance(orders, list):
        orders_count = len(orders)
    else:
        orders_count = 0

    return {
        "timestamp": s.get("timestamp"),
        "mode": s.get("mode"),
        "pairs": s.get("pairs"),
        "exchanges": s.get("exchanges"),
        "balances_exchanges": len(balances.keys()),
        "mids_pairs": len(mids.keys()),
        "orders_count": orders_count,
        "events_count": len(events) if isinstance(events, list) else 0,
    }
