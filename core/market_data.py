from __future__ import annotations

import asyncio
import contextlib
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

try:
    from utils.logger import get_logger
except Exception:
    import logging

    def get_logger(name: str):
        return logging.getLogger(name)


log = get_logger("marketdata")


CacheKey = Tuple[str, str, str]


@dataclass
class MarketDataEntry:
    snapshot: Dict[str, Any]
    timestamp: int
    source: str
    state: str
    seq: int = 0
    last_error: str = ""


class BaseWsOrderBookProvider:
    async def connect(self, tenant_id: str, exchange: str, symbol: str) -> None:
        raise NotImplementedError

    async def recv_snapshot(self, tenant_id: str, exchange: str, symbol: str) -> Dict[str, Any]:
        raise NotImplementedError

    async def close(self, tenant_id: str, exchange: str, symbol: str) -> None:
        return None


class MEXCWsOrderBookProvider(BaseWsOrderBookProvider):
    """Provider mínimo para MEXC spot public depth."""

    def __init__(self, depth_limit: int = 20, timeout_ms: int = 3000):
        self.depth_limit = int(depth_limit)
        self.timeout_ms = int(timeout_ms)
        self._sockets: Dict[Tuple[str, str], aiohttp.ClientWebSocketResponse] = {}
        self._sessions: Dict[str, aiohttp.ClientSession] = {}

    @staticmethod
    def _to_channel_symbol(symbol: str) -> str:
        return symbol.replace("/", "").upper()

    async def connect(self, tenant_id: str, exchange: str, symbol: str) -> None:
        key = (tenant_id, symbol)
        if key in self._sockets:
            return
        session = self._sessions.get(tenant_id)
        if session is None or session.closed:
            session = aiohttp.ClientSession()
            self._sessions[tenant_id] = session
        ws = await session.ws_connect(
            "wss://wbs.mexc.com/ws",
            heartbeat=20,
            timeout=self.timeout_ms / 1000.0,
        )
        ch_sym = self._to_channel_symbol(symbol)
        channel = f"spot@public.limit.depth.v3.api@{ch_sym}@{self.depth_limit}"
        await ws.send_json({"method": "SUBSCRIPTION", "params": [channel], "id": int(time.time() * 1000)})
        self._sockets[key] = ws

    async def recv_snapshot(self, tenant_id: str, exchange: str, symbol: str) -> Dict[str, Any]:
        key = (tenant_id, symbol)
        ws = self._sockets[key]
        while True:
            msg = await ws.receive(timeout=self.timeout_ms / 1000.0)
            if msg.type == aiohttp.WSMsgType.CLOSED:
                raise RuntimeError("ws_closed")
            if msg.type == aiohttp.WSMsgType.ERROR:
                raise RuntimeError("ws_error")
            if msg.type not in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                continue
            data = msg.json()
            if not isinstance(data, dict):
                continue
            payload = data.get("d") or data.get("data") or data
            bids = payload.get("bids") or []
            asks = payload.get("asks") or []
            if not bids and not asks:
                continue
            return {"bids": bids, "asks": asks, "timestamp": int(time.time() * 1000)}

    async def close(self, tenant_id: str, exchange: str, symbol: str) -> None:
        key = (tenant_id, symbol)
        ws = self._sockets.pop(key, None)
        if ws:
            with contextlib.suppress(Exception):
                await ws.close()


class PollingOrderBookProvider:
    def __init__(self, ex_hub, orderbook_limit: int):
        self.ex_hub = ex_hub
        self.orderbook_limit = int(orderbook_limit)

    async def fetch(self, exchange: str, symbol: str) -> Dict[str, Any]:
        return await self.ex_hub.raw_fetch_orderbook(exchange, symbol, limit=self.orderbook_limit)


