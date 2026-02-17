from __future__ import annotations

import threading
import time
from collections import deque
from typing import Dict, Any, Deque


class MetricsService:
    def __init__(self, window_sec: int = 60, max_points: int = 512):
        self.window_sec = max(10, int(window_sec))
        self.max_points = max(64, int(max_points))
        self._lock = threading.Lock()
        self._cycle_latencies: Dict[str, Deque[tuple[float, float]]] = {}
        self._orders: Dict[str, Deque[float]] = {}
        self._errors: Dict[str, Dict[str, Deque[float]]] = {}
        self._ws_state: Dict[str, Dict[str, Any]] = {}
        self._circuit_breaker: Dict[str, Dict[str, Any]] = {}

    def _cleanup(self, dq: Deque, now: float) -> None:
        cutoff = now - self.window_sec
        while dq and float(dq[0][0] if isinstance(dq[0], tuple) else dq[0]) < cutoff:
            dq.popleft()

    def record_cycle_latency(self, tenant_id: str, latency_ms: float) -> None:
        now = time.time()
        with self._lock:
            dq = self._cycle_latencies.setdefault(tenant_id, deque(maxlen=self.max_points))
            dq.append((now, float(latency_ms)))
            self._cleanup(dq, now)

    def record_order_created(self, tenant_id: str) -> None:
        now = time.time()
        with self._lock:
            dq = self._orders.setdefault(tenant_id, deque(maxlen=self.max_points * 4))
            dq.append(now)
            self._cleanup(dq, now)

    def record_exchange_error(self, tenant_id: str, exchange: str) -> None:
        now = time.time()
        ex = str(exchange or "unknown").lower()
        with self._lock:
            ex_map = self._errors.setdefault(tenant_id, {})
            dq = ex_map.setdefault(ex, deque(maxlen=self.max_points * 4))
            dq.append(now)
            self._cleanup(dq, now)

    def set_ws_state(self, tenant_id: str, rows: list[dict[str, Any]]) -> None:
        with self._lock:
            self._ws_state[tenant_id] = {
                "updatedAt": time.time(),
                "items": rows or [],
            }

    def set_circuit_breaker_state(self, tenant_id: str, state: Dict[str, Dict[str, Any]]) -> None:
        with self._lock:
            self._circuit_breaker[tenant_id] = state or {}

    def get_metrics(self, tenant_id: str) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            cycle_dq = self._cycle_latencies.setdefault(tenant_id, deque(maxlen=self.max_points))
            self._cleanup(cycle_dq, now)
            lat_values = [float(v) for _, v in list(cycle_dq)]
            cycle_latency_ms = round(sum(lat_values) / len(lat_values), 2) if lat_values else 0.0

            orders_dq = self._orders.setdefault(tenant_id, deque(maxlen=self.max_points * 4))
            self._cleanup(orders_dq, now)
            orders_per_minute = len(orders_dq)

            err_map = self._errors.setdefault(tenant_id, {})
            error_rate_by_exchange: Dict[str, int] = {}
            for ex, dq in err_map.items():
                self._cleanup(dq, now)
                error_rate_by_exchange[ex] = len(dq)

            ws_state = dict(self._ws_state.get(tenant_id) or {"items": []})
            circuit_state = dict(self._circuit_breaker.get(tenant_id) or {})

        return {
            "cycleLatencyMs": cycle_latency_ms,
            "ordersPerMinute": int(orders_per_minute),
            "errorRateByExchange": error_rate_by_exchange,
            "circuitBreakerState": circuit_state,
            "wsState": ws_state,
        }
