from core.exchange_circuit_breaker import ExchangeCircuitBreaker
from core.metrics_service import MetricsService


def test_circuit_breaker_opens_and_recovers():
    cb = ExchangeCircuitBreaker(failure_threshold=2, open_backoff_sec=1)
    tenant = "t1"
    ex = "mexc"

    ok, _ = cb.allow_request(tenant, ex)
    assert ok
    assert cb.on_failure(tenant, ex) is False
    assert cb.on_failure(tenant, ex) is True

    ok, state = cb.allow_request(tenant, ex)
    assert not ok
    assert state == "OPEN"


def test_metrics_collects_basic_counters():
    m = MetricsService(window_sec=60)
    tenant = "t1"
    m.record_cycle_latency(tenant, 100)
    m.record_cycle_latency(tenant, 200)
    m.record_order_created(tenant)
    m.record_exchange_error(tenant, "binance")
    m.set_ws_state(tenant, [{"exchange": "mexc", "state": "WS_ACTIVE"}])
    m.set_circuit_breaker_state(tenant, {"binance": {"state": "OPEN"}})

    data = m.get_metrics(tenant)
    assert data["cycleLatencyMs"] >= 100
    assert data["ordersPerMinute"] >= 1
    assert data["errorRateByExchange"]["binance"] >= 1
    assert data["circuitBreakerState"]["binance"]["state"] == "OPEN"
