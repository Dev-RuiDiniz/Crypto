from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class CircuitState:
    failure_count: int = 0
    last_failure: float = 0.0
    state: str = "CLOSED"  # CLOSED | OPEN | HALF_OPEN
    half_open_inflight: bool = False


class ExchangeCircuitBreaker:
    def __init__(self, failure_threshold: int = 5, open_backoff_sec: float = 30.0):
        self.failure_threshold = max(1, int(failure_threshold))
        self.open_backoff_sec = max(1.0, float(open_backoff_sec))
        self._lock = threading.Lock()
        self._states: Dict[str, CircuitState] = {}

    @staticmethod
    def _key(tenant_id: str, exchange: str) -> str:
        return f"{str(tenant_id or 'default').lower()}:{str(exchange or '').lower()}"

    def _get(self, tenant_id: str, exchange: str) -> CircuitState:
        key = self._key(tenant_id, exchange)
        if key not in self._states:
            self._states[key] = CircuitState()
        return self._states[key]

    def allow_request(self, tenant_id: str, exchange: str) -> tuple[bool, str]:
        now = time.time()
        with self._lock:
            st = self._get(tenant_id, exchange)
            if st.state == "OPEN":
                if (now - st.last_failure) >= self.open_backoff_sec:
                    st.state = "HALF_OPEN"
                    st.half_open_inflight = False
                else:
                    return False, "OPEN"

            if st.state == "HALF_OPEN":
                if st.half_open_inflight:
                    return False, "HALF_OPEN_INFLIGHT"
                st.half_open_inflight = True
                return True, "HALF_OPEN"

            return True, st.state

    def on_success(self, tenant_id: str, exchange: str) -> None:
        with self._lock:
            st = self._get(tenant_id, exchange)
            st.failure_count = 0
            st.state = "CLOSED"
            st.half_open_inflight = False

    def on_failure(self, tenant_id: str, exchange: str) -> bool:
        now = time.time()
        with self._lock:
            st = self._get(tenant_id, exchange)
            st.failure_count += 1
            st.last_failure = now
            st.half_open_inflight = False
            if st.state == "HALF_OPEN" or st.failure_count >= self.failure_threshold:
                st.state = "OPEN"
                return True
            return False

    def export_states(self, tenant_id: str) -> Dict[str, Dict[str, Any]]:
        prefix = f"{str(tenant_id or 'default').lower()}:"
        out: Dict[str, Dict[str, Any]] = {}
        with self._lock:
            for key, st in self._states.items():
                if not key.startswith(prefix):
                    continue
                ex = key.split(":", 1)[1]
                out[ex] = {
                    "state": st.state,
                    "failureCount": int(st.failure_count),
                    "lastFailureTs": float(st.last_failure or 0.0),
                    "backoffSec": float(self.open_backoff_sec),
                }
        return out
