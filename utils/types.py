# utils/types.py
# Dataclasses para planejar e rastrear ordens (com tipagem forte e helpers)

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, Literal

Side = Literal["buy", "sell"]


def _split_pair(sym: str) -> tuple[str, str]:
    s = (sym or "").strip().upper()
    if "/" in s:
        b, q = s.split("/", 1)
        return b.strip(), q.strip()
    # fallback: assume base em 'sym' e quote USDT
    return s, "USDT"


@dataclass(slots=True)
class OrderPlan:
    pair: str                 # ex.: "BTC/USDT"
    side: Side                # "buy" | "sell"
    ex_name: str              # mercadobitcoin, novadax, gate, mexc...
    symbol_local: str         # ex.: "BTC/BRL" ou "BTC/USDT"
    price_usdt: float         # alvo em USDT
    price_local: float        # alvo na moeda de cotação local
    amount: float             # quantidade em moeda base (ex.: BTC)
    note: Optional[str] = None  # motivo/comentário (ajuste, enforce minima, etc.)
    created_ts: float = field(default_factory=lambda: __import__("time").time())

    # --- helpers ---
    @property
    def base(self) -> str:
        b, _ = _split_pair(self.symbol_local or self.pair)
        return b

    @property
    def quote(self) -> str:
        _, q = _split_pair(self.symbol_local or self.pair)
        return q

    @property
    def notional_local(self) -> float:
        try:
            return float(self.amount) * float(self.price_local)
        except Exception:
            return 0.0

    @property
    def notional_usdt(self) -> float:
        try:
            return float(self.amount) * float(self.price_usdt)
        except Exception:
            return 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def __post_init__(self):
        s = str(self.side).lower()
        if s not in ("buy", "sell"):
            raise ValueError(f"side inválido: {self.side!r}")
        if self.amount <= 0 or self.price_local <= 0 or self.price_usdt <= 0:
            # Mantém simples: validações mínimas; regras de mínimos ficam no router/adapters
            raise ValueError("amount/price devem ser > 0")


@dataclass(slots=True)
class LiveOrder:
    order_id: str
    pair: str
    side: Side
    ex_name: str
    symbol_local: str
    price_local: float
    amount: float
    status: str = "open"                 # open / closed / canceled
    filled_amount: float = 0.0           # total executado em base
    average_price: Optional[float] = None  # preço médio executado (local)
    created_ts: float = field(default_factory=lambda: __import__("time").time())
    updated_ts: Optional[float] = None

    # --- helpers ---
    @property
    def base(self) -> str:
        b, _ = _split_pair(self.symbol_local or self.pair)
        return b

    @property
    def quote(self) -> str:
        _, q = _split_pair(self.symbol_local or self.pair)
        return q

    @property
    def is_open(self) -> bool:
        return str(self.status).lower() == "open"

    @property
    def is_closed(self) -> bool:
        s = str(self.status).lower()
        return s in ("closed", "filled")

    @property
    def notional_local(self) -> float:
        try:
            return float(self.amount) * float(self.price_local)
        except Exception:
            return 0.0

    def mark_update(self):
        self.updated_ts = __import__("time").time()

    def to_dict(self) -> dict:
        return asdict(self)

    def __post_init__(self):
        s = str(self.side).lower()
        if s not in ("buy", "sell"):
            raise ValueError(f"side inválido: {self.side!r}")
        if self.amount <= 0 or self.price_local <= 0:
            raise ValueError("amount/price_local devem ser > 0")
