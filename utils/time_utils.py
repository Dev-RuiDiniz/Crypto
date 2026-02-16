# utils/time_utils.py
# Helpers de tempo simples

from __future__ import annotations
import time
from datetime import datetime, timezone

def now_ts() -> float:
    return time.time()

def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def sleep_ms(ms: int):
    time.sleep(max(0, ms) / 1000.0)

def human_duration(seconds: float) -> str:
    s = int(max(0, seconds))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"
