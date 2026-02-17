#!/usr/bin/env python3
"""Teste de carga leve multi-par para Sprint 10.

Executa chamadas concorrentes contra endpoints principais para validar estabilidade
operacional sem travamentos, medindo latência média e crescimento de memória.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time
import tracemalloc
from urllib import request

PAIRS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "ADA-USDT"]


def fetch_json(url: str) -> int:
    started = time.perf_counter()
    with request.urlopen(url, timeout=5) as resp:
        _ = resp.read()
    return int((time.perf_counter() - started) * 1000)


async def run(base_url: str, minutes: float, concurrency: int) -> None:
    duration_sec = max(10.0, minutes * 60.0)
    end = time.time() + duration_sec
    latencies = []
    errors = 0

    tracemalloc.start()
    mem_start, _ = tracemalloc.get_traced_memory()

    async def worker() -> None:
        nonlocal errors
        loop = asyncio.get_running_loop()
        while time.time() < end:
            pair = PAIRS[int(time.time()) % len(PAIRS)]
            urls = [
                f"{base_url}/api/mids?pair={pair}",
                f"{base_url}/api/orders?state=open",
                f"{base_url}/api/tenants/default/marketdata/orderbook-status",
                f"{base_url}/api/tenants/default/metrics",
            ]
            for u in urls:
                try:
                    ms = await loop.run_in_executor(None, fetch_json, u)
                    latencies.append(ms)
                except Exception:
                    errors += 1
            await asyncio.sleep(0.2)

    await asyncio.gather(*[worker() for _ in range(max(1, concurrency))])
    mem_end, mem_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    avg = statistics.mean(latencies) if latencies else 0.0
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else (max(latencies) if latencies else 0)

    print("Load test summary")
    print(f"- samples: {len(latencies)}")
    print(f"- errors: {errors}")
    print(f"- latency_avg_ms: {avg:.2f}")
    print(f"- latency_p95_ms: {p95:.2f}")
    print(f"- memory_growth_kb: {(mem_end - mem_start)/1024:.2f}")
    print(f"- memory_peak_kb: {mem_peak/1024:.2f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--minutes", type=float, default=1.0)
    ap.add_argument("--concurrency", type=int, default=3)
    args = ap.parse_args()
    asyncio.run(run(args.base_url, args.minutes, args.concurrency))
