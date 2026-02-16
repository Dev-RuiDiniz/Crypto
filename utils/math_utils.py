# utils/math_utils.py
# Utilitários numéricos genéricos

from __future__ import annotations
from typing import Iterable, Optional, Sequence, Tuple

import math

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def median(values: Sequence[float]) -> Optional[float]:
    arr = [float(v) for v in values if v is not None]
    if not arr:
        return None
    arr.sort()
    n = len(arr)
    m = n // 2
    if n % 2 == 1:
        return arr[m]
    return (arr[m - 1] + arr[m]) / 2.0

def vwap(prices: Sequence[float], vols: Sequence[float]) -> Optional[float]:
    if not prices or not vols or len(prices) != len(vols):
        return None
    num = 0.0
    den = 0.0
    for p, v in zip(prices, vols):
        if p is None or v is None:
            continue
        num += float(p) * float(v)
        den += float(v)
    if den <= 0:
        return None
    return num / den

def to_bps(delta: float, base: float) -> Optional[float]:
    try:
        if base == 0:
            return None
        return (delta / base) * 10_000.0
    except Exception:
        return None

def pct_change(new: float, old: float) -> Optional[float]:
    try:
        if old == 0:
            return None
        return (new - old) / old * 100.0
    except Exception:
        return None

def safe_float(x) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None

def almost_equal(a: float, b: float, tol: float = 1e-12) -> bool:
    return abs(float(a) - float(b)) <= tol

def round_step_floor(value: float, step: float) -> float:
    if step is None or step <= 0:
        return float(value)
    return math.floor(float(value) / float(step)) * float(step)

def round_precision(value: float, precision: int) -> float:
    if precision is None or precision < 0:
        return float(value)
    fmt = "{:0." + str(int(precision)) + "f}"
    return float(fmt.format(float(value)))