class MarketDataService:
    def __init__(self, cfg, ex_hub, tenant_id: str, ws_providers: Optional[Dict[str, BaseWsOrderBookProvider]] = None):
        self.cfg = cfg
        self.ex_hub = ex_hub
        self.tenant_id = tenant_id
        self.ws_stale_ms = int(os.getenv("MARKETDATA_WS_STALE_MS", cfg.get("MARKETDATA", "WS_STALE_MS", fallback="3000")))
        self.ws_reconnect_ms = int(os.getenv("MARKETDATA_WS_RECONNECT_MS", cfg.get("MARKETDATA", "WS_RECONNECT_MS", fallback="5000")))
        self.poll_interval_ms = int(os.getenv("MARKETDATA_POLL_INTERVAL_MS", cfg.get("MARKETDATA", "POLL_INTERVAL_MS", fallback="2000")))
        self.orderbook_limit = int(os.getenv("ORDERBOOK_LIMIT", cfg.get("MARKETDATA", "ORDERBOOK_LIMIT", fallback="20")))

        self._cache: Dict[CacheKey, MarketDataEntry] = {}
        self._lock = asyncio.Lock()
        self._tasks: Dict[CacheKey, asyncio.Task] = {}
        self._running = False

        self.polling_provider = PollingOrderBookProvider(ex_hub=ex_hub, orderbook_limit=self.orderbook_limit)
        self.ws_providers = ws_providers or {"mexc": MEXCWsOrderBookProvider(depth_limit=self.orderbook_limit, timeout_ms=self.ws_stale_ms)}

    def _key(self, exchange: str, symbol: str) -> CacheKey:
        return (self.tenant_id, exchange.lower(), symbol.upper())

    def supports_ws(self, exchange: str) -> bool:
        return exchange.lower() in self.ws_providers

    async def start(self, pairs: List[str]) -> None:
        self._running = True
        streams: List[Tuple[str, str]] = []
        for ex_name in getattr(self.ex_hub, "enabled_ids", []):
            for pair in pairs:
                for side in ("BUY", "SELL"):
                    sym = self.ex_hub.resolve_symbol_local(ex_name, side, pair)
                    if sym:
                        streams.append((ex_name, sym))
        dedup = sorted(set(streams))
        for exchange, symbol in dedup:
            key = self._key(exchange, symbol)
            if key in self._tasks:
                continue
            self._tasks[key] = asyncio.create_task(self._run_stream(exchange, symbol), name=f"md:{exchange}:{symbol}")

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def _set_entry(self, exchange: str, symbol: str, snapshot: Dict[str, Any], source: str, state: str, error: str = "") -> None:
        key = self._key(exchange, symbol)
        now_ms = int(time.time() * 1000)
        async with self._lock:
            prev = self._cache.get(key)
            seq = (prev.seq + 1) if prev else 1
            self._cache[key] = MarketDataEntry(snapshot=snapshot, timestamp=now_ms, source=source, state=state, seq=seq, last_error=error)

    async def _mark_state(self, exchange: str, symbol: str, source: str, state: str, error: str = "") -> None:
        key = self._key(exchange, symbol)
        async with self._lock:
            prev = self._cache.get(key)
            if prev:
                prev.source = source
                prev.state = state
                prev.last_error = error
            else:
                self._cache[key] = MarketDataEntry(snapshot={"bids": [], "asks": []}, timestamp=0, source=source, state=state, seq=0, last_error=error)

    async def _run_stream(self, exchange: str, symbol: str) -> None:
        circuit_state = "WS_ACTIVE" if self.supports_ws(exchange) else "POLL_ACTIVE"
        ws_provider = self.ws_providers.get(exchange.lower())
        while self._running:
            try:
                if circuit_state == "WS_ACTIVE" and ws_provider:
                    await ws_provider.connect(self.tenant_id, exchange, symbol)
                    log.info("MARKETDATA_WS_CONNECTED tenantId=%s exchange=%s symbol=%s source=WS state=OK", self.tenant_id, exchange, symbol)
                    last_msg_ms = int(time.time() * 1000)
                    while self._running:
                        snap = await ws_provider.recv_snapshot(self.tenant_id, exchange, symbol)
                        last_msg_ms = int(time.time() * 1000)
                        await self._set_entry(exchange, symbol, snap, source="WS", state="OK")
                        entry = await self.get_order_book(self.tenant_id, exchange, symbol)
                        log.info("MARKETDATA_WS_MESSAGE tenantId=%s exchange=%s symbol=%s source=WS state=OK ageMs=%s seq=%s", self.tenant_id, exchange, symbol, entry.get("ageMs"), entry.get("seq"))
                        if (int(time.time() * 1000) - last_msg_ms) > self.ws_stale_ms:
                            raise TimeoutError("stale_ws")
                else:
                    raise RuntimeError("poll_mode")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                err = str(exc)
                if ws_provider and circuit_state == "WS_ACTIVE":
                    log.warning("MARKETDATA_WS_STALE_DETECTED tenantId=%s exchange=%s symbol=%s source=WS state=DEGRADED errorCode=%s", self.tenant_id, exchange, symbol, err)
                circuit_state = "POLL_ACTIVE"
                await self._mark_state(exchange, symbol, source="POLL", state="DEGRADED", error=err)
                log.warning("MARKETDATA_FALLBACK_TO_POLL tenantId=%s exchange=%s symbol=%s source=POLL state=DEGRADED errorCode=%s", self.tenant_id, exchange, symbol, err)

                poll_started = int(time.time() * 1000)
                while self._running and circuit_state == "POLL_ACTIVE":
                    try:
                        snap = await self.polling_provider.fetch(exchange, symbol)
                        await self._set_entry(exchange, symbol, snap, source="POLL", state="DEGRADED")
                        entry = await self.get_order_book(self.tenant_id, exchange, symbol)
                        log.info("MARKETDATA_POLL_TICK tenantId=%s exchange=%s symbol=%s source=POLL state=DEGRADED ageMs=%s seq=%s", self.tenant_id, exchange, symbol, entry.get("ageMs"), entry.get("seq"))
                    except Exception as poll_exc:
                        await self._mark_state(exchange, symbol, source="POLL", state="DISCONNECTED", error=str(poll_exc))
                    await asyncio.sleep(self.poll_interval_ms / 1000.0)

                    if ws_provider and (int(time.time() * 1000) - poll_started) >= self.ws_reconnect_ms:
                        circuit_state = "RECOVERING_WS"
                        break

                if circuit_state == "RECOVERING_WS":
                    log.info("MARKETDATA_WS_RECONNECT_ATTEMPT tenantId=%s exchange=%s symbol=%s source=WS state=RECOVERING_WS", self.tenant_id, exchange, symbol)
                    try:
                        await ws_provider.close(self.tenant_id, exchange, symbol)
                    except Exception:
                        pass
                    circuit_state = "WS_ACTIVE"
                    log.info("MARKETDATA_WS_RECOVERED tenantId=%s exchange=%s symbol=%s source=WS state=OK", self.tenant_id, exchange, symbol)

    async def get_order_book(self, tenant_id: str, exchange: str, symbol: str) -> Dict[str, Any]:
        key = (tenant_id, exchange.lower(), symbol.upper())
        now_ms = int(time.time() * 1000)
        async with self._lock:
            entry = self._cache.get(key)
            if entry:
                age_ms = max(0, now_ms - int(entry.timestamp or 0))
                return {
                    "snapshot": entry.snapshot,
                    "timestamp": entry.timestamp,
                    "source": entry.source,
                    "state": entry.state,
                    "seq": entry.seq,
                    "lastError": entry.last_error,
                    "ageMs": age_ms,
                    "stale": bool(entry.timestamp and age_ms > self.ws_stale_ms),
                }

        snap = await self.polling_provider.fetch(exchange, symbol)
        await self._set_entry(exchange, symbol, snap, source="POLL", state="DEGRADED")
        return await self.get_order_book(tenant_id, exchange, symbol)

    async def get_status_rows(self, exchange: Optional[str] = None, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        now_ms = int(time.time() * 1000)
        rows: List[Dict[str, Any]] = []
        async with self._lock:
            for (tenant_id, ex, sym), entry in self._cache.items():
                if tenant_id != self.tenant_id:
                    continue
                if exchange and ex != exchange.lower():
                    continue
                if symbol and sym != symbol.upper():
                    continue
                best_bid = entry.snapshot.get("bids", [[None, None]])[0] if entry.snapshot.get("bids") else [None, None]
                best_ask = entry.snapshot.get("asks", [[None, None]])[0] if entry.snapshot.get("asks") else [None, None]
                rows.append({
                    "exchange": ex,
                    "symbol": sym,
                    "source": entry.source,
                    "state": entry.state,
                    "ageMs": max(0, now_ms - int(entry.timestamp or 0)) if entry.timestamp else None,
                    "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime((entry.timestamp or 0) / 1000.0)) if entry.timestamp else None,
                    "bestBid": {"price": best_bid[0], "qty": best_bid[1]},
                    "bestAsk": {"price": best_ask[0], "qty": best_ask[1]},
                    "lastError": entry.last_error or None,
                })
        return sorted(rows, key=lambda r: (r["exchange"], r["symbol"]))
